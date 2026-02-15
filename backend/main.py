"""
Earnings Intelligence — Backend API v6
- YouTube Data API v3 for video listing
- OpenRouter (free models) for AI analysis
- Resend API for email (one per analysis)
- Server-side scheduler (persists across browser sessions)
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────
YOUTUBE_API_KEY    = os.getenv("YOUTUBE_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")  # kept for fallback
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY", "AIzaSyACgFJcwAt2-r8WKxtDTYblKkCLM7hpd74")
RESEND_API_KEY     = os.getenv("RESEND_API_KEY", "")
TRENDLYNE_CHANNEL_ID = "UCznm57tnYpUpc2q2FmO3R3Q"
JSONBIN_API_KEY    = os.getenv("JSONBIN_API_KEY", "")
JSONBIN_SCHEDULE_BIN = os.getenv("JSONBIN_SCHEDULE_BIN", "")   # set after first create
JSONBIN_LOGS_BIN     = os.getenv("JSONBIN_LOGS_BIN", "")       # set after first create
MAX_LOG_ENTRIES    = 200
JSONBIN_BASE       = "https://api.jsonbin.io/v3"

# ── JSONBIN STORE ─────────────────────────────────────────────────────────────
JSONBIN_HEADERS = {
    "Content-Type": "application/json",
    "X-Master-Key": "$2a$10$bD4cfepRAvt78BXnQtdZs.KXPjGmCIkcq2J8Jo9xYVExCwml9FHnW",
    "X-Bin-Private": "false",
}

def _bin_id(env_key: str) -> str:
    return os.getenv(env_key, "")

def _create_bin(name: str, data: dict) -> str:
    """Create a new JSONBin and return its ID."""
    r = httpx.post(
        f"{JSONBIN_BASE}/b",
        headers={**JSONBIN_HEADERS, "X-Bin-Name": name},
        json=data, timeout=15,
    )
    if r.status_code in (200, 201):
        bin_id = r.json()["metadata"]["id"]
        logger.info(f"Created JSONBin '{name}': {bin_id}")
        return bin_id
    logger.error(f"Failed to create bin '{name}': {r.text}")
    return ""

def _read_bin(bin_id: str) -> dict:
    r = httpx.get(f"{JSONBIN_BASE}/b/{bin_id}/latest",
                  headers=JSONBIN_HEADERS, timeout=15)
    if r.status_code == 200:
        return r.json().get("record", {})
    return {}

def _write_bin(bin_id: str, data: dict) -> bool:
    r = httpx.put(f"{JSONBIN_BASE}/b/{bin_id}",
                  headers=JSONBIN_HEADERS, json=data, timeout=15)
    return r.status_code == 200

# ── SCHEDULER STORE ───────────────────────────────────────────────────────────
_schedule_bin_id = ""
_logs_bin_id     = ""

def _get_schedule_bin() -> str:
    global _schedule_bin_id
    if _schedule_bin_id:
        return _schedule_bin_id
    _schedule_bin_id = os.getenv("JSONBIN_SCHEDULE_BIN", "")
    if not _schedule_bin_id:
        # Auto-create on first run
        _schedule_bin_id = _create_bin("ei-schedule", {"active": False})
        logger.info(f"Add to Render env: JSONBIN_SCHEDULE_BIN={_schedule_bin_id}")
    return _schedule_bin_id

def _get_logs_bin() -> str:
    global _logs_bin_id
    if _logs_bin_id:
        return _logs_bin_id
    _logs_bin_id = os.getenv("JSONBIN_LOGS_BIN", "")
    if not _logs_bin_id:
        _logs_bin_id = _create_bin("ei-logs", {"logs": []})
        logger.info(f"Add to Render env: JSONBIN_LOGS_BIN={_logs_bin_id}")
    return _logs_bin_id

def load_schedule() -> dict:
    try:
        bin_id = _get_schedule_bin()
        if bin_id:
            return _read_bin(bin_id) or {"active": False}
    except Exception as e:
        logger.error(f"load_schedule error: {e}")
    return {"active": False}

def save_schedule(data: dict):
    try:
        bin_id = _get_schedule_bin()
        if bin_id:
            _write_bin(bin_id, data)
    except Exception as e:
        logger.error(f"save_schedule error: {e}")

def to_utc_iso(dt: datetime) -> str:
    """Return ISO string with Z suffix so JavaScript parses it correctly as UTC."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

