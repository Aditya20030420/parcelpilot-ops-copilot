"""Per-request context passed to every tool: who is calling and in what session."""
from __future__ import annotations

from dataclasses import dataclass

from ..auth import User
from ..core.knowledge import Knowledge
from ..core.session import SessionStore


@dataclass
class ToolContext:
    user: User
    session_id: str
    knowledge: Knowledge
    store: SessionStore
