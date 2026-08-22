import React, { useEffect, useRef, useState } from "react";
import { login, getLoginHints } from "./api.js";
import Icon from "./icons.jsx";

function initials(name) {
  const clean = name.replace(/\(.*?\)/, "").trim();
  const words = clean.split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  const w = words[0] || "";
  const caps = w.match(/[A-Z]/g); // camelCase like "LumenWorks" -> "LW"
  if (caps && caps.length >= 2) return (caps[0] + caps[1]).toUpperCase();
  return w.slice(0, 2).toUpperCase();
}

export default function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [hints, setHints] = useState(null);
  const shakeRef = useRef(null);

  useEffect(() => {
    getLoginHints().then(setHints).catch(() => {});
  }, []);

  async function doLogin(u, p) {
    setBusy(true);
    setError("");
    try {
      const data = await login(u.trim(), p);
      onLogin(data);
    } catch (err) {
      setError(err.message || "Login failed");
      // retrigger the shake animation
      if (shakeRef.current) {
        shakeRef.current.classList.remove("shake");
        void shakeRef.current.offsetWidth;
        shakeRef.current.classList.add("shake");
      }
      setBusy(false);
    }
  }

  function submit(e) {
    e.preventDefault();
    if (!username || !password || busy) return;
    doLogin(username, password);
  }

  function signInAs(u) {
    if (busy) return;
    setUsername(u);
    setPassword(hints?.password || "");
    doLogin(u, hints?.password || "");
  }

  return (
    <div className="login-page">
      <aside className="login-hero">
        <div className="hero-brand">
          <span className="hero-logo"><Icon name="box" size={26} /></span>
          <span className="hero-name">ParcelPilot</span>
        </div>
        <div className="hero-body">
          <h1>Support answers your team can trust.</h1>
          <p>One AI copilot for ParcelPilot — it answers customers and helps staff
            investigate, grounded in your policies, contracts and live order data.</p>
          <ul className="hero-points">
            <li><span className="hp-ic"><Icon name="shield" size={16} /></span>
              Every answer cites the policy or contract that governs it</li>
            <li><span className="hp-ic"><Icon name="users" size={16} /></span>
              Scoped access — customers only ever see their own account</li>
            <li><span className="hp-ic"><Icon name="check" size={16} /></span>
              Confirms before it acts, and escalates when unsure</li>
          </ul>
        </div>
        <div className="hero-foot">Assessment demo · synthetic data</div>
      </aside>

      <main className="login-panel">
        <div className="login-box" ref={shakeRef}>
          <div className="login-box-head">
            <h2>Sign in</h2>
            <p>Use your ParcelPilot credentials to continue.</p>
          </div>

          <form onSubmit={submit} className="login-form">
            <label className="field">
              <span>Username</span>
              <div className="input-wrap">
                <Icon name="user" size={15} className="input-ic" />
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="e.g. diego or northstar"
                  autoFocus
                  autoComplete="username"
                />
              </div>
            </label>
            <label className="field">
              <span>Password</span>
              <div className="input-wrap">
                <Icon name="lock" size={15} className="input-ic" />
                <input
                  type={showPw ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Password"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  className="pw-toggle"
                  onClick={() => setShowPw((s) => !s)}
                  aria-label={showPw ? "Hide password" : "Show password"}
                >
                  <Icon name={showPw ? "eye-off" : "eye"} size={15} />
                </button>
              </div>
            </label>
            {error && (
              <div className="login-error"><Icon name="alert" size={14} /> <span>{error}</span></div>
            )}
            <button type="submit" className="signin-btn" disabled={busy || !username || !password}>
              {busy ? <span className="btn-spinner" /> : "Sign in"}
            </button>
          </form>

          {hints && (
            <div className="login-demo">
              <div className="demo-divider"><span>or continue as a demo user</span></div>
              <div className="demo-grid">
                <div className="demo-col">
                  <div className="demo-col-head"><Icon name="users" size={13} /> Staff</div>
                  {hints.staff.map((h) => (
                    <DemoRow key={h.username} h={h} kind="staff"
                             onClick={() => signInAs(h.username)} disabled={busy} />
                  ))}
                </div>
                <div className="demo-col">
                  <div className="demo-col-head"><Icon name="user" size={13} /> Customers</div>
                  {hints.customers.map((h) => (
                    <DemoRow key={h.username} h={h} kind="customer"
                             onClick={() => signInAs(h.username)} disabled={busy} />
                  ))}
                </div>
              </div>
              <div className="demo-foot">All demo passwords are <code>{hints.password}</code>. One click signs you in.</div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function DemoRow({ h, kind, onClick, disabled }) {
  return (
    <button className={`demo-row ${kind}`} onClick={onClick} disabled={disabled}
            title={`Sign in as @${h.username}`}>
      <span className="demo-avatar">{initials(h.name)}</span>
      <span className="demo-meta">
        <span className="demo-user">{h.name}</span>
        <span className="demo-sub">{h.desc} · @{h.username}</span>
      </span>
      <span className="demo-arrow"><Icon name="escalate" size={14} /></span>
    </button>
  );
}