# ── ACTIVITY LOG ─────────────────────────────────────────────────────────────
def append_activity(level: str, message: str):
    """Append a log entry to JSONBin activity log."""
    try:
        bin_id = _get_logs_bin()
        if not bin_id:
            return
        data = _read_bin(bin_id) or {"logs": []}
        logs = data.get("logs", [])
        logs.append({
            "time":  to_utc_iso(datetime.utcnow()),
            "level": level,
            "msg":   message,
        })
        logs = logs[-MAX_LOG_ENTRIES:]
        _write_bin(bin_id, {"logs": logs})
    except Exception as e:
        logger.error(f"append_activity error: {e}")

def get_activity_log(limit: int = 100) -> list:
    try:
        bin_id = _get_logs_bin()
        if bin_id:
            data = _read_bin(bin_id) or {"logs": []}
            logs = data.get("logs", [])
            return logs[-limit:]
    except Exception as e:
        logger.error(f"get_activity_log error: {e}")
    return []

def clear_activity_log():
    try:
        bin_id = _get_logs_bin()
        if bin_id:
            _write_bin(bin_id, {"logs": []})
    except Exception as e:
        logger.error(f"clear_activity_log error: {e}")

def get_next_run_time(schedule: dict) -> datetime:
    """Returns next run time as UTC datetime."""
    mode = schedule.get("mode")
    if mode == "interval":
        value = int(schedule.get("intervalValue", 1))
        unit  = schedule.get("intervalUnit", "hour")
        delta = timedelta(minutes=value) if unit == "minute" else timedelta(hours=value)
        return datetime.utcnow() + delta
    if mode == "daily":
        time_str = schedule.get("dailyTime", "08:00")
        h, m = map(int, time_str.split(":"))
        next_run = datetime.utcnow().replace(hour=h, minute=m, second=0, microsecond=0)
        if next_run <= datetime.utcnow():
            next_run += timedelta(days=1)
        return next_run
    return None

# ── YOUTUBE ───────────────────────────────────────────────────────────────────
def fetch_videos_in_range(from_date: str, to_date: str) -> list:
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY not set")
    published_after  = f"{from_date}T00:00:00Z"
    published_before = f"{to_date}T23:59:59Z"
    videos = []
    next_page_token = None
    while True:
        params = {
            "part": "snippet",
            "channelId": TRENDLYNE_CHANNEL_ID,
            "type": "video",
            "order": "date",
            "publishedAfter": published_after,
            "publishedBefore": published_before,
            "maxResults": 50,
            "key": YOUTUBE_API_KEY,
        }
        if next_page_token:
            params["pageToken"] = next_page_token
        r = httpx.get("https://www.googleapis.com/youtube/v3/search", params=params, timeout=15)
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"YouTube API error: {data['error']['message']}")
        for item in data.get("items", []):
            snippet  = item.get("snippet", {})
            video_id = item.get("id", {}).get("videoId", "")
            title    = snippet.get("title", "")
            published = snippet.get("publishedAt", "")[:10]
            try:
                pub_display = datetime.strptime(published, "%Y-%m-%d").strftime("%d %b %Y")
            except ValueError:
                pub_display = published
            videos.append({
                "video_id": video_id,
                "title": title,
                "published_date": pub_display,
                "published_raw": published,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            })
        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break
    videos.sort(key=lambda x: x["published_raw"], reverse=True)
    for v in videos:
        v.pop("published_raw", None)
    logger.info(f"YouTube API returned {len(videos)} videos in range")
    return videos

