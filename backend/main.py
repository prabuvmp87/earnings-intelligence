"""
Earnings Intelligence — Backend API v4
Uses YouTube Data API v3 (free, no bot issues) to fetch videos.
"""

import os
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── CONFIG ───────────────────────────────────────────────────────────────────
SMTP_HOST       = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER       = os.getenv("SMTP_USER", "")
SMTP_PASS       = os.getenv("SMTP_PASS", "")
FROM_EMAIL      = os.getenv("FROM_EMAIL", SMTP_USER)
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# @trendlyne channel ID
TRENDLYNE_CHANNEL_ID = "UCznm57tnYpUpc2q2FmO3R3Q"

app = FastAPI(title="Earnings Intelligence API", version="4.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── YOUTUBE DATA API ─────────────────────────────────────────────────────────

def get_channel_id(api_key: str) -> str:
    """Resolve @trendlyne handle to a channel ID."""
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": "trendlyne",
        "type": "channel",
        "key": api_key,
        "maxResults": 5,
    }
    r = httpx.get(url, params=params, timeout=15)
    data = r.json()
    for item in data.get("items", []):
        if "trendlyne" in item["snippet"].get("channelTitle", "").lower():
            return item["snippet"]["channelId"]
    # fallback — return known ID
    return TRENDLYNE_CHANNEL_ID


def fetch_videos_in_range(from_date: str, to_date: str) -> list:
    """
    Fetch all videos from @trendlyne channel between from_date and to_date.
    Uses YouTube Data API v3 search endpoint.
    from_date / to_date: YYYY-MM-DD strings
    """
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY environment variable not set")

    # Convert dates to RFC 3339 format required by YouTube API
    published_after  = f"{from_date}T00:00:00Z"
    published_before = f"{to_date}T23:59:59Z"

    url = "https://www.googleapis.com/youtube/v3/search"
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

        r = httpx.get(url, params=params, timeout=15)
        data = r.json()

        if "error" in data:
            raise RuntimeError(f"YouTube API error: {data['error']['message']}")

        for item in data.get("items", []):
            snippet   = item.get("snippet", {})
            video_id  = item.get("id", {}).get("videoId", "")
            title     = snippet.get("title", "")
            published = snippet.get("publishedAt", "")[:10]  # YYYY-MM-DD

            try:
                pub_date = datetime.strptime(published, "%Y-%m-%d")
                pub_display = pub_date.strftime("%d %b %Y")
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

    # Sort newest first
    videos.sort(key=lambda x: x["published_raw"], reverse=True)

    # Clean up internal field
    for v in videos:
        v.pop("published_raw", None)

    logger.info(f"YouTube API returned {len(videos)} videos in range")
    return videos


