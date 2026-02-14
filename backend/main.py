"""
Earnings Intelligence — Backend API v5
- YouTube Data API v3 for video listing
- OpenRouter (free models) for AI analysis
- Resend API for email (one email per analysis)
"""

import os
import logging
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────
YOUTUBE_API_KEY    = os.getenv("YOUTUBE_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
RESEND_API_KEY     = os.getenv("RESEND_API_KEY", "")
TRENDLYNE_CHANNEL_ID = "UCznm57tnYpUpc2q2FmO3R3Q"

app = FastAPI(title="Earnings Intelligence API", version="5.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
                "duration": "N/A",
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


# ── AI ANALYSIS ───────────────────────────────────────────────────────────────
async def analyze_with_openrouter(prompt: str) -> str:
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


# ── EMAIL (one per analysis via Resend) ───────────────────────────────────────
def build_email_html(item: dict, index: int, total: int, from_date: str, to_date: str) -> str:
    title    = item.get("title", "Unknown")
    pub_date = item.get("published_date", "N/A")
    url      = item.get("url", "#")
    analysis = item.get("analysis", "No analysis available.")

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f4f4f8;color:#1a1a2e;margin:0;padding:0}}
.wrapper{{max-width:860px;margin:0 auto;background:#fff;box-shadow:0 2px 20px rgba(0,0,0,0.08)}}
.hdr{{background:linear-gradient(135deg,#0a0a0f 0%,#1a1a3e 100%);color:#e8ff47;padding:32px 40px}}
.hdr-badge{{display:inline-block;background:rgba(232,255,71,0.15);border:1px solid rgba(232,255,71,0.4);
  color:#e8ff47;font-size:10px;padding:4px 12px;border-radius:20px;font-family:monospace;
  letter-spacing:2px;margin-bottom:14px;text-transform:uppercase}}
.hdr h1{{font-size:24px;margin:0 0 8px;font-weight:700;line-height:1.3}}
.hdr p{{color:#aaa;font-size:12px;margin:0;font-family:monospace}}
.meta{{background:#f8f9ff;padding:12px 40px;font-size:12px;color:#666;
  border-bottom:2px solid #e8ff47;display:flex;gap:20px;flex-wrap:wrap}}
.meta a{{color:#4444ff;text-decoration:none;font-weight:600}}
.content{{padding:0 40px 32px}}
/* Report sections */
.report .section{{margin:24px 0;border-radius:8px;overflow:hidden;
  border:1px solid #e8e8f0}}
.section-title{{background:#1a1a3e;color:#e8ff47;padding:12px 20px;
  font-size:13px;font-weight:700;letter-spacing:0.5px}}
/* Color coded items */
.item{{padding:10px 20px;font-size:13px;line-height:1.7;border-bottom:1px solid #f0f0f8}}
.item.green{{background:#f0fff4;border-left:4px solid #2ed573}}
.item.red{{background:#fff5f5;border-left:4px solid #ff4757}}
.item.grey{{background:#f8f8f8;border-left:4px solid #aaa}}
/* Rating box */
.rating-box{{padding:14px 20px;font-size:14px;font-weight:700;text-align:center;letter-spacing:1px}}
.rating-box.strong-buy{{background:#e8fff0;color:#00a651;border-left:4px solid #00a651}}
.rating-box.buy{{background:#f0fff4;color:#2ed573;border-left:4px solid #2ed573}}
.rating-box.hold{{background:#fffdf0;color:#f4a100;border-left:4px solid #f4a100}}
.rating-box.avoid{{background:#fff5f5;color:#ff4757;border-left:4px solid #ff4757}}
/* Verdict */
.verdict-box{{background:#f8f9ff;padding:14px 20px;font-size:13px;
  border-left:4px solid #4444ff;font-style:italic}}
/* Strategic check grid */
.check-grid{{display:grid;grid-template-columns:1fr 1fr;gap:0}}
.check{{padding:10px 20px;font-size:12px;border-bottom:1px solid #f0f0f8;border-right:1px solid #f0f0f8}}
.check.yes{{background:#f0fff4;border-left:3px solid #2ed573}}
.check.no{{background:#fff5f5;border-left:3px solid #ff4757}}
.check.partial{{background:#fffdf0;border-left:3px solid #f4a100}}
/* Tables */
.catalyst-table,.summary-table{{width:100%;border-collapse:collapse;font-size:12px}}
.catalyst-table th,.summary-table th{{background:#1a1a3e;color:#e8ff47;padding:10px 14px;text-align:left;font-size:11px;letter-spacing:1px}}
.catalyst-table td,.summary-table td{{padding:9px 14px;border-bottom:1px solid #f0f0f8;vertical-align:top;line-height:1.5}}
.catalyst-table tr.pos{{background:#f0fff4}}
.catalyst-table tr.pos td:nth-child(2){{color:#00a651;font-weight:700}}
.catalyst-table tr.neg{{background:#fff5f5}}
.catalyst-table tr.neg td:nth-child(2){{color:#ff4757;font-weight:700}}
.catalyst-table tr.neu{{background:#f8f8f8}}
.catalyst-table tr.neu td:nth-child(2){{color:#888;font-weight:700}}
.summary-table tr:nth-child(even){{background:#f8f9ff}}
/* Positives/Negatives/Neutrals */
.positives{{background:#f0fff4;border-left:4px solid #2ed573;padding:12px 20px;margin:8px 0;font-size:13px;line-height:1.7}}
.negatives{{background:#fff5f5;border-left:4px solid #ff4757;padding:12px 20px;margin:8px 0;font-size:13px;line-height:1.7}}
.neutrals{{background:#f8f8f8;border-left:4px solid #aaa;padding:12px 20px;margin:8px 0;font-size:13px;line-height:1.7}}
/* Conclusion */
.conclusion{{background:#f8f9ff}}
.conclusion-item{{padding:10px 20px;font-size:13px;border-bottom:1px solid #eef;line-height:1.7}}
.verdict-final{{padding:16px 20px;font-size:15px;font-weight:700;text-align:center;letter-spacing:1px;margin:4px 0}}
.verdict-final.strong-buy{{background:#e8fff0;color:#00a651}}
.verdict-final.buy{{background:#f0fff4;color:#2ed573}}
.verdict-final.hold{{background:#fffdf0;color:#f4a100}}
.verdict-final.avoid{{background:#fff5f5;color:#ff4757}}
.analyst-view{{background:#fff;padding:16px 20px;font-size:13px;line-height:1.8;
  font-style:italic;color:#444;border-top:2px solid #e8ff47}}
.footer{{padding:20px 40px;text-align:center;font-size:11px;color:#aaa;
  background:#f4f4f8;border-top:1px solid #e8e8f0}}
</style></head>
<body><div class="wrapper">
<div class="hdr">
  <div class="hdr-badge">📊 Earnings Analysis {index} of {total}</div>
  <h1>{title}</h1>
  <p>AI-Powered Equity Research · Trendlyne · Period: {from_date} to {to_date}</p>
</div>
<div class="meta">
  <span>📅 Published: {pub_date}</span>
  <span>⏱ Generated: {datetime.now().strftime("%d %b %Y %H:%M UTC")}</span>
  <span><a href="{url}">▶ Watch on YouTube →</a></span>
</div>
<div class="content">
{analysis}
</div>
<div class="footer">
  Auto-generated AI analysis of public earnings call transcripts.<br>
  Not financial advice. Conduct your own due diligence.<br><br>
  Earnings Intelligence · Open Source
</div>
</div></body></html>"""


def send_single_email(to_email: str, item: dict, index: int, total: int, from_date: str, to_date: str):
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY not configured")

    title   = item.get("title", "Unknown")
    html    = build_email_html(item, index, total, from_date, to_date)
    subject = f"📊 [{index}/{total}] {title} — Earnings Analysis"

    response = httpx.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": "Earnings Intelligence <onboarding@resend.dev>",
            "to": [to_email],
            "subject": subject,
            "html": html,
        },
        timeout=30,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Resend error: {response.text}")
    logger.info(f"Email [{index}/{total}] sent to {to_email}: {title}")


# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"service": "Earnings Intelligence API", "status": "ok", "version": "5.0.0"}


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/api/fetch-videos")
async def fetch_videos(request: Request):
    body      = await request.json()
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
        analysis = await analyze_with_openrouter(prompt)
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

    # Filter only successfully analyzed items
    valid = [a for a in analyses if a.get("analysis") and "No transcript" not in a.get("analysis", "")]
    total = len(valid)

    if total == 0:
        return {"success": False, "message": "No valid analyses to send"}

    import asyncio
    sent = 0
    errors = []
    for i, item in enumerate(valid, 1):
        try:
            send_single_email(email, item, i, total, from_date, to_date)
            sent += 1
            await asyncio.sleep(0.6)  # max ~1.6 emails/sec, safely under limit
        except Exception as e:
            logger.error(f"Email error for {item.get('title')}: {e}")
            errors.append(str(e))

    return {
        "success": sent > 0,
        "sent": sent,
        "total": total,
        "errors": errors,
        "message": f"Sent {sent}/{total} emails to {email}"
    }


@app.get("/debug/videos")
def debug_videos():
    try:
        videos = fetch_videos_in_range("2026-02-01", "2026-02-14")
        return {"status": "ok", "count": len(videos), "videos": videos[:5]}
    except Exception as e:
        return {"status": "error", "message": str(e)}