# ── TRANSCRIPT (via Supadata) ─────────────────────────────────────────────────
async def fetch_transcript(video_id: str) -> str:
    keys = [
        os.getenv("SUPADATA_KEY_1", ""),
        os.getenv("SUPADATA_KEY_2", ""),
        os.getenv("SUPADATA_KEY_3", ""),
    ]
    async with httpx.AsyncClient(timeout=30) as client:
        for key in keys:
            if not key:
                continue
            try:
                r = await client.get(
                    f"https://api.supadata.ai/v1/youtube/transcript?videoId={video_id}&text=true",
                    headers={"x-api-key": key}
                )
                if r.status_code == 200:
                    data = r.json()
                    text = data.get("content") or data.get("transcript") or data.get("text") or ""
                    if len(text) > 100:
                        return text
            except Exception:
                continue
    return ""

# ── AI ANALYSIS ───────────────────────────────────────────────────────────────
ANALYSIS_PROMPT = """You are an expert equity research analyst. Analyze the earnings call transcript below and respond ONLY with a complete HTML block (no markdown, no backticks). Use this structure:

<div class="report">
<div class="section">
<div class="section-title">⚙️ PART 1 — CORE FUNDAMENTAL ASSESSMENT</div>
<div class="item green">🟢 1️⃣ Management Tone & Confidence: [analysis]</div>
<div class="item [green|red|grey]">🟢/🔴/⚪ 2️⃣ Business Performance: [Revenue, profit, margins YoY & QoQ]</div>
<div class="item [green|red|grey]">🟢/🔴/⚪ 3️⃣ Growth Drivers: [products, markets, partnerships]</div>
<div class="item [green|red|grey]">🟢/🔴/⚪ 4️⃣ Risks & Challenges: [threats, macro, regulatory]</div>
<div class="item [green|red|grey]">🟢/🔴/⚪ 5️⃣ Industry & Market Outlook: [sector trends]</div>
<div class="item [green|red|grey]">🟢/🔴/⚪ 6️⃣ Capital Allocation: [dividends, buybacks, debt]</div>
<div class="item [green|red|grey]">🟢/🔴/⚪ 7️⃣ Guidance & Forecast: [projections, credibility]</div>
<div class="item [green|red|grey]">🟢/🔴/⚪ 8️⃣ Sentiment Analysis: [linguistic tone signals]</div>
<div class="rating-box [strong-buy|buy|hold|avoid]">9️⃣ Rating: [STRONG BUY/BUY/HOLD/AVOID] — [rationale]</div>
<div class="verdict-box">🔟 Final Verdict: [2-3 sentences on long-term suitability]</div>
</div>
<div class="section">
<div class="section-title">⚡ PART 2 — CATALYST TABLE</div>
<table class="catalyst-table"><thead><tr><th>Catalyst</th><th>Signal</th><th>Evidence</th><th>Impact</th></tr></thead><tbody>
<tr class="[pos|neu|neg]"><td>Operating Leverage</td><td>[Positive/Neutral/Negative]</td><td>[evidence]</td><td>[impact]</td></tr>
<tr class="[pos|neu|neg]"><td>Sectoral Tailwinds</td><td>[signal]</td><td>[evidence]</td><td>[impact]</td></tr>
<tr class="[pos|neu|neg]"><td>Product Mix</td><td>[signal]</td><td>[evidence]</td><td>[impact]</td></tr>
<tr class="[pos|neu|neg]"><td>Capacity Expansion</td><td>[signal]</td><td>[evidence]</td><td>[impact]</td></tr>
<tr class="[pos|neu|neg]"><td>Debt Reduction</td><td>[signal]</td><td>[evidence]</td><td>[impact]</td></tr>
<tr class="[pos|neu|neg]"><td>Market Share</td><td>[signal]</td><td>[evidence]</td><td>[impact]</td></tr>
</tbody></table>
</div>
<div class="section conclusion">
<div class="section-title">🎯 PART 3 — CONCLUSION</div>
<div class="conclusion-item"><strong>Management Tone:</strong> [Bullish/Cautious/Defensive]</div>
<div class="conclusion-item"><strong>Key Triggers Next Quarter:</strong> [triggers]</div>
<div class="conclusion-item"><strong>Risks:</strong> [risks]</div>
<div class="verdict-final [strong-buy|buy|hold|avoid]"><strong>Verdict:</strong> [STRONG BUY / BUY OR ACCUMULATE / HOLD / WATCHLIST / AVOID]</div>
<div class="analyst-view"><strong>Analyst View:</strong> [5 sentences on conviction, growth potential, valuation. If Buy, state triggers to upgrade to Strong Buy.]</div>
</div>
</div>

Transcript:
---
{TRANSCRIPT}
---"""

