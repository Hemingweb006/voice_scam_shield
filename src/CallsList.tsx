import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

function fmt(ts) {
  if (!ts) return "—";
  const d = new Date(ts);
  return d.toLocaleString();
}

export default function CallsList({ backend = "http://localhost:8000" }) {
  const [calls, setCalls] = useState([]); // [{sid, from, to, status, started_at, updated_at}]
  const wsRef = useRef(null);

  useEffect(() => {
    const url = `${backend.replace("http", "ws")}/ws/calls`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "calls.snapshot") {
          setCalls(msg.data);
        } else if (msg.type === "call.started") {
          setCalls((prev) => {
            const others = prev.filter((c) => c.sid !== msg.data.sid);
            return [msg.data, ...others];
          });
        } else if (msg.type === "call.ended") {
          setCalls((prev) => prev.map((c) => (c.sid === msg.data.sid ? msg.data : c)));
        }
      } catch {}
    };
    return () => { try { ws.close(); } catch {} };
  }, [backend]);

  return (
    <div style={{ maxWidth: 960, margin: "24px auto", padding: 16 }}>
      <h2 style={{ marginBottom: 12 }}>Calls</h2>
      <div style={{ border: "1px solid #e5e7eb", borderRadius: 12, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead style={{ background: "#f9fafb" }}>
            <tr>
              <th style={{ textAlign: "left", padding: 12 }}>From</th>
              <th style={{ textAlign: "left", padding: 12 }}>To</th>
              <th style={{ textAlign: "left", padding: 12 }}>Status</th>
              <th style={{ textAlign: "left", padding: 12 }}>Started</th>
              <th style={{ textAlign: "left", padding: 12 }}>Updated</th>
              <th style={{ textAlign: "left", padding: 12 }}>Open</th>
            </tr>
          </thead>
          <tbody>
            {calls.map((c) => (
              <tr key={c.sid} style={{ borderTop: "1px solid #f3f4f6" }}>
                <td style={{ padding: 12 }}>{c.from || "unknown"}</td>
                <td style={{ padding: 12 }}>{c.to || "unknown"}</td>
                <td style={{ padding: 12, textTransform: "capitalize" }}>{c.status || "—"}</td>
                <td style={{ padding: 12 }}>{fmt(c.started_at)}</td>
                <td style={{ padding: 12 }}>{fmt(c.updated_at)}</td>
                <td style={{ padding: 12 }}>
                  <Link to={`/call/${c.sid}`} style={{ color: "#2563eb", textDecoration: "none" }}>
                    View
                  </Link>
                </td>
              </tr>
            ))}
            {calls.length === 0 && (
              <tr>
                <td colSpan={6} style={{ padding: 16, opacity: 0.6 }}>
                  No calls yet. Call your Twilio number to start a session.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
