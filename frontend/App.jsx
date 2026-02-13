import { useState, useRef, useEffect } from "react";

// ── CONFIG ──────────────────────────────────────────────────────────────────
// Update this to your deployed Render/Railway backend URL
const API_BASE =
  typeof window !== "undefined" &&
  (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
    ? "http://localhost:8000"
    : "https://YOUR-BACKEND.onrender.com"; // ← update after deployment

const ANALYSIS_PROMPT = `You are an expert equity research analyst with deep expertise in fundamental analysis, behavioral finance, industry dynamics, and technical interpretation.
I will provide the quarterly earnings call transcript of a publicly traded company.
Your job is to perform a comprehensive qualitative and quantitative analysis and determine if the stock is a good long-term hold.

⚙️ ANALYSIS FRAMEWORK

PART 1 — CORE FUNDAMENTAL ASSESSMENT
Present findings using 🟢 Green (Positive), 🔴 Red (Negative), and ⚪ Grey (Neutral) indicators.
Evaluate the transcript based on:
1️⃣ Management Tone & Confidence
2️⃣ Business Performance – revenue, profit, margins, EPS, cash flow, debt (YoY & QoQ)
3️⃣ Growth Drivers – products, markets, partnerships, R&D, acquisitions
4️⃣ Risks & Challenges – competitive threats, macro, cost pressures, regulatory
5️⃣ Industry & Market Outlook – peers, demand, sector trends
6️⃣ Capital Allocation & Shareholder Returns – dividends, buybacks, debt, reinvestment
7️⃣ Guidance & Forecast – credibility, visibility, realism
8️⃣ Sentiment Analysis – linguistic confidence/caution
9️⃣ Investment Rating – Strong Buy / Buy / Cautious / Sell
🔟 Final Verdict – suitable for long-term holding?

PART 2 — STRATEGIC QUALITY CHECK
• Is multi-year ROE/ROCE rising and consistent?
• Is management integrity unquestionable?
• Is it a market leader with strong competitive moats?
• Is cash flow conversion high (OCF/PAT > 1)?
• DuPont ROE analysis insights?
• Are sector/macro trends favorable?
• Visible scalability and long-term compounding potential?
• Category winner or turnaround candidate?
• Sound capital allocation and shareholder alignment?
• Are earnings, revenue, EPS consistently growing?
• Are margins stable or expanding, debt manageable?
• Board aligned with minority shareholders?
• Resilient during downturns (e.g., COVID)?
• Persistent sector tailwinds?
• Strong unit economics with pricing power?
• Recent strategic shifts, leadership changes, product launches?
• Adaptive to disruption and policy changes?

PART 3 — CATALYST TABLE

| Catalyst | Positive/Neutral/Negative | Key Evidence | Potential Stock Impact |
|---|---|---|---|
| 1️⃣ Operating Leverage & Margin Expansion | | | |
| 2️⃣ Sectoral Tailwinds | | | |
| 3️⃣ Product Mix Improvements | | | |
| 4️⃣ Capacity Expansion Plans | | | |
| 5️⃣ Insider Buying / Promoter Confidence | | | |
| 6️⃣ Geographical Expansion | | | |
| 7️⃣ Supply-Side Consolidation | | | |
| 8️⃣ Debt Reduction / ROE-ROCE Improvement | | | |
| 9️⃣ Operational Efficiency / Tech Adoption | | | |
| 🔟 Market Share Gains | | | |
| 11️⃣ Corporate Actions (M&A, Buyback, Spinoff) | | | |
| 12️⃣ Creating Optionality (Governance, ESG, Leadership) | | | |

PART 4 — STRUCTURED SUMMARY

| Category | Assessment | Evidence |
|---|---|---|
| Management Tone | | |
| Financial Trends | | |
| Growth Drivers | | |
| Risks | | |
| Industry Position | | |
| Capital Allocation | | |
| Guidance | | |
| Sentiment | | |
| Rating | | |

🟢 Positives:
🔴 Negatives:
⚪ Neutrals:

PART 5 — CONCLUSION
• Overall Management Tone: Bullish / Cautious / Defensive
• Key Triggers for Next Quarter:
• Risks Mentioned or Implied:
• Verdict: Strong Buy / Buy or Accumulate / Hold / Watchlist / Avoid
• Analyst View (5 sentences): conviction level, growth potential, valuation comfort zone.
  If Buy, mention triggers that would upgrade to Strong Buy.

Transcript:
---
{TRANSCRIPT}
---`;

// ── FREE CLAUDE API CALL ─────────────────────────────────────────────────────
async function analyzeWithClaude(transcript, title) {
  const prompt = ANALYSIS_PROMPT.replace("{TRANSCRIPT}", transcript.slice(0, 80000));
  const response = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "claude-sonnet-4-20250514",
      max_tokens: 1000,
      messages: [{ role: "user", content: prompt }],
    }),
  });
  if (!response.ok) throw new Error(`Claude API error: ${response.status}`);
  const data = await response.json();
  return data.content.map((b) => b.text || "").join("\n");
}