# ── GEMINI AI ANALYSIS ───────────────────────────────────────────────────────
# Gemini 1.5 Flash — free tier: 1 million tokens/day, 15 RPM
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

async def analyze_with_gemini(prompt: str) -> str:
    """Call Gemini with retry on 429 rate limit."""
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": 8192,
                        "temperature": 0.3,
                    },
                },
            )
        if resp.status_code == 200:
            data = resp.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Gemini parse error: {e} — {str(data)[:200]}")
        elif resp.status_code == 429:
            wait = 10 * (attempt + 1)  # 10s, 20s, 30s
            logger.warning(f"Gemini 429 rate limit — waiting {wait}s (attempt {attempt+1}/3)")
            await asyncio.sleep(wait)
            continue
        else:
            raise RuntimeError(f"Gemini error {resp.status_code}: {resp.text[:200]}")
    raise RuntimeError("Gemini rate limited after 3 retries")

async def analyze_with_openrouter(prompt: str) -> str:
    """Fallback to OpenRouter if Gemini fails."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://earnings-intelligence-api.onrender.com",
            },
            json={
                "model": "openrouter/auto",
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
    if resp.status_code != 200:
        raise RuntimeError(f"OpenRouter error {resp.status_code}: {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"]

async def analyze_with_ai(prompt: str) -> str:
    """Try Gemini first, fall back to OpenRouter."""
    try:
        result = await analyze_with_gemini(prompt)
        logger.info("Analysis succeeded with Gemini")
        return result
    except Exception as e:
        logger.warning(f"Gemini failed: {e} — trying OpenRouter fallback")
        return await analyze_with_openrouter(prompt)

# ── EMAIL ─────────────────────────────────────────────────────────────────────
def build_email_html(item, index, total, from_date, to_date):
    title    = item.get("title", "Unknown")
    pub_date = item.get("published_date", "N/A")
    url      = item.get("url", "#")
    analysis = item.get("analysis", "No analysis available.")
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f4f4f8;color:#1a1a2e;margin:0;padding:0}}
.wrapper{{max-width:860px;margin:0 auto;background:#fff;box-shadow:0 2px 20px rgba(0,0,0,0.08)}}
.hdr{{background:linear-gradient(135deg,#0a0a0f 0%,#1a1a3e 100%);color:#e8ff47;padding:32px 40px}}
.hdr-badge{{display:inline-block;background:rgba(232,255,71,0.15);border:1px solid rgba(232,255,71,0.4);
  color:#e8ff47;font-size:10px;padding:4px 12px;border-radius:20px;font-family:monospace;
  letter-spacing:2px;margin-bottom:14px;text-transform:uppercase}}
.hdr h1{{font-size:24px;margin:0 0 8px;font-weight:700}}
.hdr p{{color:#aaa;font-size:12px;margin:0;font-family:monospace}}
.meta{{background:#f8f9ff;padding:12px 40px;font-size:12px;color:#666;border-bottom:2px solid #e8ff47}}
.meta a{{color:#4444ff;text-decoration:none;font-weight:600}}
.content{{padding:0 40px 32px}}
.report .section{{margin:24px 0;border-radius:8px;overflow:hidden;border:1px solid #e8e8f0}}
.section-title{{background:#1a1a3e;color:#e8ff47;padding:12px 20px;font-size:13px;font-weight:700}}
.item{{padding:10px 20px;font-size:13px;line-height:1.7;border-bottom:1px solid #f0f0f8}}
.item.green{{background:#f0fff4;border-left:4px solid #2ed573}}
.item.red{{background:#fff5f5;border-left:4px solid #ff4757}}
.item.grey{{background:#f8f8f8;border-left:4px solid #aaa}}
.rating-box{{padding:14px 20px;font-size:14px;font-weight:700;text-align:center}}
.rating-box.strong-buy{{background:#e8fff0;color:#00a651;border-left:4px solid #00a651}}
.rating-box.buy{{background:#f0fff4;color:#2ed573;border-left:4px solid #2ed573}}
.rating-box.hold{{background:#fffdf0;color:#f4a100;border-left:4px solid #f4a100}}
.rating-box.avoid{{background:#fff5f5;color:#ff4757;border-left:4px solid #ff4757}}
.verdict-box{{background:#f8f9ff;padding:14px 20px;font-size:13px;border-left:4px solid #4444ff;font-style:italic}}
.catalyst-table{{width:100%;border-collapse:collapse;font-size:12px}}
.catalyst-table th{{background:#1a1a3e;color:#e8ff47;padding:10px 14px;text-align:left;font-size:11px}}
.catalyst-table td{{padding:9px 14px;border-bottom:1px solid #f0f0f8;vertical-align:top}}
.catalyst-table tr.pos{{background:#f0fff4}}.catalyst-table tr.pos td:nth-child(2){{color:#00a651;font-weight:700}}
.catalyst-table tr.neg{{background:#fff5f5}}.catalyst-table tr.neg td:nth-child(2){{color:#ff4757;font-weight:700}}
.catalyst-table tr.neu{{background:#f8f8f8}}.catalyst-table tr.neu td:nth-child(2){{color:#888;font-weight:700}}
.conclusion{{background:#f8f9ff}}
.conclusion-item{{padding:10px 20px;font-size:13px;border-bottom:1px solid #eef;line-height:1.7}}
.verdict-final{{padding:16px 20px;font-size:15px;font-weight:700;text-align:center}}
.verdict-final.strong-buy{{background:#e8fff0;color:#00a651}}
.verdict-final.buy{{background:#f0fff4;color:#2ed573}}
.verdict-final.hold{{background:#fffdf0;color:#f4a100}}
.verdict-final.avoid{{background:#fff5f5;color:#ff4757}}
.analyst-view{{background:#fff;padding:16px 20px;font-size:13px;line-height:1.8;font-style:italic;color:#444;border-top:2px solid #e8ff47}}
.footer{{padding:20px 40px;text-align:center;font-size:11px;color:#aaa;background:#f4f4f8}}
</style></head><body><div class="wrapper">
<div class="hdr">
  <div class="hdr-badge">📊 Earnings Analysis {index} of {total}</div>
  <h1>{title}</h1>
  <p>AI-Powered Equity Research · Trendlyne · {from_date} to {to_date}</p>
</div>
<div class="meta">
  📅 Published: {pub_date} &nbsp;|&nbsp;
  ⏱ {datetime.utcnow().strftime("%d %b %Y %H:%M UTC")} &nbsp;|&nbsp;
  <a href="{url}">▶ Watch on YouTube →</a>
</div>
<div class="content">{analysis}</div>
<div class="footer">Auto-generated AI analysis · Not financial advice · Earnings Intelligence</div>
</div></body></html>"""

