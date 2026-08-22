import React, { useEffect, useRef, useState } from "react";
import { chat, confirm, getStatus } from "./api.js";
import { renderMarkdown } from "./markdown.js";
import Icon from "./icons.jsx";
import Login from "./Login.jsx";

const AUTH_KEY = "pp_auth";

function formatDate(value) {
  if (!value) return "No snapshot";
  return value.slice(0, 10);
}

function tableRows(status, name) {
  const tables = status?.structured?.tables || [];
  const hit = tables.find((t) => (t.table || "").toLowerCase().includes(name));
  return hit?.row_count ?? "-";
}

function initials(name) {
  const words = (name || "").replace(/\(.*?\)/, "").trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  const w = words[0] || "?";
  const caps = w.match(/[A-Z]/g);
  if (caps && caps.length >= 2) return (caps[0] + caps[1]).toUpperCase();
  return w.slice(0, 2).toUpperCase();
}

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
  customer: {
    title: "Customer",
    blurb: "You only see your own account's orders, tickets and agreement. I'll bring in a human when needed.",
  },
};

function staffExamples(role) {
  const common = [
    { q: "Can Northstar cancel ORD-1001 without a cancellation fee? Explain why.", tag: "Contract" },
    { q: "ORD-2002 missed pickup due to carrier fault — is a service credit owed, and how much?", tag: "Calculation" },
    { q: "Scan our support activity for anything urgent or unusual right now.", tag: "Ops scan" },
    { q: "For TKT-450, was the historical resolution actually correct?", tag: "Trust check" },
  ];
  // A read-only analyst can't act; agents/managers should see the confirmation flow.
  const fourth = role === "support_analyst"
    ? { q: "Escalate the possible API key exposure on TKT-505 to security urgently.", tag: "Access boundary" }
    : { q: "Escalate the possible API key exposure on TKT-505 to security urgently.", tag: "Confirmation" };
  return [...common, fourth];
}

const CUSTOMER_EXAMPLES = [
  { q: "Can I cancel my order ORD-1001 without a cancellation fee?", tag: "Order" },
  { q: "One of my pickups was missed due to carrier fault — am I owed a service credit?", tag: "Credit" },
  { q: "What are my support response times?", tag: "Agreement" },
  { q: "I'd like to raise a billing issue with a person.", tag: "Escalation" },
];

function exampleIcon(tag) {
  if (tag === "Ops scan" || tag === "Access boundary") return "alert";
  if (tag === "Calculation" || tag === "Credit") return "calculator";
  if (tag === "Confirmation" || tag === "Escalation") return "escalate";
  if (tag === "Contract" || tag === "Agreement") return "file";
  return "search";
}

