import React, { useEffect, useState } from "react";
import { login, getLoginHints } from "./api.js";
import Icon from "./icons.jsx";

export default function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [hints, setHints] = useState(null);

  useEffect(() => {
    getLoginHints().then(setHints).catch(() => {});
  }, []);

  async function submit(e) {
    e.preventDefault();
    if (!username || !password || busy) return;
    setBusy(true);
    setError("");
    try {
      const data = await login(username.trim(), password);
      onLogin(data);
    } catch (err) {
      setError(err.message || "Login failed");
    } finally {
      setBusy(false);
    }
  }

  function quickFill(u) {
    setUsername(u);
    setPassword(hints?.password || "");
    setError("");
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-brand">
          <span className="logo"><Icon name="box" size={26} /></span>
          <div>
            <div className="login-title">ParcelPilot</div>
            <div className="login-sub">Support &amp; Operations sign in</div>
          </div>
        </div>

        <form onSubmit={submit} className="login-form">
          <label className="field">
            <span>Username</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g. marco or northstar"
              autoFocus
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
            />
          </label>
          {error && (
            <div className="login-error"><Icon name="alert" size={14} /> <span>{error}</span></div>
          )}
          <button type="submit" disabled={busy || !username || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        {hints && (
          <div className="login-demo">
            <div className="login-demo-head">Demo accounts — password <code>{hints.password}</code></div>
            <div className="login-demo-cols">
              <div>
                <div className="login-demo-label">Staff</div>
                {hints.staff.map((h) => (
                  <button key={h.username} className="login-chip" onClick={() => quickFill(h.username)}>
                    <strong>{h.username}</strong> — {h.label.replace(/^[^—]*—\s*/, "")}
                  </button>
                ))}
              </div>
              <div>
                <div className="login-demo-label">Customers</div>
                {hints.customers.map((h) => (
                  <button key={h.username} className="login-chip" onClick={() => quickFill(h.username)}>
                    <strong>{h.username}</strong> — {h.label.replace(/\s*\(customer\)/, "")}
                  </button>
                ))}
              </div>
            </div>
            <div className="login-demo-foot">
              Staff see the internal operations copilot; customers see their own support chat.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