def send_single_email(to_email, item, index, total, from_date, to_date):
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY not configured")
    html    = build_email_html(item, index, total, from_date, to_date)
    subject = f"📊 [{index}/{total}] {item.get('title','Unknown')} — Earnings Analysis"
    r = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
        json={"from": "Earnings Intelligence <onboarding@resend.dev>",
              "to": [to_email], "subject": subject, "html": html},
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Resend error: {r.text}")
    logger.info(f"Email [{index}/{total}] sent: {item.get('title')}")

# ── SCHEDULED JOB ─────────────────────────────────────────────────────────────
async def run_scheduled_job(schedule: dict):
    email     = schedule.get("email", "")
    now       = datetime.utcnow()
    to_date   = now.strftime("%Y-%m-%d")
    from_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info(f"Scheduled job running for {email} — {from_date} to {to_date}")
    append_activity("info", f"⏰ Scheduled run started — {from_date} → {to_date}")

    try:
        all_videos = fetch_videos_in_range(from_date, to_date)
        # Filter only earnings call videos
        videos = [v for v in all_videos if "earnings call" in v.get("title","").lower()]
        if not videos:
            append_activity("err", f"⚠ No earnings call videos found in last 24h (skipped {len(all_videos)} non-earnings videos)")
            logger.info("No earnings call videos found in last 24h")
            return

        append_activity("ok", f"✓ Found {len(videos)} earnings call(s) (filtered from {len(all_videos)} total videos)")

        analyses = []
        for i, v in enumerate(videos, 1):
            append_activity("info", f"[{i}/{len(videos)}] Fetching transcript: {v['title']}")
            transcript = await fetch_transcript(v["video_id"])
            if not transcript:
                append_activity("err", f"⚠ No transcript: {v['title']}")
                logger.warning(f"No transcript: {v['title']}")
                continue
            append_activity("ai", f"✓ Got transcript ({round(len(transcript)/1000)}k chars) — running AI analysis...")
            prompt   = ANALYSIS_PROMPT.replace("{TRANSCRIPT}", transcript[:80000])
            analysis = await analyze_with_ai(prompt)
            analyses.append({**v, "analysis": analysis})
            append_activity("ok", f"✓ Analysis complete: {v['title']}")
            await asyncio.sleep(5)  # Gemini free tier: 15 RPM = 1 per 4s

        valid = [a for a in analyses if a.get("analysis")]
        append_activity("ai", f"Sending {len(valid)} email(s) to {email}...")
        for i, item in enumerate(valid, 1):
            send_single_email(email, item, i, len(valid), from_date, to_date)
            append_activity("ok", f"📧 Email [{i}/{len(valid)}] sent: {item.get('title','')[:50]}")
            await asyncio.sleep(0.6)

        append_activity("ok", f"✅ Pipeline complete — {len(valid)} emails sent to {email}")
        logger.info(f"Scheduled job complete — {len(valid)} emails sent to {email}")
    except Exception as e:
        append_activity("err", f"✗ Scheduled job error: {str(e)[:100]}")
        logger.error(f"Scheduled job error: {e}")

