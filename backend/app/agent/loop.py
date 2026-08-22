"""The agent loop: OpenAI function-calling with live event emission for the UI.

Emits a stream of events so the interface can show which tool is running and render the
confirmation card for state-changing actions. State-changing tools are intercepted here:
they are *prepared* (never executed) and surfaced for explicit user confirmation.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from openai import OpenAI

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
from .schemas import to_openai_tools

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to backend/.env before chatting."
            )
        kwargs = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        _client = OpenAI(**kwargs)
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

    async def _create(self, system: dict, tools: list[dict]):
        """Call the model, retrying briefly on transient rate limits (free-tier friendly)."""
        from openai import RateLimitError

        attempts = 3
        for i in range(attempts):
            try:
                return await asyncio.to_thread(
                    _get_client().chat.completions.create,
                    model=settings.model,
                    max_tokens=settings.max_tokens,
                    messages=[system, *self.session.messages],
                    tools=tools,
                    tool_choice="auto",
                )
            except RateLimitError as e:
                wait = _retry_after(e)
                if i == attempts - 1 or wait > 20:
                    raise _RateLimited(wait) from e
                await asyncio.sleep(wait)
        raise _RateLimited(0)

    async def run(self, injected_user_content: str) -> AsyncIterator[dict]:
        """Append a user turn and drive the tool-calling loop to completion."""
        self.session.messages.append({"role": "user", "content": injected_user_content})
        system = {"role": "system", "content": build_system_prompt(self.ctx)}
        tools = to_openai_tools()

        max_iters = 8
        for _ in range(max_iters):
            try:
                resp = await self._create(system, tools)
            except _RateLimited as e:
                yield {"type": "error", "message": (
                    "The model is rate-limited (free-tier quota). Please wait "
                    f"~{e.retry_after}s and try again.")}
                return
            except Exception as e:  # noqa: BLE001
                yield {"type": "error", "message": f"Model call failed: {e}"}
                return

            msg = resp.choices[0].message
            tool_calls = msg.tool_calls or []

            # Persist the assistant turn in a re-sendable shape.
            assistant_entry: dict = {"role": "assistant", "content": msg.content or ""}
            if tool_calls:
                assistant_entry["tool_calls"] = [_serialise_tool_call(tc) for tc in tool_calls]
            self.session.messages.append(assistant_entry)

            if msg.content and msg.content.strip():
                yield {"type": "assistant_text", "text": msg.content}

            if not tool_calls:
                yield {"type": "done"}
                return

            paused_for_confirmation = False
            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield {"type": "tool_call", "name": name, "args": args}

                if is_state_changing(name):
                    try:
                        pending = prepare_action(self.ctx, name, args)
                    except AccessDenied as e:
                        self.session.messages.append(
                            _tool_msg(tc.id, {"error": "access_denied", "message": e.message}))
                        yield {"type": "tool_result", "name": name, "summary": "access denied"}
                        continue
                    self.ctx.store.add_pending(pending)
                    yield {
                        "type": "confirmation_required",
                        "action_id": pending.action_id,
                        "tool_name": name,
                        "summary": pending.summary,
                        "payload": pending.payload,
                    }
                    self.session.messages.append(_tool_msg(tc.id, {
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
                    # Surface document citations to the UI so answers show their sources.
                    if name == "search_documents" and isinstance(result, dict):
                        items = [
                            {"source": r.get("source"), "page": r.get("page"),
                             "tier": r.get("tier"), "authority": r.get("authority")}
                            for r in (result.get("results") or [])[:3]
                        ]
                        if items:
                            yield {"type": "sources", "items": items}
                    self.session.messages.append(_tool_msg(tc.id, result))

            # After preparing an action, let the model produce its closing summary, then it
            # will stop (it's instructed not to re-call the tool).
            if paused_for_confirmation:
                continue

        yield {"type": "assistant_text",
               "text": "I've reached the step limit for this turn. Could you narrow the request?"}
        yield {"type": "done"}


class _RateLimited(Exception):
    def __init__(self, retry_after: float):
        self.retry_after = round(retry_after) or 30
        super().__init__(f"rate limited, retry after {self.retry_after}s")


def _retry_after(err) -> float:
    """Best-effort parse of the provider's suggested retry delay (seconds)."""
    import re

    msg = str(getattr(err, "message", "") or err)
    m = re.search(r"retry in ([\d.]+)s|retryDelay['\":\s]+([\d.]+)s", msg, re.I)
    if m:
        return float(m.group(1) or m.group(2))
    return 8.0


def _serialise_tool_call(tc) -> dict:
    """Re-sendable tool-call dict. Preserves provider extras like Gemini's
    `thought_signature` (carried in `extra_content`), which Gemini 3 thinking models
    require to be echoed back on the next request when using tools."""
    d = {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
    }
    extra = getattr(tc, "model_extra", None) or {}
    if extra.get("extra_content"):
        d["extra_content"] = extra["extra_content"]
    return d


def _tool_msg(tool_call_id: str, content: dict) -> dict:
    return {"role": "tool", "tool_call_id": tool_call_id,
            "content": json.dumps(content, default=str)}