export default function App() {
  const [auth, setAuth] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(AUTH_KEY) || "null");
    } catch {
      return null;
    }
  });
  const [status, setStatus] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    getStatus().then(setStatus).catch(() => {});
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages, busy]);

  function handleLogin(data) {
    localStorage.setItem(AUTH_KEY, JSON.stringify(data));
    setMessages([]);
    sessionRef.current = null;
    setAuth(data);
  }

  function logout() {
    localStorage.removeItem(AUTH_KEY);
    setMessages([]);
    sessionRef.current = null;
    setAuth(null);
  }

  function newChat() {
    if (busy) return;
    setMessages([]);
    sessionRef.current = null;
  }

  if (!auth) return <Login onLogin={handleLogin} />;

  const token = auth.token;
  const currentUser = auth.user;
  const mode = currentUser.kind === "customer" ? "customer" : "staff";
  const roleInfo = ROLE_INFO[currentUser.role];
  const examples = mode === "customer" ? CUSTOMER_EXAMPLES : staffExamples(currentUser.role);

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
      case "sources":
        setMessages((prev) => {
          const next = [...prev];
          for (let i = next.length - 1; i >= 0; i--) {
            if (next[i].role === "assistant") {
              const seen = new Set((next[i].sources || []).map((s) => `${s.source}|${s.page}`));
              const merged = [...(next[i].sources || [])];
              for (const s of ev.items || []) {
                const key = `${s.source}|${s.page}`;
                if (s.source && !seen.has(key)) { seen.add(key); merged.push(s); }
              }
              next[i] = { ...next[i], sources: merged };
              break;
            }
          }
          return next;
        });
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
            <div className="title">
              ParcelPilot {mode === "customer" ? "Support" : "Ops Copilot"}
            </div>
            <div className="subtitle">
              {mode === "customer"
                ? "Help with your orders, cancellations, credits & account"
                : "Ask about policies, contracts, orders & tickets — in plain English"}
            </div>
          </div>
        </div>
        <div className="topbar-right">
          {mode === "staff" && status?.snapshot_time && (
            <span className="pill" title="All dates and SLAs are measured against this reference time">
              <Icon name="calendar" size={13} />
              Snapshot {formatDate(status.snapshot_time)}
            </span>
          )}
          <button className="newchat" onClick={newChat} disabled={busy} title="Start a new conversation">
            <Icon name="message" size={14} />
            <span>New chat</span>
          </button>
          <div className="who">
            <span className={`who-avatar ${mode === "customer" ? "customer" : ""}`}>
              {initials(currentUser.name)}
            </span>
            <span className="who-name">{currentUser.name}</span>
            <button className="logout" onClick={logout}>Sign out</button>
          </div>
        </div>
      </header>

      {roleInfo && (
        <div className={`role-banner ${mode === "customer" ? "customer" : ""}`}>
          <span className="role-tag">
            {mode === "customer" && currentUser?.account_name
              ? `${currentUser.account_name} · account ${currentUser.account_id}`
              : roleInfo.title}
          </span>
          <span className="role-blurb">{roleInfo.blurb}</span>
        </div>
      )}

      <div className="workspace">
        <main className="chat-shell">
          <div className="chat" ref={scrollRef}>
            {messages.length === 0 && (
              <div className="empty">
                <div className="empty-head">
                  <div className="empty-icon"><Icon name="message" size={28} /></div>
                  <div>
                    <h2>{mode === "customer" ? "Start with your account" : "Start with the live queue"}</h2>
                    <p className="empty-lead">
                      {mode === "customer" ? (
                        <>Ask about orders, cancellations, service credits, or an account question that should move to the support team.</>
                      ) : (
                        <>Use the official ParcelPilot pack to check policy, contracts, operational records, source conflicts, and confirmation-gated actions.</>
                      )}
                    </p>
                  </div>
                </div>
                <div className="examples">
                  {examples.map((ex) => (
                    <button key={ex.q} className="example" onClick={() => send(ex.q)}>
                      <span className="example-main">
                        <Icon name={exampleIcon(ex.tag)} size={15} />
                        <span className="example-q">{ex.q}</span>
                      </span>
                      <span className="example-tag">{ex.tag}</span>
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
                  <div className="avatar"><Icon name="bot" size={17} /></div>
                  <div className="bubble">
                    {m.blocks.length === 0 && busy && i === messages.length - 1 && (
                      <span className="thinking"><span className="dot" /><span className="dot" /><span className="dot" /></span>
                    )}
                    {m.blocks.map((b, j) => <Block key={j} b={b} onResolve={resolveAction} />)}
                    {m.sources?.length > 0 && <Sources items={m.sources} />}
                  </div>
                </div>
              )
            )}
          </div>

          <form className="composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <input
              value={input}
              disabled={busy}
              placeholder={mode === "customer"
                ? "Ask about your orders, cancellations or account..."
                : "Ask a question, e.g. \"Can LumenWorks cancel ORD-2001 for free?\""}
              onChange={(e) => setInput(e.target.value)}
            />
            <button className="send-btn" type="submit" disabled={busy || !input.trim()} title="Send message" aria-label="Send message">
              {busy ? <span className="btn-spinner" /> : <Icon name="send" size={17} />}
            </button>
          </form>
        </main>

        <ContextPanel
          status={status}
          mode={mode}
          currentUser={currentUser}
          onAsk={send}
          busy={busy}
        />
      </div>
    </div>
  );
}

