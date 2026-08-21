"""FastAPI entrypoint: chat (SSE), action confirmation, status, and user directory."""
from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .agent.loop import AgentRunner
from .auth import Perm, public_directory, resolve_user
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
@app.get("/api/status")
def status():
    return knowledge.status()


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
            injected = (f"[SYSTEM] The user CANCELLED the prepared action "
                        f"'{action.tool_name}' ({action.summary}). Acknowledge and ask if "
                        f"they want to change anything.")
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
            injected = (f"[SYSTEM] The user CONFIRMED action '{action.tool_name}'. It has "
                        f"been executed with result: {json.dumps(result, default=str)}. "
                        f"Acknowledge briefly and continue if further steps remain.")

        runner = AgentRunner(ctx, session)
        async for event in runner.run(injected):
            yield _sse(event)

    return StreamingResponse(gen(), media_type="text/event-stream")


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