# ── BACKGROUND SCHEDULER LOOP ─────────────────────────────────────────────────
async def scheduler_loop():
    logger.info("Scheduler loop started")
    while True:
        await asyncio.sleep(30)  # check every 30 seconds
        try:
            schedule = load_schedule()
            if not schedule.get("active"):
                continue

            next_run_str = schedule.get("next_run")
            if not next_run_str:
                continue

            next_run = datetime.fromisoformat(next_run_str.replace("Z",""))
            if datetime.utcnow() >= next_run:
                logger.info("Triggering scheduled analysis run...")
                await run_scheduled_job(schedule)

                # Calculate and save next run time
                next_run = get_next_run_time(schedule)
                schedule["next_run"]  = to_utc_iso(next_run)
                schedule["run_count"] = schedule.get("run_count", 0) + 1
                schedule["last_run"]  = to_utc_iso(datetime.utcnow())
                save_schedule(schedule)
                logger.info(f"Next run scheduled for {next_run}")
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(scheduler_loop())
    yield

# ── APP ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Earnings Intelligence API", version="6.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"service": "Earnings Intelligence API", "status": "ok", "version": "6.0.0"}

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.post("/api/fetch-videos")
async def fetch_videos(request: Request):
    body = await request.json()
    from_date = body.get("from_date", "")
    to_date   = body.get("to_date", "")
    if not from_date or not to_date:
        raise HTTPException(400, "from_date and to_date required")
    try:
        videos = fetch_videos_in_range(from_date, to_date)
        return {"success": True, "count": len(videos), "videos": videos}
    except Exception as e:
        logger.error(f"fetch-videos error: {e}")
        raise HTTPException(500, str(e))

