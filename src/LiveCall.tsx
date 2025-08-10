import React, { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";

function riskColor(score = 0) {
  if (score >= 70) return "#ef4444"; // red
  if (score >= 30) return "#f59e0b"; // amber
  return "#10b981";                  // green
}
function riskLabel(score = 0) {
  if (score >= 70) return "High";
  if (score >= 30) return "Medium";
  return "Low";
}
function playBeep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.value = 0.05;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    setTimeout(() => { osc.stop(); ctx.close(); }, 180);
  } catch {}
}

export default function LiveCall({ backend = "http://localhost:8000" }) {
  const { sid } = useParams();
  const [lines, setLines] = useState([]); // {text, lang, risk?, ts}
  const [ended, setEnded] = useState(false);
  const listRef = useRef(null);

  // subscribe to per-call feed
  useEffect(() => {
    if (!sid) return;
    const url = `${backend.replace("http", "ws")}/ws/call/${sid}`;
    const ws = new WebSocket(url);

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg?.type === "final" && msg?.text) {
          const score = msg?.risk?.score ?? null;
          // beep if high risk
          if (score !== null && score >= 70) playBeep();
          setLines((prev) => [...prev, {
            text: msg.text,
            lang: msg.lang || "auto",
            risk: msg.risk || null,
            ts: Date.now(),
          }]);
        }
      } catch {}
    };
    ws.onclose = () => {};
    return () => { try { ws.close(); } catch {} };
  }, [sid, backend]);

  // also subscribe to calls bus to detect call end
  useEffect(() => {
    const url = `${backend.replace("http", "ws")}/ws/calls`;
    const ws = new WebSocket(url);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "call.ended" && msg.data?.sid === sid) {
          setEnded(true);
        }
      } catch {}
    };
    return () => { try { ws.close(); } catch {} };
  }, [sid, backend]);

  // autoscroll
  useEffect(() => {
    if (!listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [lines]);

  // risk meter: last N scores & trend
  const N = 6;
  const scores = useMemo(() => lines.map(l => l?.risk?.score).filter(s => typeof s === "number"), [lines]);
  const recent = scores.slice(-N);
  const maxRecent = recent.length ? Math.max(...recent) : 0;
  const prev = recent.length > 1 ? recent[recent.length - 2] : maxRecent;
  const trend = maxRecent > prev ? "up" : maxRecent < prev ? "down" : "flat";
  const topColor = riskColor(maxRecent);

  // summary
  const summary = useMemo(() => {
    const total = lines.length;
    const maxScore = scores.length ? Math.max(...scores) : 0;
    const strategies = {};
    lines.forEach(l => (l?.risk?.strategies || []).forEach(s => strategies[s] = (strategies[s] || 0) + 1));
    const topStrategies = Object.entries(strategies)
      .sort((a,b) => b[1]-a[1])
      .slice(0,5)
      .map(([name,count]) => ({name, count}));
    return { total, maxScore, topStrategies };
  }, [lines, scores]);

  return (
    <div style={{ maxWidth: 960, margin: "16px auto", padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <Link to="/" style={{ textDecoration: "none", color: "#2563eb" }}>← Back</Link>
        <h2 style={{ margin: 0 }}>Live Call</h2>
        <span style={{ marginLeft: "auto", fontSize: 12, opacity: 0.7 }}>SID: {sid}</span>
      </div>

      {/* risk meter */}
      <div style={{
        border: "1px solid #e5e7eb", borderRadius: 12, padding: 12, marginBottom: 12, background: "#fff"
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 10, height: 10, borderRadius: 999, background: topColor
          }} />
          <div style={{ fontWeight: 700 }}>
            Live Risk: {maxRecent || 0} <span style={{ opacity: 0.7 }}>({riskLabel(maxRecent)})</span>
          </div>
          <div style={{ marginLeft: 8, fontSize: 12, opacity: 0.8 }}>
            {trend === "up" && "↑ rising"}
            {trend === "down" && "↓ falling"}
            {trend === "flat" && "→ steady"}
          </div>
        </div>
        <div style={{ height: 8, background: "#f3f4f6", borderRadius: 999, overflow: "hidden", marginTop: 8 }}>
          <div style={{
            width: `${Math.min(Math.max(maxRecent,0),100)}%`,
            height: "100%", background: topColor
          }} />
        </div>
        <div style={{ marginTop: 6, fontSize: 12, opacity: 0.7 }}>
          Max of last {N} scores. Beeps on ≥ 70.
        </div>
      </div>

      {/* transcript */}
      <div
        ref={listRef}
        style={{
          border: "1px solid #e5e7eb",
          borderRadius: 12,
          height: 420,
          overflowY: "auto",
          padding: 12,
          background: "#fff",
          marginBottom: 12
        }}
      >
        {lines.length === 0 && (
          <div style={{ opacity: 0.6, padding: 12 }}>Waiting for speech…</div>
        )}
        {lines.map((line, i) => {
          const score = line?.risk?.score ?? null;
          const color = score !== null ? riskColor(score) : "#9ca3af";
          const label = score !== null ? riskLabel(score) : "—";
          const strategies = line?.risk?.strategies || [];
          const high = score !== null && score >= 70;
          return (
            <div key={i} style={{
              padding: "10px 12px",
              borderRadius: 10,
              border: `1px solid ${high ? "#fecaca" : "#f3f4f6"}`,
              marginBottom: 10,
              background: high ? "#fff1f2" : "#fafafa",
              boxShadow: high ? "inset 0 0 0 1px #fecaca" : "none"
            }}>
              <div style={{ display: "flex", gap: 10, alignItems: "baseline", justifyContent: "space-between" }}>
                <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.4 }}>{line.text}</div>
                <div style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "2px 8px",
                  borderRadius: 999,
                  border: `1px solid ${color}`,
                  color: color,
                  fontSize: 12,
                  fontWeight: 600,
                  flexShrink: 0
                }}>
                  <span>{score !== null ? `${score}` : "?"}</span>
                  <span style={{ opacity: .8 }}>{label}</span>
                </div>
              </div>
              {strategies.length > 0 && (
                <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {strategies.map((s, idx) => (
                    <span key={idx} style={{
                      fontSize: 12, padding: "4px 8px", borderRadius: 999,
                      background: "#eef2ff", color: "#3730a3", border: "1px solid #c7d2fe"
                    }}>
                      {s}
                    </span>
                  ))}
                </div>
              )}
              {high && (
                <div style={{ marginTop: 8, fontSize: 12, color: "#991b1b" }}>
                  ⚠️ Potential scam — proceed with caution.
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* summary */}
      {ended && (
        <div style={{ border: "1px solid #e5e7eb", borderRadius: 12, padding: 12, background: "#fff" }}>
          <h3 style={{ marginTop: 0 }}>Call Summary</h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <div><b>Total sentences:</b> {summary.total}</div>
              <div><b>Max risk:</b> {summary.maxScore} ({riskLabel(summary.maxScore)})</div>
            </div>
            <div>
              <b>Top strategies:</b>
              <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 6 }}>
                {summary.topStrategies.length === 0 && <span style={{ opacity: 0.6 }}>None</span>}
                {summary.topStrategies.map((it, idx) => (
                  <span key={idx} style={{
                    fontSize: 12, padding: "4px 8px", borderRadius: 999,
                    background: "#fef3c7", color: "#92400e", border: "1px solid #fde68a"
                  }}>
                    {it.name} × {it.count}
                  </span>
                ))}
              </div>
            </div>
          </div>
          <div style={{ marginTop: 12, fontSize: 12, opacity: 0.7 }}>
            Tip: screenshot this summary for your report.
          </div>
        </div>
      )}
    </div>
  );
}
