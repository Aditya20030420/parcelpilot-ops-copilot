// Minimal SSE-over-POST client. EventSource only does GET, so we stream the
// fetch body and parse `data: {json}` frames ourselves.
const API_BASE = import.meta.env.VITE_API_BASE || "";

async function streamPost(path, body, token, onEvent) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    onEvent({ type: "error", message: `HTTP ${res.status}` });
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const frames = buf.split("\n\n");
    buf = frames.pop() || "";
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)));
      } catch {
        /* ignore malformed frame */
      }
    }
  }
}

export function chat(message, sessionId, token, onEvent) {
  return streamPost("/api/chat", { message, session_id: sessionId }, token, onEvent);
}

export function confirm(sessionId, actionId, approved, token, onEvent) {
  return streamPost(
    "/api/confirm",
    { session_id: sessionId, action_id: actionId, approved },
    token,
    onEvent
  );
}

export async function login(username, password) {
  const res = await fetch(`${API_BASE}/api/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Login failed");
  return data; // { token, user }
}

export async function getLoginHints() {
  const res = await fetch(`${API_BASE}/api/login-hints`);
  return res.json();
}

export async function getUsers() {
  const res = await fetch(`${API_BASE}/api/users`);
  return res.json();
}

export async function getStatus() {
  const res = await fetch(`${API_BASE}/api/status`);
  return res.json();
}
