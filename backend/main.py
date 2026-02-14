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
body{{font-family:Georgia,serif;background:#f8f8f8;color:#1a1a1a;margin:0;padding:0}}
.wrapper{{max-width:820px;margin:0 auto;background:#fff}}
.hdr{{background:#0a0a0f;color:#e8ff47;padding:32px 40px}}
.hdr h1{{font-size:22px;margin:0 0 6px;font-family:monospace}}
.hdr p{{color:#888;font-size:11px;margin:0;font-family:monospace}}
.badge{{display:inline-block;background:rgba(232,255,71,0.15);border:1px solid rgba(232,255,71,0.3);
  color:#e8ff47;font-size:10px;padding:3px 10px;border-radius:4px;
  font-family:monospace;letter-spacing:1px;margin-bottom:12px}}
.meta{{background:#f0f0f0;padding:12px 40px;font-size:12px;color:#555;
  font-family:monospace;border-bottom:1px solid #ddd}}
.meta a{{color:#0066cc}}
.body{{padding:32px 40px;font-size:14px;line-height:1.9;white-space:pre-wrap;color:#333}}
.footer{{padding:20px 40px;text-align:center;font-size:11px;color:#aaa;
  font-family:monospace;border-top:1px solid #eee}}
</style></head>
<body><div class="wrapper">
<div class="hdr">
  <div class="badge">📊 EARNINGS ANALYSIS {index} of {total}</div>
  <h1>{title}</h1>
  <p>AI-Powered Equity Analysis · Trendlyne · {from_date} to {to_date}</p>
</div>
<div class="meta">
  Published: {pub_date} &nbsp;|&nbsp;
  <a href="{url}">▶ Watch on YouTube</a> &nbsp;|&nbsp;
  Generated: {datetime.now().strftime("%d %b %Y %H:%M UTC")}
</div>
<div class="body">{analysis}</div>
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