const TIER_LABEL = {
  customer_contract: "Contract",
  current_sop: "Current SOP",
  current_policy: "Current policy",
  product_docs: "Product docs",
  deprecated_policy: "Deprecated",
  historical_ticket: "Past ticket",
};

function Sources({ items }) {
  return (
    <div className="sources">
      <div className="sources-head"><Icon name="file" size={12} /> Sources</div>
      <div className="sources-list">
        {items.map((s, i) => (
          <span key={i} className={`source-chip tier-${s.tier}`} title={`Authority ${s.authority}`}>
            <span className="source-name">{s.source}</span>
            {s.page ? <span className="source-page">p.{s.page}</span> : null}
            <span className="source-tier">{TIER_LABEL[s.tier] || s.tier}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

const AUTHORITY_STACK = [
  ["Contract", "Customer-specific terms"],
  ["Current SOP", "Cancellations and credits"],
  ["Policy v3", "General support rules"],
  ["Product docs", "Known behavior"],
  ["Deprecated/history", "Context only"],
];

function signalsFor(user, mode) {
  if (mode === "customer") {
    if (user.account_id === "ACCT-002") {
      return [
        ["ORD-2002", "Missed pickup credit", "Was my missed pickup on ORD-2002 eligible for a service credit?"],
        ["TKT-502", "Bulk upload ticket", "What is the latest on TKT-502?"],
      ];
    }
    if (user.account_id === "ACCT-003") {
      return [
        ["ORD-3001", "Cancellation request", "Can I cancel ORD-3001 without a fee?"],
        ["TKT-503", "Billing contact", "Can you help with TKT-503?"],
      ];
    }
    return [
      ["ORD-1001", "Cancellation window", "Can I cancel ORD-1001 without a fee?"],
      ["TKT-501", "Shipment creation issue", "What should happen next on TKT-501?"],
    ];
  }
  return [
    ["TKT-501", "Outage-like signal", "What should we do about TKT-501?"],
    ["TKT-505", "Security signal", "Escalate the possible API key exposure on TKT-505 to security urgently."],
    ["ORD-2002", "Carrier fault", "Is ORD-2002 eligible for a service credit and how much?"],
  ];
}

function ContextPanel({ status, mode, currentUser, onAsk, busy }) {
  const docs = status?.documents?.documents?.length ?? "-";
  const chunks = status?.documents?.chunks ?? "-";
  const snapshot = formatDate(status?.snapshot_time);
  const signals = signalsFor(currentUser, mode);

  return (
    <aside className="context-panel">
      <section className="context-section identity-section">
        <div className="panel-kicker">{mode === "customer" ? "Account context" : "Assessment data"}</div>
        <div className="context-title">
          {mode === "customer" ? currentUser.account_name : "Official ParcelPilot pack"}
        </div>
        <div className="context-sub">
          {mode === "customer" ? `Account ${currentUser.account_id}` : `Snapshot ${snapshot}`}
        </div>
      </section>

      <section className="context-section">
        <div className="section-title"><Icon name="database" size={14} /> Records</div>
        <div className="metric-grid">
          <Metric label="Docs" value={docs} />
          <Metric label="Passages" value={chunks} />
          <Metric label="Accounts" value={tableRows(status, "accounts")} />
          <Metric label="Orders" value={tableRows(status, "orders")} />
          <Metric label="Tickets" value={tableRows(status, "tickets")} />
        </div>
      </section>

      {mode === "staff" && (
        <section className="context-section">
          <div className="section-title"><Icon name="layers" size={14} /> Source Authority</div>
          <ol className="authority-list">
            {AUTHORITY_STACK.map(([label, detail]) => (
              <li key={label}>
                <span>{label}</span>
                <small>{detail}</small>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section className="context-section">
        <div className="section-title"><Icon name="flag" size={14} /> Try Records</div>
        <div className="signal-list">
          {signals.map(([id, title, prompt]) => (
            <button key={id} className="signal" onClick={() => onAsk(prompt)} disabled={busy}>
              <span className="signal-id">{id}</span>
              <span className="signal-title">{title}</span>
            </button>
          ))}
        </div>
      </section>
    </aside>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <span className="metric-value">{value}</span>
      <span className="metric-label">{label}</span>
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
