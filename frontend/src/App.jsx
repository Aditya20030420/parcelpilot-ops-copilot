import React, { useEffect, useRef, useState } from "react";
import { chat, confirm, getUsers, getStatus } from "./api.js";
import { renderMarkdown } from "./markdown.js";
import Icon from "./icons.jsx";

// Turn a tool call into a plain-English step the user can follow.
function describeTool(name, args = {}) {
  const a = args || {};
  switch (name) {
    case "search_documents": {
      const where = a.customer ? `${a.customer}'s documents` : "the knowledge base";
      return { icon: "file", label: `Searching ${where}`, detail: a.query ? `“${a.query}”` : "" };
    }
    case "list_data_tables":
      return { icon: "grid", label: "Checking what data is available", detail: "" };
    case "query_operational_data": {
      const f = (a.filters || []).find((x) => x && x.value);
      const val = f?.value;
      let what = `the ${a.table || "data"} table`;
      if (f?.column?.includes("order")) what = `order ${val}`;
      else if (f?.column?.includes("ticket")) what = `ticket ${val}`;
      else if (f?.column?.includes("account")) what = `account ${val}`;
      return { icon: "search", label: `Looking up ${what}`, detail: "" };
    }
    case "get_reference_time":
      return { icon: "clock", label: "Checking the reference date", detail: "" };
    case "compute":
      return {
        icon: "calculator",
        label: a.operation === "service_credit" ? "Calculating the service credit"
          : a.operation === "hours_between" ? "Calculating elapsed time" : "Calculating",
        detail: "",
      };
    case "detect_issues":
      return { icon: "alert", label: "Scanning support activity for issues", detail: "" };
    case "create_escalation":
      return { icon: "escalate", label: "Preparing an escalation", detail: "" };
    case "update_ticket":
      return { icon: "edit", label: "Preparing a ticket update", detail: "" };
    case "create_follow_up_task":
      return { icon: "flag", label: "Preparing a follow-up task", detail: "" };
    default:
      return { icon: "tool", label: name, detail: "" };
  }
}

function describeResult(name, summary) {
  if (!summary) return "";
  if (summary === "access denied") return "Not allowed for your role";
  const m = summary.match(/^(\d+)/);
  const n = m ? m[1] : null;
  if (name === "search_documents") return n ? `Found ${n} relevant passage${n === "1" ? "" : "s"}` : summary;
  if (name === "query_operational_data") return n ? `${n} record${n === "1" ? "" : "s"} found` : summary;
  if (name === "detect_issues") return n ? `${n} finding${n === "1" ? "" : "s"}` : summary;
  if (name === "list_data_tables") return n ? `${n} tables` : summary;
  return "Done";
}

const ROLE_INFO = {
  support_analyst: {
    title: "Support Analyst",
    blurb: "Read-only. Can look things up across documents and data, but cannot make changes.",
  },
  support_agent: {
    title: "Support Agent",
    blurb: "Can look things up and prepare actions for your confirmation. Approves credits up to ₹2,000.",
  },
  ops_manager: {
    title: "Ops Manager",
    blurb: "Full access, including approving larger service credits (up to ₹25,000).",
  },
};

