"""FastAPI entrypoint: chat (SSE), action confirmation, status, and user directory."""
from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from .agent.loop import AgentRunner
from .auth import (
    Perm,
    authenticate,
    demo_login_hints,
    public_directory,
    resolve_user,
    user_public,
)
from .config import settings
from .core.knowledge import knowledge
from .core.session import store
from .tools.context import ToolContext
from .tools.registry import execute_action

app = FastAPI(title="ParcelPilot Ops Copilot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    knowledge.load()


# --- schemas ---------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ConfirmRequest(BaseModel):
    session_id: str
    action_id: str
    approved: bool


class LoginRequest(BaseModel):
    username: str
    password: str


# --- helpers ---------------------------------------------------------------
def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _ctx(token: str | None, session_id: str) -> ToolContext:
    return ToolContext(user=resolve_user(token), session_id=session_id,
                       knowledge=knowledge, store=store)


# Permission each state-changing tool requires (re-checked at execution time).
_ACTION_PERM = {
    "create_escalation": Perm.ACT_ESCALATE,
    "update_ticket": Perm.ACT_TICKET,
    "create_follow_up_task": Perm.ACT_ESCALATE,
}


# --- routes ----------------------------------------------------------------
@app.get("/healthz")
def healthz():
    """Lightweight liveness/readiness probe for Render and uptime monitors.

    Returns 200 when the process is up and the knowledge base has loaded; 503 otherwise so
    a monitor can distinguish "starting/broken" from "ready"."""
    ready = knowledge.loaded and knowledge.docs.ready
    payload = {
        "status": "ok" if ready else "starting",
        "ready": ready,
        "documents": len(knowledge.docs.chunks),
        "tables": len(knowledge.data.tables),
        "snapshot_time": knowledge.snapshot_time.isoformat() if knowledge.loaded else None,
    }
    return JSONResponse(status_code=200 if ready else 503, content=payload)


@app.get("/api/status")
def status():
    return knowledge.status()


@app.get("/api/login-hints")
def login_hints():
    """Demo credentials shown on the login page (assessment convenience)."""
    return demo_login_hints()


@app.post("/api/login")
def login(req: LoginRequest):
    result = authenticate(req.username, req.password)
    if result is None:
        return JSONResponse(status_code=401, content={"error": "Invalid username or password."})
    token, user = result
    return {"token": token, "user": user_public(user)}


@app.get("/api/users")
def users():
    return {"users": public_directory()}


@app.get("/api/audit")
def audit():
    """Committed side effects — handy for the demo to prove actions really ran."""
    return {"audit_log": store.audit_log}


@app.post("/api/chat")
async def chat(req: ChatRequest, authorization: str | None = Header(default=None)):
    token = _token(authorization)
    session = store.get_or_create(req.session_id)
    ctx = _ctx(token, session.session_id)
    runner = AgentRunner(ctx, session)

    async def gen() -> AsyncIterator[str]:
        yield _sse({"type": "session", "session_id": session.session_id})
        async for event in runner.run(req.message):
            yield _sse(event)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/confirm")
async def confirm(req: ConfirmRequest, authorization: str | None = Header(default=None)):
    token = _token(authorization)
    session = store.get_or_create(req.session_id)
    ctx = _ctx(token, session.session_id)
    action = store.get_pending(req.action_id)

    async def gen() -> AsyncIterator[str]:
        yield _sse({"type": "session", "session_id": session.session_id})
        if action is None or action.session_id != session.session_id:
            yield _sse({"type": "error", "message": "Unknown or mismatched action."})
            return
        if action.status != "pending":
            yield _sse({"type": "error", "message": f"Action already {action.status}."})
            return

        if not req.approved:
            action.status = "cancelled"
            ack = "No problem — I've cancelled that. Nothing was changed. Let me know if you'd like to adjust anything."
            note = f"[SYSTEM] The user cancelled the prepared action '{action.tool_name}' ({action.summary})."
        else:
            # Re-enforce authorization at execution time, not just at prepare time.
            perm = _ACTION_PERM.get(action.tool_name)
            if perm and not ctx.user.can(perm):
                yield _sse({"type": "error",
                            "message": "You are not authorised to execute this action."})
                return
            result = execute_action(ctx, action)
            action.status = "confirmed"
            yield _sse({"type": "action_executed", "tool_name": action.tool_name,
                        "result": result})
            ack = _ack_text(action.tool_name, result)
            note = (f"[SYSTEM] The user confirmed action '{action.tool_name}'; executed with "
                    f"result: {json.dumps(result, default=str)}.")

        # Acknowledge deterministically — no extra LLM round-trip, so confirmation is instant.
        # Still record the outcome in session history so later turns keep context.
        session.messages.append({"role": "user", "content": note})
        session.messages.append({"role": "assistant", "content": ack})
        yield _sse({"type": "assistant_text", "text": ack})
        yield _sse({"type": "done"})

    return StreamingResponse(gen(), media_type="text/event-stream")


def _ack_text(tool_name: str, result: dict) -> str:
    """Human-friendly confirmation, generated in code (no LLM call = instant)."""
    if tool_name == "create_escalation":
        eid = result.get("escalation_id", "")
        acct = result.get("account") or "the account"
        prio = result.get("priority", "normal")
        return (f"Done — escalation **{eid}** has been created for {acct} "
                f"({prio} priority). The team will pick it up from here.")
    if tool_name == "update_ticket":
        tid = result.get("ticket_id", "")
        bits = []
        if result.get("new_status"):
            bits.append(f"status set to {result['new_status']}")
        if result.get("comment"):
            bits.append("comment added")
        detail = "; ".join(bits) or "updated"
        return f"Done — ticket **{tid}** {detail}."
    if tool_name == "create_follow_up_task":
        tid = result.get("task_id", "")
        due = result.get("due_at", "")
        return f"Done — follow-up task **{tid}** created" + (f", due {due}." if due else ".")
    return "Done — the action has been completed."


def _token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    return authorization[7:] if authorization.lower().startswith("bearer ") else authorization


@app.get("/api")
def api_root():
    return {"service": "ParcelPilot Ops Copilot API", "docs": "/docs",
            "loaded": knowledge.loaded}


# Serve the built React app from FastAPI when present, so a single service hosts both the
# API and the UI (convenient for Render/Fly free tiers). In local dev, run Vite separately.
_DIST = (settings.data_dir.parent / "frontend" / "dist")
if _DIST.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="ui")
else:
    @app.get("/")
    def root():
        return {"service": "ParcelPilot Ops Copilot API", "ui": "not built",
                "hint": "run `npm run build` in frontend/, or use the Vite dev server"}
