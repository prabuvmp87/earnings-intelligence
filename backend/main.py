"""
Earnings Intelligence — Backend API (No Anthropic API Key Required!)
FastAPI app that:
  1. Fetches @trendlyne YouTube earnings videos in a date range
  2. Returns raw transcripts to the frontend
  3. Frontend calls Claude via the FREE built-in artifact API (no key needed)
  4. Frontend sends completed analyses back here to email

Deploy FREE on: Render.com, Railway.app, or Fly.io
"""

import os
import logging
import smtplib
from datetime import datetime, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    YT_TRANSCRIPT_AVAILABLE = True
except ImportError:
    YT_TRANSCRIPT_AVAILABLE = False

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(levelname)s — %(message)s")
logger = logging.getLogger(__name__)

# ─── CONFIGURATION ──────────────────────────────────────────────────────────
# NOTE: No ANTHROPIC_API_KEY needed! AI runs free via the frontend artifact API.
SMTP_HOST  = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT  = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER  = os.getenv("SMTP_USER", "")
SMTP_PASS  = os.getenv("SMTP_PASS", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

TRENDLYNE_CHANNEL_URL = "https://www.youtube.com/@trendlyne"

# ─── APP ─────────────────────────────────────────────────────────────────────
app = FastAPI(title="Earnings Intelligence API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ─── MODELS ──────────────────────────────────────────────────────────────────
class FetchRequest(BaseModel):
    from_date: str
    to_date: str

class SendReportRequest(BaseModel):
    email: str
    analyses: list
    from_date: str
    to_date: str

# ─── UTILS ───────────────────────────────────────────────────────────────────
def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()

def seconds_to_hms(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}h {m}m" if h else f"{m}m {s}s"

# ─── YOUTUBE ─────────────────────────────────────────────────────────────────
def fetch_channel_videos(from_date, to_date):
    if not YTDLP_AVAILABLE:
        raise RuntimeError("yt-dlp not installed")

    ydl_opts = {"extract_flat": "in_playlist", "quiet": True,
                "no_warnings": True, "playlistend": 200}
    videos = []

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"{TRENDLYNE_CHANNEL_URL}/videos", download=False)
        for entry in (info.get("entries") or []):
            if not entry:
                continue
            raw = entry.get("upload_date")
            if not raw:
                continue
            try:
                upload_date = datetime.strptime(raw, "%Y%m%d").date()
            except ValueError:
                continue
            if not (from_date <= upload_date <= to_date):
                continue
            title = entry.get("title", "")
            keywords = ["earnings", "q1", "q2", "q3", "q4", "quarterly",
                        "results", "concall", "analyst", "investor"]
            if not any(k in title.lower() for k in keywords):
                continue
            videos.append({
                "video_id": entry.get("id"),
                "title": title,
                "published_date": upload_date.strftime("%d %b %Y"),
                "duration": seconds_to_hms(entry.get("duration") or 0),
                "url": f"https://www.youtube.com/watch?v={entry.get('id')}"
            })

    return videos


def get_transcript(video_id):
    if not YT_TRANSCRIPT_AVAILABLE:
        raise RuntimeError("youtube-transcript-api not installed")
    try:
        tlist = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            t = tlist.find_transcript(["en", "en-IN"]).fetch()
        except Exception:
            t = tlist.find_generated_transcript(["en", "en-IN"]).fetch()
        return " ".join(seg["text"].strip() for seg in t if seg.get("text"))
    except Exception as e:
        logger.warning(f"No transcript for {video_id}: {e}")
        return ""


# ─── EMAIL ────────────────────────────────────────────────────────────────────
def send_email_report(to_email, analyses, from_date, to_date):
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("SMTP_USER / SMTP_PASS not configured")

    html_parts = [f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
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
<div class="bar">Period: {from_date} → {to_date} &nbsp;|&nbsp; Calls: {len(analyses)} &nbsp;|&nbsp; Generated: {datetime.now().strftime("%d %b %Y %H:%M UTC")}</div>"""]

    for i, item in enumerate(analyses, 1):
        html_parts.append(f"""
<div class="sec">
  <div class="vtitle">{i}. {item.get('title','Unknown')}</div>
  <div class="vmeta">Published: {item.get('published_date','N/A')} &nbsp;|&nbsp;
    Duration: {item.get('duration','N/A')} &nbsp;|&nbsp;
    <a href="{item.get('url','#')}">Watch on YouTube ↗</a></div>
  <div class="body">{item.get('analysis','No analysis available.')}</div>
</div>""")

    html_parts.append("""<div class="footer">
  This report was auto-generated using AI analysis of public earnings call transcripts.<br>
  Not financial advice. Conduct your own due diligence.<br><br>
  Earnings Intelligence · Open Source
</div></div></body></html>""")

    plain = f"EARNINGS INTELLIGENCE REPORT\n{'='*50}\nPeriod: {from_date} to {to_date}\nCalls: {len(analyses)}\n\n"
    for i, item in enumerate(analyses, 1):
        plain += f"\n{'='*50}\n{i}. {item.get('title')}\n{item.get('published_date')} | {item.get('url')}\n\n{item.get('analysis','N/A')}\n"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 Earnings Report — {len(analyses)} Calls ({from_date} to {to_date})"
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText("".join(html_parts), "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo(); s.starttls(); s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(FROM_EMAIL, to_email, msg.as_string())
    logger.info(f"Email sent to {to_email}")


# ─── ROUTES ──────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"service": "Earnings Intelligence API v2", "status": "ok",
            "note": "AI analysis runs FREE via frontend — no Anthropic key needed on backend"}

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/api/fetch-videos")
def fetch_videos(req: FetchRequest):
    """Returns list of earnings call videos with metadata (no transcript yet)."""
    try:
        from_dt = parse_date(req.from_date)
        to_dt   = parse_date(req.to_date)
    except ValueError as e:
        raise HTTPException(400, f"Invalid date: {e}")
    if from_dt > to_dt:
        raise HTTPException(400, "from_date must be before to_date")
    try:
        videos = fetch_channel_videos(from_dt, to_dt)
        return {"success": True, "count": len(videos), "videos": videos}
    except Exception as e:
        logger.error(e)
        raise HTTPException(500, str(e))


@app.post("/api/get-transcript/{video_id}")
def get_video_transcript(video_id: str):
    """Returns raw transcript text for a single video."""
    try:
        transcript = get_transcript(video_id)
        return {"success": True, "video_id": video_id,
                "transcript": transcript, "length": len(transcript)}
    except Exception as e:
        logger.error(e)
        raise HTTPException(500, str(e))


@app.post("/api/send-report")
def send_report(req: SendReportRequest):
    """Emails the compiled analyses to the user."""
    if not req.analyses:
        raise HTTPException(400, "No analyses provided")
    try:
        send_email_report(req.email, req.analyses, req.from_date, req.to_date)
        return {"success": True, "message": f"Report sent to {req.email}"}
    except Exception as e:
        logger.error(e)
        raise HTTPException(500, str(e))