const EXAMPLES = [
  { q: "Can Northstar cancel ORD-1001 without a cancellation fee? Explain why.", tag: "Policy + contract" },
  { q: "ORD-2002 missed pickup due to carrier fault — is a service credit owed, and how much?", tag: "Multi-step + calc" },
  { q: "Scan our support activity for anything urgent or unusual right now.", tag: "Proactive view" },
  { q: "For TKT-450, was the historical resolution actually correct?", tag: "Trust check" },
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
  const roleInfo = currentUser ? ROLE_INFO[currentUser.role] : null;

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
        updateLastAssistant((b) => [...b, { kind: "tool", name: ev.name, args: ev.args, running: true }]);
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
          { kind: "confirm", action_id: ev.action_id, tool_name: ev.tool_name,
            summary: ev.summary, payload: ev.payload, status: "pending" },
        ]);
        break;
      case "action_executed":
        updateLastAssistant((b) =>
          b.map((blk) =>
            blk.kind === "confirm" && blk.status === "confirming"
              ? { ...blk, status: "confirmed", result: ev.result } : blk)
        );
        break;
      case "error":
        updateLastAssistant((b) => [...b, { kind: "text", text: ev.message, error: true }]);
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
    setMessages((prev) => [...prev, { role: "user", text: msg }, { role: "assistant", blocks: [] }]);
    try {
      await chat(msg, sessionRef.current, token, handleEvent);
    } finally {
      setBusy(false);
    }
  }

  async function resolveAction(block, approved) {
    setBusy(true);
    setMessages((prev) => {
      const next = prev.map((m) =>
        m.role === "assistant"
          ? {
              ...m,
              blocks: m.blocks.map((b) =>
                b.kind === "confirm" && b.action_id === block.action_id
                  ? { ...b, status: approved ? "confirming" : "cancelled" } : b),
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
          <span className="logo"><Icon name="box" size={24} /></span>
          <div>
            <div className="title">ParcelPilot Ops Copilot</div>
            <div className="subtitle">Ask about policies, contracts, orders &amp; tickets — in plain English</div>
          </div>
        </div>
        <div className="topbar-right">
          {status?.snapshot_time && (
            <span className="pill" title="All dates and SLAs are measured against this reference time">
              <Icon name="calendar" size={13} />
              Today is {status.snapshot_time.replace("T", " ").slice(0, 10)}
            </span>
          )}
          <label className="role-switch">
            <span>You are signed in as</span>
            <select value={token} onChange={(e) => setToken(e.target.value)}>
              {users.map((u) => (
                <option key={u.token} value={u.token}>{u.name}</option>
              ))}
            </select>
          </label>
        </div>
      </header>

      {roleInfo && (
        <div className="role-banner">
          <span className="role-tag">{roleInfo.title}</span>
          <span className="role-blurb">{roleInfo.blurb}</span>
        </div>
      )}

      <div className="chat" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="empty">
            <div className="empty-icon"><Icon name="message" size={30} /></div>
            <h2>How can I help?</h2>
            <p className="empty-lead">
              I look things up across your documents and operational data, walk through each
              step, and <strong>always ask before making any change</strong>. Try one:
            </p>
            <div className="examples">
              {EXAMPLES.map((ex) => (
                <button key={ex.q} className="example" onClick={() => send(ex.q)}>
                  <span className="example-q">{ex.q}</span>
                  <span className="example-tag">{ex.tag}</span>
                </button>
              ))}
            </div>
            <p className="empty-hint">
              Tip: switch roles (top right) to see how access changes — an Analyst can read but
              not act, an Agent can act with your confirmation.
            </p>
          </div>
        )}

        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="msg user">
              <div className="bubble">{m.text}</div>
            </div>
          ) : (
            <div key={i} className="msg assistant">
              <div className="avatar"><Icon name="bot" size={17} /></div>
              <div className="bubble">
                {m.blocks.length === 0 && busy && i === messages.length - 1 && (
                  <span className="thinking"><span className="dot" /><span className="dot" /><span className="dot" /></span>
                )}
                {m.blocks.map((b, j) => <Block key={j} b={b} onResolve={resolveAction} />)}
              </div>
            </div>
          )
        )}
      </div>

      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <input
          value={input}
          disabled={busy}
          placeholder="Ask a question, e.g. “Can LumenWorks cancel ORD-2001 for free?”"
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
    const d = describeTool(b.name, b.args);
    return (
      <div className={`tool-step ${b.running ? "running" : "done"}`}>
        <span className="tool-icon"><Icon name={d.icon} size={15} /></span>
        <span className="tool-text">
          {d.label}
          {d.detail && <span className="tool-detail"> {d.detail}</span>}
        </span>
        {b.running ? (
          <span className="spinner" />
        ) : (
          <span className="tool-done">{describeResult(b.name, b.summary)}</span>
        )}
      </div>
    );
  }
  if (b.kind === "text") {
    if (b.error) {
      return (
        <div className="text error error-row">
          <Icon name="alert" size={15} />
          <span>{b.text}</span>
        </div>
      );
    }
    return (
      <div className="text" dangerouslySetInnerHTML={{ __html: renderMarkdown(b.text) }} />
    );
  }
  if (b.kind === "confirm") {
    const nice = (k) =>
      ({ ticket_id: "Ticket", account: "Account", reason: "Reason", requested_outcome: "Requested outcome",
         priority: "Priority", new_status: "New status", comment: "Comment", title: "Title",
         due_at: "Due", notes: "Notes", raised_by: "Raised by", updated_by: "Updated by",
         owner: "Owner" }[k] || k);
    return (
      <div className={`confirm-card ${b.status}`}>
        <div className="confirm-head">
          <Icon name="lock" size={15} />
          <span>Please confirm before I do this</span>
        </div>
        <div className="confirm-summary">{b.summary}</div>
        <ul className="confirm-payload">
          {Object.entries(b.payload || {})
            .filter(([, v]) => v !== null && v !== undefined && v !== "")
            .map(([k, v]) => (
              <li key={k}><span className="pk">{nice(k)}</span>: {String(v)}</li>
            ))}
        </ul>
        {b.status === "pending" && (
          <div className="confirm-actions">
            <button className="confirm-yes" onClick={() => onResolve(b, true)}>Yes, do it</button>
            <button className="confirm-no" onClick={() => onResolve(b, false)}>Cancel</button>
          </div>
        )}
        {b.status === "confirming" && <div className="confirm-state">Working on it…</div>}
        {b.status === "confirmed" && (
          <div className="confirm-state ok">
            <Icon name="check" size={15} />
            <span>Done{b.result?.escalation_id ? ` — ${b.result.escalation_id}` : b.result?.task_id ? ` — ${b.result.task_id}` : ""}</span>
          </div>
        )}
        {b.status === "cancelled" && (
          <div className="confirm-state">
            <Icon name="x" size={15} />
            <span>Cancelled — nothing was changed</span>
          </div>
        )}
      </div>
    );
  }
  return null;
}