def get_transcript(video_id: str) -> str:
    """Fetch transcript using youtube-transcript-api."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        raise RuntimeError("youtube-transcript-api not installed")

    try:
        tlist = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            t = tlist.find_transcript(["en", "en-IN"]).fetch()
        except Exception:
            t = tlist.find_generated_transcript(["en", "en-IN"]).fetch()
        text = " ".join(seg["text"].strip() for seg in t if seg.get("text"))
        logger.info(f"Transcript fetched for {video_id}: {len(text)} chars")
        return text
    except Exception as e:
        logger.warning(f"No transcript for {video_id}: {e}")
        return ""


# ── EMAIL ─────────────────────────────────────────────────────────────────────
def send_email_report(to_email, analyses, from_date, to_date):
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("SMTP_USER / SMTP_PASS not configured")

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
body{{font-family:Georgia,serif;background:#f8f8f8;color:#1a1a1a;margin:0;padding:0}}
.wrapper{{max-width:820px;margin:0 auto;background:#fff}}
.hdr{{background:#0a0a0f;color:#e8ff47;padding:40px;text-align:center}}
.hdr h1{{font-size:26px;margin:0 0 8px}}
.hdr p{{color:#888;font-size:12px;margin:0;font-family:monospace}}
.bar{{background:#f0f0f0;padding:14px 40px;font-size:12px;color:#555;font-family:monospace;border-bottom:1px solid #ddd}}
.sec{{padding:36px 40px;border-bottom:2px solid #e8e8e8}}
.vtitle{{font-size:20px;font-weight:bold;color:#0a0a0f;margin-bottom:6px}}
.vmeta{{font-size:12px;color:#888;font-family:monospace;margin-bottom:22px}}
.vmeta a{{color:#0066cc}}
.body{{font-size:14px;line-height:1.9;white-space:pre-wrap;color:#333}}
.footer{{padding:24px 40px;text-align:center;font-size:11px;color:#aaa;font-family:monospace}}
</style></head><body><div class="wrapper">
<div class="hdr"><h1>📊 Earnings Intelligence Report</h1>
<p>AI-Powered Equity Analysis · Trendlyne YouTube Earnings Calls</p></div>
<div class="bar">Period: {from_date} → {to_date} &nbsp;|&nbsp; Calls: {len(analyses)} &nbsp;|&nbsp; Generated: {datetime.now().strftime("%d %b %Y %H:%M UTC")}</div>"""

    for i, item in enumerate(analyses, 1):
        html += f"""
<div class="sec">
<div class="vtitle">{i}. {item.get('title','Unknown')}</div>
<div class="vmeta">Published: {item.get('published_date','N/A')} &nbsp;|&nbsp;
<a href="{item.get('url','#')}">Watch on YouTube ↗</a></div>
<div class="body">{item.get('analysis','No analysis available.')}</div>
</div>"""

    html += """<div class="footer">Auto-generated AI analysis of public earnings call transcripts.<br>
Not financial advice. Conduct your own due diligence.<br><br>Earnings Intelligence · Open Source
</div></div></body></html>"""

    plain = f"EARNINGS INTELLIGENCE REPORT\n{'='*50}\nPeriod: {from_date} to {to_date}\n\n"
    for i, item in enumerate(analyses, 1):
        plain += f"\n{'='*50}\n{i}. {item.get('title')}\n{item.get('url')}\n\n{item.get('analysis','N/A')}\n"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 Earnings Report — {len(analyses)} Calls ({from_date} to {to_date})"
    msg["From"]    = FROM_EMAIL
    msg["To"]      = to_email
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo()
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(FROM_EMAIL, to_email, msg.as_string())
    logger.info(f"Email sent to {to_email}")


# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"service": "Earnings Intelligence API", "status": "ok", "version": "4.0.0"}


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/api/fetch-videos")
async def fetch_videos(request: Request):
    body         = await request.json()
    from_date    = body.get("from_date", "")
    to_date      = body.get("to_date", "")

    if not from_date or not to_date:
        raise HTTPException(400, "from_date and to_date required")

    try:
        videos = fetch_videos_in_range(from_date, to_date)
        return {"success": True, "count": len(videos), "videos": videos}
    except Exception as e:
        logger.error(f"fetch-videos error: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/get-transcript/{video_id}")
async def get_video_transcript(video_id: str):
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"https://www.youtube.com/watch?v={video_id}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"},
            )
        # Use youtube-transcript-api with a fresh session
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api.formatters import TextFormatter
        transcript_list = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=["en", "en-IN", "hi"],
            proxies=None
        )
        text = " ".join(seg["text"].strip() for seg in transcript_list if seg.get("text"))
        return {"success": True, "video_id": video_id, "transcript": text, "length": len(text)}
    except Exception as e:
        logger.error(f"transcript error for {video_id}: {e}")
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

    try:
        send_email_report(email, analyses, from_date, to_date)
        return {"success": True, "message": f"Report sent to {email}"}
    except Exception as e:
        logger.error(f"send-report error: {e}")
        raise HTTPException(500, str(e))


@app.get("/debug/videos")
def debug_videos():
    """Test endpoint — returns latest 5 videos from channel."""
    try:
        videos = fetch_videos_in_range("2026-02-01", "2026-02-13")
        return {"status": "ok", "count": len(videos), "videos": videos[:5]}
    except Exception as e:
        return {"status": "error", "message": str(e)}
