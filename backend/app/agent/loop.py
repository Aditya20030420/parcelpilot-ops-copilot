"""The agent loop: Claude tool-use with live event emission for the UI.

Emits a stream of events so the interface can show which tool is running and render the
confirmation card for state-changing actions. State-changing tools are intercepted here:
they are *prepared* (never executed) and surfaced for explicit user confirmation.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from anthropic import Anthropic

from ..auth import AccessDenied
from ..config import settings
from ..core.session import Session
from ..tools.context import ToolContext
from ..tools.registry import (
    dispatch_read,
    is_state_changing,
    prepare_action,
)
from .prompts import build_system_prompt
from .schemas import TOOL_SCHEMAS

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to backend/.env before chatting."
            )
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _summarise_result(name: str, result: dict) -> str:
    if not isinstance(result, dict):
        return str(result)[:200]
    if result.get("error"):
        return f"{result.get('error')}: {result.get('message', '')}".strip(": ")
    if name == "search_documents":
        return f"{len(result.get('results', []))} passage(s)"
    if name == "query_operational_data":
        return f"{result.get('matched', 0)} row(s) matched"
    if name == "detect_issues":
        return f"{len(result.get('findings', []))} finding(s)"
    if name == "list_data_tables":
        return f"{len(result.get('tables', []))} table(s)"
    return "ok"


class AgentRunner:
    def __init__(self, ctx: ToolContext, session: Session) -> None:
        self.ctx = ctx
        self.session = session

    async def run(self, injected_user_content) -> AsyncIterator[dict]:
        """Append a user turn (str or content blocks) and drive the loop to completion."""
        self.session.messages.append({"role": "user", "content": injected_user_content})
        system = build_system_prompt(self.ctx)

        max_iters = 8
        for _ in range(max_iters):
            try:
                resp = await asyncio.to_thread(
                    _get_client().messages.create,
                    model=settings.model,
                    max_tokens=settings.max_tokens,
                    system=system,
                    tools=TOOL_SCHEMAS,
                    messages=self.session.messages,
                )
            except Exception as e:  # noqa: BLE001
                yield {"type": "error", "message": f"Model call failed: {e}"}
                return

            assistant_blocks = [b.model_dump() for b in resp.content]
            self.session.messages.append({"role": "assistant", "content": assistant_blocks})

            # Emit any assistant text.
            for b in assistant_blocks:
                if b.get("type") == "text" and b.get("text", "").strip():
                    yield {"type": "assistant_text", "text": b["text"]}

            if resp.stop_reason != "tool_use":
                yield {"type": "done"}
                return

            tool_uses = [b for b in assistant_blocks if b.get("type") == "tool_use"]
            tool_results = []
            paused_for_confirmation = False

            for tu in tool_uses:
                name, args, tid = tu["name"], tu.get("input", {}) or {}, tu["id"]
                yield {"type": "tool_call", "name": name, "args": args}

                if is_state_changing(name):
                    try:
                        pending = prepare_action(self.ctx, name, args)
                    except AccessDenied as e:
                        tool_results.append(_tr(tid, {"error": "access_denied",
                                                      "message": e.message}))
                        yield {"type": "tool_result", "name": name,
                               "summary": "access denied"}
                        continue
                    self.ctx.store.add_pending(pending)
                    yield {
                        "type": "confirmation_required",
                        "action_id": pending.action_id,
                        "tool_name": name,
                        "summary": pending.summary,
                        "payload": pending.payload,
                    }
                    tool_results.append(_tr(tid, {
                        "status": "prepared_awaiting_confirmation",
                        "action_id": pending.action_id,
                        "summary": pending.summary,
                        "instruction": ("Tell the user what you prepared and that it awaits "
                                        "their confirmation. Do not call this tool again."),
                    }))
                    paused_for_confirmation = True
                else:
                    result = dispatch_read(self.ctx, name, args)
                    yield {"type": "tool_result", "name": name,
                           "summary": _summarise_result(name, result)}
                    tool_results.append(_tr(tid, result))

            self.session.messages.append({"role": "user", "content": tool_results})

            # Let the model produce its closing summary after preparing an action,
            # then it will stop (it's instructed not to re-call the tool).
            if paused_for_confirmation:
                continue

        # Safety valve if the model loops.
        yield {"type": "assistant_text",
               "text": "I've reached the step limit for this turn. Could you narrow the request?"}
        yield {"type": "done"}


def _tr(tool_use_id: str, content: dict) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(content, default=str),
    }
