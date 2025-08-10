import React, { useEffect, useRef, useState } from "react";

type CallRow = {
  sid: string;
  from?: string;
  to?: string;
  status?: string;
  started_at?: number;
  updated_at?: number;
  ended_at?: number;
};

export default function CallsInbox() {
  const [calls, setCalls] = useState<Record<string, CallRow>>({});
  const wsRef = useRef<WebSocket | null>(null);

  // change this if you want to connect via ngrok from the browser
  const WS_URL =
    (localStorage.getItem("vss_calls_ws") as string) || "ws://localhost:8000/ws/calls";

  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "calls.snapshot") {
          const map: Record<string, CallRow> = {};
          for (const row of msg.data as CallRow[]) map[row.sid] = row;
          setCalls(map);
        } else if (msg.type === "call.started") {
          const d: CallRow = msg.data;
          setCalls((prev) => ({ ...prev, [d.sid]: d }));
        } else if (msg.type === "call.ended") {
          const d: CallRow = msg.data;
          setCalls((prev) => ({ ...prev, [d.sid]: d }));
        }
      } catch {}
    };

    return () => {
      try { ws.close(); } catch {}
    };
  }, [WS_URL]);

  const rows = Object.values(calls).sort(
    (a, b) => (b.updated_at || 0) - (a.updated_at || 0)
  );

  const fmt = (ms?: number) =>
    ms ? new Date(ms).toLocaleTimeString() : "—";

  return (
    <div style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ fontSize: 20, marginBottom: 12 }}>Calls Inbox</h1>
      <div style={{ marginBottom: 12, fontSize: 12, color: "#667" }}>
        WS: {WS_URL} • Tip: set a custom URL via <code>localStorage.setItem("vss_calls_ws","wss://YOUR-NGROK/ws/calls")</code>
      </div>
      <table width="100%" cellPadding={8} style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ background: "#111", color: "#ddd" }}>
            <th align="left">Time</th>
            <th align="left">Caller</th>
            <th align="left">To</th>
            <th align="left">SID</th>
            <th align="left">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={5} style={{ color: "#789" }}>Waiting for a call…</td></tr>
          ) : (
            rows.map((c) => (
              <tr key={c.sid} style={{ borderBottom: "1px solid #222" }}>
                <td>{fmt(c.updated_at || c.started_at)}</td>
                <td>{c.from || "unknown"}</td>
                <td>{c.to || "unknown"}</td>
                <td style={{ fontFamily: "monospace" }}>{c.sid}</td>
                <td style={{ color: c.status === "in-progress" ? "#0bd" : "#9a9" }}>
                  {c.status}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
