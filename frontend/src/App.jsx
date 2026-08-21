import React, { useEffect, useRef, useState } from "react";
import { chat, confirm, getUsers, getStatus } from "./api.js";

const TOOL_LABELS = {
  search_documents: "📄 Searching documents",
  list_data_tables: "🗂️ Listing tables",
  query_operational_data: "🔎 Querying operational data",
  get_reference_time: "🕒 Reading snapshot time",
  compute: "🧮 Calculating",
  detect_issues: "🚨 Scanning for issues",
  create_escalation: "⤴️ Preparing escalation",
  update_ticket: "✏️ Preparing ticket update",
  create_follow_up_task: "📌 Preparing follow-up task",
};

const EXAMPLES = [
  "Can Northstar cancel ORD-1001 without a cancellation fee? Explain why.",
  "ORD-2002 missed pickup due to carrier fault — is a service credit owed, and how much?",
  "Scan our open tickets for anything urgent or unusual right now.",
  "For TKT-450, was the historical resolution actually correct?",
];

export default function App() {
  const [users, setUsers] = useState([]);
  const [token, setToken] = useState("token-agent");
  const [status, setStatus] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    getUsers().then((d) => setUsers(d.users || []));
    getStatus().then(setStatus).catch(() => {});
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages, busy]);

  const currentUser = users.find((u) => u.token === token);

  function updateLastAssistant(mutator) {
    setMessages((prev) => {
      const next = [...prev];
      for (let i = next.length - 1; i >= 0; i--) {
        if (next[i].role === "assistant") {
          next[i] = { ...next[i], blocks: mutator([...next[i].blocks]) };
          break;
        }
      }
      return next;
    });
  }

  function handleEvent(ev) {
    switch (ev.type) {
      case "session":
        sessionRef.current = ev.session_id;
        break;
      case "tool_call":
        updateLastAssistant((b) => [
          ...b,
          { kind: "tool", name: ev.name, args: ev.args, running: true },
        ]);
        break;
      case "tool_result":
        updateLastAssistant((b) => {
          const copy = [...b];
          for (let i = copy.length - 1; i >= 0; i--) {
            if (copy[i].kind === "tool" && copy[i].name === ev.name && copy[i].running) {
              copy[i] = { ...copy[i], running: false, summary: ev.summary };
              break;
            }
          }
          return copy;
        });
        break;
      case "assistant_text":
        updateLastAssistant((b) => [...b, { kind: "text", text: ev.text }]);
        break;
      case "confirmation_required":
        updateLastAssistant((b) => [
          ...b,
          {
            kind: "confirm",
            action_id: ev.action_id,
            tool_name: ev.tool_name,
            summary: ev.summary,
            payload: ev.payload,
            status: "pending",
          },
        ]);
        break;
      case "action_executed":
        updateLastAssistant((b) =>
          b.map((blk) =>
            blk.kind === "confirm" && blk.status === "confirming"
              ? { ...blk, status: "confirmed", result: ev.result }
              : blk
          )
        );
        break;
      case "error":
        updateLastAssistant((b) => [
          ...b,
          { kind: "text", text: `⚠️ ${ev.message}`, error: true },
        ]);
        break;
      default:
        break;
    }
  }

  async function send(text) {
    const msg = (text ?? input).trim();
    if (!msg || busy) return;
    setInput("");
    setBusy(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", text: msg },
      { role: "assistant", blocks: [] },
    ]);
    try {
      await chat(msg, sessionRef.current, token, handleEvent);
    } finally {
      setBusy(false);
    }
  }

  async function resolveAction(block, approved) {
    setBusy(true);
    // Mark this confirm block, and add a fresh assistant bubble for the follow-up.
    setMessages((prev) => {
      const next = prev.map((m) =>
        m.role === "assistant"
          ? {
              ...m,
              blocks: m.blocks.map((b) =>
                b.kind === "confirm" && b.action_id === block.action_id
                  ? { ...b, status: approved ? "confirming" : "cancelled" }
                  : b
              ),
            }
          : m
      );
      return [...next, { role: "assistant", blocks: [] }];
    });
    try {
      await confirm(sessionRef.current, block.action_id, approved, token, handleEvent);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">📦</span>
          <div>
            <div className="title">ParcelPilot Ops Copilot</div>
            <div className="subtitle">Internal support &amp; operations assistant</div>
          </div>
        </div>
        <div className="topbar-right">
          {status?.snapshot_time && (
            <span className="pill" title="Reference time for all date math">
              🕒 snapshot {status.snapshot_time.replace("T", " ").slice(0, 16)}
            </span>
          )}
          <label className="role-switch">
            <span>Acting as</span>
            <select value={token} onChange={(e) => setToken(e.target.value)}>
              {users.map((u) => (
                <option key={u.token} value={u.token}>
                  {u.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      {currentUser && (
        <div className="perms-bar">
          <strong>{currentUser.role}</strong> — can:{" "}
          {currentUser.permissions.map((p) => (
            <span key={p} className="perm">
              {p}
            </span>
          ))}
          {currentUser.credit_approval_limit > 0 && (
            <span className="perm limit">
              credit limit ₹{currentUser.credit_approval_limit}
            </span>
          )}
        </div>
      )}

      <div className="chat" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="empty">
            <h2>Ask about policies, contracts, orders, tickets, or SLAs.</h2>
            <p>Access is scoped to your role, and any action needs your confirmation.</p>
            <div className="examples">
              {EXAMPLES.map((ex) => (
                <button key={ex} className="example" onClick={() => send(ex)}>
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="msg user">
              <div className="bubble">{m.text}</div>
            </div>
          ) : (
            <div key={i} className="msg assistant">
              <div className="bubble">
                {m.blocks.length === 0 && busy && i === messages.length - 1 && (
                  <span className="thinking">Thinking…</span>
                )}
                {m.blocks.map((b, j) => (
                  <Block key={j} b={b} onResolve={resolveAction} />
                ))}
              </div>
            </div>
          )
        )}
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <input
          value={input}
          disabled={busy}
          placeholder="Ask a support or operations question…"
          onChange={(e) => setInput(e.target.value)}
        />
        <button type="submit" disabled={busy || !input.trim()}>
          {busy ? "…" : "Send"}
        </button>
      </form>
    </div>
  );
}

function Block({ b, onResolve }) {
  if (b.kind === "tool") {
    return (
      <div className={`tool-chip ${b.running ? "running" : "done"}`}>
        <span className="tool-label">{TOOL_LABELS[b.name] || b.name}</span>
        {b.args && Object.keys(b.args).length > 0 && (
          <code className="tool-args">{compactArgs(b.args)}</code>
        )}
        {b.running ? (
          <span className="spinner" />
        ) : (
          <span className="tool-summary">{b.summary}</span>
        )}
      </div>
    );
  }
  if (b.kind === "text") {
    return <div className={`text ${b.error ? "error" : ""}`}>{b.text}</div>;
  }
  if (b.kind === "confirm") {
    return (
      <div className={`confirm-card ${b.status}`}>
        <div className="confirm-head">
          🔐 Action needs your confirmation
          <span className="confirm-tool">{b.tool_name}</span>
        </div>
        <div className="confirm-summary">{b.summary}</div>
        <ul className="confirm-payload">
          {Object.entries(b.payload || {})
            .filter(([, v]) => v !== null && v !== undefined && v !== "")
            .map(([k, v]) => (
              <li key={k}>
                <span className="pk">{k}</span>: {String(v)}
              </li>
            ))}
        </ul>
        {b.status === "pending" && (
          <div className="confirm-actions">
            <button className="confirm-yes" onClick={() => onResolve(b, true)}>
              Confirm &amp; execute
            </button>
            <button className="confirm-no" onClick={() => onResolve(b, false)}>
              Cancel
            </button>
          </div>
        )}
        {b.status === "confirming" && <div className="confirm-state">Executing…</div>}
        {b.status === "confirmed" && (
          <div className="confirm-state ok">✓ Executed{b.result?.escalation_id ? ` — ${b.result.escalation_id}` : b.result?.task_id ? ` — ${b.result.task_id}` : ""}</div>
        )}
        {b.status === "cancelled" && <div className="confirm-state">✕ Cancelled</div>}
      </div>
    );
  }
  return null;
}

function compactArgs(args) {
  const parts = Object.entries(args)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`);
  const s = parts.join(", ");
  return s.length > 90 ? s.slice(0, 90) + "…" : s;
}
