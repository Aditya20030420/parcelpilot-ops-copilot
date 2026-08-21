"""In-memory session + pending-action store.

For a demo this is a process-local dict. Production would use Redis/Postgres so sessions
survive restarts and scale horizontally (noted in the architecture note).
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PendingAction:
    """A prepared state-changing action awaiting explicit user confirmation."""
    action_id: str
    session_id: str
    tool_name: str
    summary: str            # human-readable description shown in the confirm card
    payload: dict           # the fields that will be written on confirmation
    created_by: str         # user id that prepared it
    created_at: dt.datetime = field(default_factory=dt.datetime.utcnow)
    status: str = "pending"  # pending | confirmed | cancelled | expired


@dataclass
class Session:
    session_id: str
    # Anthropic-format message history (role/content blocks).
    messages: list[dict] = field(default_factory=list)
    created_at: dt.datetime = field(default_factory=dt.datetime.utcnow)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._pending: dict[str, PendingAction] = {}
        # Mock "database" of side effects the action tools have committed.
        self.audit_log: list[dict] = []

    def get_or_create(self, session_id: str | None) -> Session:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        sid = session_id or uuid.uuid4().hex
        s = Session(session_id=sid)
        self._sessions[sid] = s
        return s

    def add_pending(self, action: PendingAction) -> None:
        self._pending[action.action_id] = action

    def get_pending(self, action_id: str) -> PendingAction | None:
        return self._pending.get(action_id)

    def record_commit(self, entry: dict) -> None:
        entry = {**entry, "committed_at": dt.datetime.utcnow().isoformat()}
        self.audit_log.append(entry)


store = SessionStore()