// ── COMPONENTS ───────────────────────────────────────────────────────────────
const LogLine = ({ time, type, msg }) => {
  const colors = {
    info: "#47ffe8",
    ok: "#2ed573",
    err: "#ff4757",
    ai: "#e8ff47",
    msg: "#c0c0d0",
  };
  return (
    <div style={{ display: "flex", gap: 12, fontSize: 12, lineHeight: "1.8", fontFamily: "monospace", animation: "fadeIn 0.3s ease" }}>
      <span style={{ color: "#555", flexShrink: 0 }}>{time}</span>
      <span style={{ color: colors[type] || colors.msg }}>{msg}</span>
    </div>
  );
};

const StatusBadge = ({ status }) => {
  const styles = {
    Done:       { bg: "rgba(46,213,115,0.12)", color: "#2ed573", border: "rgba(46,213,115,0.3)" },
    Error:      { bg: "rgba(255,71,87,0.12)",  color: "#ff4757", border: "rgba(255,71,87,0.3)" },
    Analyzing:  { bg: "rgba(232,255,71,0.12)", color: "#e8ff47", border: "rgba(232,255,71,0.3)" },
    Pending:    { bg: "rgba(255,255,255,0.05)", color: "#666",   border: "rgba(255,255,255,0.1)" },
  };
  const s = styles[status] || styles.Pending;
  return (
    <span style={{ fontSize: 10, fontFamily: "monospace", padding: "3px 10px", borderRadius: 4,
      background: s.bg, color: s.color, border: `1px solid ${s.border}`,
      letterSpacing: 1, textTransform: "uppercase", flexShrink: 0 }}>
      {status}
    </span>
  );
};