@app.post("/api/analyze")
async def analyze(request: Request):
    body   = await request.json()
    prompt = body.get("prompt", "")
    if not prompt:
        raise HTTPException(400, "prompt is required")
    try:
        analysis = await analyze_with_ai(prompt)
        await asyncio.sleep(4)  # Gemini free tier: 15 RPM
        return {"success": True, "analysis": analysis}
    except Exception as e:
        logger.error(f"analyze error: {e}")
        raise HTTPException(500, str(e))

@app.post("/api/send-report")
async def send_report(request: Request):
    body      = await request.json()
    email     = body.get("email", "")
    analyses  = body.get("analyses", [])
    from_date = body.get("from_date", "")
    to_date   = body.get("to_date", "")
    if not email or not analyses:
        raise HTTPException(400, "email and analyses required")
    valid = [a for a in analyses if a.get("analysis") and "No transcript" not in a.get("analysis","")]
    if not valid:
        return {"success": False, "message": "No valid analyses to send"}
    sent, errors = 0, []
    for i, item in enumerate(valid, 1):
        try:
            send_single_email(email, item, i, len(valid), from_date, to_date)
            sent += 1
            await asyncio.sleep(0.6)
        except Exception as e:
            logger.error(f"Email error: {e}")
            errors.append(str(e))
    return {"success": sent > 0, "sent": sent, "total": len(valid), "errors": errors,
            "message": f"Sent {sent}/{len(valid)} emails to {email}"}

# ── SCHEDULE ROUTES ───────────────────────────────────────────────────────────
@app.get("/api/schedule")
def get_schedule():
    return load_schedule()

@app.post("/api/schedule")
async def set_schedule(request: Request):
    body = await request.json()
    mode  = body.get("mode")
    email = body.get("email", "")
    if mode not in ("interval", "daily"):
        raise HTTPException(400, "mode must be interval or daily")
    if not email:
        raise HTTPException(400, "email required")

    schedule = {
        "active":        True,
        "mode":          mode,
        "email":         email,
        "intervalValue": body.get("intervalValue", 1),
        "intervalUnit":  body.get("intervalUnit", "hour"),
        "dailyTime":     body.get("dailyTime", "08:00"),
        "run_count":     0,
        "created_at":    to_utc_iso(datetime.utcnow()),
        "last_run":      None,
    }
    next_run = get_next_run_time(schedule)
    schedule["next_run"] = to_utc_iso(next_run)
    save_schedule(schedule)
    logger.info(f"Schedule set: {mode} for {email}, next run {next_run}")
    return {"success": True, "schedule": schedule}

@app.delete("/api/schedule")
def delete_schedule():
    save_schedule({"active": False})
    return {"success": True, "message": "Schedule cancelled"}

@app.get("/api/logs")
def get_logs(limit: int = 100):
    """Return recent activity log entries for any browser to poll."""
    return {"logs": get_activity_log(limit)}

@app.delete("/api/logs")
def clear_logs():
    clear_activity_log()
    return {"success": True, "message": "Logs cleared"}

@app.get("/debug/videos")
def debug_videos():
    try:
        videos = fetch_videos_in_range("2026-02-01", "2026-02-14")
        return {"status": "ok", "count": len(videos), "videos": videos[:5]}
    except Exception as e:
        return {"status": "error", "message": str(e)}