// ── MAIN APP ─────────────────────────────────────────────────────────────────
export default function App() {
  const today = new Date().toISOString().split("T")[0];
  const weekAgo = new Date(Date.now() - 7 * 86400000).toISOString().split("T")[0];

  const [fromDate, setFromDate] = useState(weekAgo);
  const [toDate, setToDate] = useState(today);
  const [email, setEmail] = useState("");
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState([]);
  const [videos, setVideos] = useState([]);
  const [progress, setProgress] = useState(0);
  const [done, setDone] = useState(false);
  const [emailSent, setEmailSent] = useState(false);
  const logsRef = useRef(null);

  useEffect(() => {
    if (logsRef.current) logsRef.current.scrollTop = logsRef.current.scrollHeight;
  }, [logs]);

  const ts = () => new Date().toLocaleTimeString("en-US", { hour12: false });

  const addLog = (msg, type = "msg") =>
    setLogs((p) => [...p, { time: ts(), msg, type }]);

  const updateVideo = (idx, patch) =>
    setVideos((p) => p.map((v, i) => (i === idx ? { ...v, ...patch } : v)));

  async function run() {
    if (!fromDate || !toDate || !email) return alert("Please fill all fields.");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return alert("Invalid email.");
    if (new Date(fromDate) > new Date(toDate)) return alert("From date must be before To date.");

    setRunning(true);
    setLogs([]);
    setVideos([]);
    setProgress(0);
    setDone(false);
    setEmailSent(false);

    addLog("Initializing earnings intelligence pipeline...", "info");
    addLog(`Date range: ${fromDate} → ${toDate}`, "msg");
    addLog(`Email: ${email}`, "msg");

    try {
      // Step 1: Fetch videos from backend
      addLog("Connecting to @trendlyne YouTube channel...", "info");
      setProgress(10);

      const vRes = await fetch(`${API_BASE}/api/fetch-videos`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ from_date: fromDate, to_date: toDate }),
      });
      if (!vRes.ok) throw new Error(`Failed to fetch videos: ${vRes.statusText}`);
      const vData = await vRes.json();

      if (!vData.videos?.length) {
        addLog("⚠ No earnings call videos found in this date range.", "err");
        addLog("Try extending your date range.", "msg");
        setRunning(false);
        return;
      }

      addLog(`✓ Found ${vData.videos.length} earnings call(s)`, "ok");
      setVideos(vData.videos.map((v) => ({ ...v, status: "Pending", analysis: "" })));
      setProgress(20);

      // Step 2: For each video — fetch transcript → analyze with FREE Claude API
      const analyses = [];
      for (let i = 0; i < vData.videos.length; i++) {
        const v = vData.videos[i];
        const pct = 20 + Math.round(((i + 1) / vData.videos.length) * 65);

        addLog(`[${i + 1}/${vData.videos.length}] Fetching transcript: ${v.title}`, "info");
        updateVideo(i, { status: "Analyzing" });

        try {
          // Get transcript from backend
          const tRes = await fetch(`${API_BASE}/api/get-transcript/${v.video_id}`, { method: "POST" });
          if (!tRes.ok) throw new Error("Transcript fetch failed");
          const tData = await tRes.json();

          if (!tData.transcript?.trim()) {
            addLog(`⚠ No transcript for: ${v.title}`, "err");
            updateVideo(i, { status: "Error", analysis: "No transcript available." });
            analyses.push({ ...v, analysis: "No transcript available for this video." });
            continue;
          }

          addLog(`✓ Transcript: ${(tData.length / 1000).toFixed(1)}k chars — running AI analysis...`, "ai");

          // Analyze with FREE built-in Claude API
          const analysis = await analyzeWithClaude(tData.transcript, v.title);

          updateVideo(i, { status: "Done", analysis });
          analyses.push({ ...v, analysis });
          addLog(`✓ Analysis complete: ${v.title}`, "ok");
          setProgress(pct);

        } catch (err) {
          addLog(`✗ Failed: ${v.title} — ${err.message}`, "err");
          updateVideo(i, { status: "Error", analysis: `Error: ${err.message}` });
          analyses.push({ ...v, analysis: `Analysis failed: ${err.message}` });
        }
      }

      // Step 3: Send email via backend
      setProgress(92);
      addLog("Sending email report...", "ai");

      const eRes = await fetch(`${API_BASE}/api/send-report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, analyses, from_date: fromDate, to_date: toDate }),
      });
      if (!eRes.ok) throw new Error(`Email send failed: ${eRes.statusText}`);

      setProgress(100);
      addLog(`✓ Report delivered to ${email}`, "ok");
      addLog("Pipeline complete! Check your inbox.", "info");
      setEmailSent(true);
      setDone(true);

    } catch (err) {
      addLog(`✗ Fatal: ${err.message}`, "err");
    } finally {
      setRunning(false);
    }
  }

  // ── RENDER ─────────────────────────────────────────────────────────────────
  return (
    <div style={{
      minHeight: "100vh", background: "#0a0a0f", color: "#f0f0f5",
      fontFamily: "monospace", padding: "0 0 60px",
      backgroundImage: "linear-gradient(rgba(232,255,71,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(232,255,71,0.025) 1px, transparent 1px)",
      backgroundSize: "56px 56px",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@300;400;500&family=Syne:wght@700;800&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        @keyframes fadeIn { from { opacity:0; transform:translateY(4px) } to { opacity:1; transform:translateY(0) } }
        @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.4;transform:scale(.8)} }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
        input { outline: none; }
        input:focus { border-color: #e8ff47 !important; box-shadow: 0 0 0 3px rgba(232,255,71,0.1) !important; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-thumb { background: #1e1e2e; border-radius: 2px; }
      `}</style>

      {/* Header */}
      <div style={{ maxWidth: 820, margin: "0 auto", padding: "0 24px" }}>
        <div style={{ padding: "48px 0 32px", borderBottom: "1px solid #1e1e2e" }}>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 8,
            background: "rgba(232,255,71,0.07)", border: "1px solid rgba(232,255,71,0.2)",
            borderRadius: 4, padding: "4px 12px", fontSize: 10, letterSpacing: 2,
            color: "#e8ff47", textTransform: "uppercase", marginBottom: 20,
            fontFamily: "Syne, sans-serif", fontWeight: 700,
          }}>
            <span style={{ width: 6, height: 6, background: "#e8ff47", borderRadius: "50%", animation: "pulse 2s infinite" }} />
            Open Source · Free · AI-Powered
          </div>
          <h1 style={{ fontFamily: "'DM Serif Display', serif", fontSize: "clamp(34px,6vw,52px)", lineHeight: 1.1, letterSpacing: -1, marginBottom: 12 }}>
            Earnings<br /><em style={{ color: "#e8ff47" }}>Intelligence</em>
          </h1>
          <p style={{ fontSize: 13, color: "#666", lineHeight: 1.7, maxWidth: 480 }}>
            Fetch @trendlyne earnings call transcripts, run deep AI equity analysis for free, and receive a comprehensive report in your inbox.
          </p>
        </div>

        {/* Stats row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 1, background: "#1e1e2e", border: "1px solid #1e1e2e", borderRadius: 8, overflow: "hidden", margin: "32px 0" }}>
          {[["📺","Source","@trendlyne"],["🤖","AI Engine","Built-in Claude (Free)"],["📧","Delivery","Email Report"]].map(([icon,label,val]) => (
            <div key={label} style={{ background: "#111118", padding: "18px 20px", textAlign: "center" }}>
              <div style={{ fontSize: 22, marginBottom: 6 }}>{icon}</div>
              <div style={{ fontSize: 10, letterSpacing: 2, color: "#555", textTransform: "uppercase", marginBottom: 4, fontFamily: "Syne, sans-serif", fontWeight: 700 }}>{label}</div>
              <div style={{ fontSize: 12, color: "#e8ff47", fontWeight: 600 }}>{val}</div>
            </div>
          ))}
        </div>

        {/* Form card */}
        <div style={{ background: "#111118", border: "1px solid #1e1e2e", borderRadius: 12, padding: "32px", marginBottom: 24, position: "relative", overflow: "hidden" }}>
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: "linear-gradient(90deg,transparent,rgba(232,255,71,0.4),transparent)" }} />
          <div style={{ fontSize: 10, letterSpacing: 3, color: "#555", textTransform: "uppercase", marginBottom: 24, fontFamily: "Syne, sans-serif", fontWeight: 700 }}>
            <span style={{ color: "#e8ff47" }}>// </span>Configure Analysis Run
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            {[["FROM DATE", fromDate, setFromDate], ["TO DATE", toDate, setToDate]].map(([lbl, val, setter]) => (
              <div key={lbl}>
                <label style={{ display: "block", fontSize: 10, letterSpacing: 2, color: "#555", textTransform: "uppercase", marginBottom: 8, fontFamily: "Syne, sans-serif", fontWeight: 700 }}>{lbl}</label>
                <input type="date" value={val} onChange={e => setter(e.target.value)}
                  style={{ width: "100%", background: "rgba(255,255,255,0.03)", border: "1px solid #1e1e2e", borderRadius: 6, padding: "10px 14px", color: "#f0f0f5", fontFamily: "monospace", fontSize: 13, transition: "all 0.2s" }} />
              </div>
            ))}
          </div>

          <div style={{ marginBottom: 20 }}>
            <label style={{ display: "block", fontSize: 10, letterSpacing: 2, color: "#555", textTransform: "uppercase", marginBottom: 8, fontFamily: "Syne, sans-serif", fontWeight: 700 }}>RECIPIENT EMAIL</label>
            <input type="email" placeholder="analyst@example.com" value={email} onChange={e => setEmail(e.target.value)}
              style={{ width: "100%", background: "rgba(255,255,255,0.03)", border: "1px solid #1e1e2e", borderRadius: 6, padding: "10px 14px", color: "#f0f0f5", fontFamily: "monospace", fontSize: 13, transition: "all 0.2s" }} />
          </div>

          {/* Progress bar */}
          {running && (
            <div style={{ background: "rgba(255,255,255,0.05)", borderRadius: 2, height: 3, marginBottom: 16, overflow: "hidden" }}>
              <div style={{ height: "100%", background: "linear-gradient(90deg,#e8ff47,#47ffe8)", borderRadius: 2, width: `${progress}%`, transition: "width 0.5s ease" }} />
            </div>
          )}

          <button onClick={run} disabled={running}
            style={{ width: "100%", padding: "14px", background: running ? "rgba(232,255,71,0.4)" : "#e8ff47",
              color: "#0a0a0f", border: "none", borderRadius: 6, fontFamily: "Syne, sans-serif",
              fontSize: 13, fontWeight: 800, letterSpacing: 2, textTransform: "uppercase",
              cursor: running ? "not-allowed" : "pointer", transition: "all 0.15s", display: "flex",
              alignItems: "center", justifyContent: "center", gap: 8 }}>
            <span style={{ fontSize: 16 }}>{running ? "⏳" : "⚡"}</span>
            {running ? "Analyzing..." : "Run Earnings Analysis"}
          </button>
        </div>

        {/* Terminal */}
        {logs.length > 0 && (
          <div style={{ background: "#08080f", border: "1px solid #1e1e2e", borderRadius: 8, overflow: "hidden", marginBottom: 24 }}>
            <div style={{ padding: "10px 16px", background: "#111118", borderBottom: "1px solid #1e1e2e", display: "flex", alignItems: "center", gap: 12, fontSize: 11, color: "#555" }}>
              <div style={{ display: "flex", gap: 5 }}>
                {["#ff5f57","#febc2e","#28c840"].map(c => <div key={c} style={{ width: 10, height: 10, borderRadius: "50%", background: c }} />)}
              </div>
              <span>earnings-analyzer.log</span>
            </div>
            <div ref={logsRef} style={{ padding: "16px 20px", maxHeight: 280, overflowY: "auto" }}>
              {logs.map((l, i) => <LogLine key={i} {...l} />)}
              {running && <span style={{ display: "inline-block", width: 7, height: 12, background: "#e8ff47", verticalAlign: "middle", animation: "blink 1s step-end infinite", marginLeft: 6 }} />}
            </div>
          </div>
        )}

        {/* Video results */}
        {videos.length > 0 && (
          <div style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 10, letterSpacing: 3, color: "#555", textTransform: "uppercase", marginBottom: 14, fontFamily: "Syne, sans-serif", fontWeight: 700 }}>
              <span style={{ color: "#2ed573" }}>// </span>Analysis Results
            </div>
            {videos.map((v, i) => (
              <div key={i} style={{ background: "#111118", border: "1px solid #1e1e2e", borderRadius: 8, padding: "16px 20px", marginBottom: 10, display: "flex", alignItems: "flex-start", gap: 14, transition: "border-color 0.2s" }}>
                <span style={{ fontSize: 18, flexShrink: 0, marginTop: 2 }}>
                  {v.status === "Done" ? "✅" : v.status === "Error" ? "❌" : v.status === "Analyzing" ? "⏳" : "📄"}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: "Syne, sans-serif", fontSize: 13, fontWeight: 700, marginBottom: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v.title}</div>
                  <div style={{ fontSize: 11, color: "#555" }}>Published: {v.published_date} · Duration: {v.duration}</div>
                </div>
                <StatusBadge status={v.status} />
              </div>
            ))}
          </div>
        )}

        {/* Email success */}
        {emailSent && (
          <div style={{ background: "rgba(46,213,115,0.06)", border: "1px solid rgba(46,213,115,0.2)", borderRadius: 8, padding: "20px 24px", display: "flex", alignItems: "center", gap: 16 }}>
            <span style={{ fontSize: 28 }}>✉️</span>
            <div>
              <div style={{ fontFamily: "Syne, sans-serif", fontSize: 14, fontWeight: 800, color: "#2ed573", marginBottom: 4 }}>Report Delivered!</div>
              <div style={{ fontSize: 12, color: "#2ed573" }}>Full AI analysis sent to <strong>{email}</strong></div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
