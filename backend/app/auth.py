"""Mock authentication and role-based access control.

This models the *internal* ParcelPilot support/operations tool. Real auth is out of
scope for the assessment, so we mock a small set of staff users. What matters is that
authorization is a first-class concept the *tool layer* enforces (see tools/*), never
something we merely ask the model to respect.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# --- Permissions ------------------------------------------------------------
# Fine-grained capabilities. Tools check for these rather than checking role names,
# so the policy lives in one place and is easy to reason about.
class Perm:
    READ_DOCS = "read_docs"
    READ_DATA = "read_data"
    READ_PII = "read_pii"            # customer contact details / contract $ terms
    DETECT_ISSUES = "detect_issues"  # proactive ops view
    ACT_TICKET = "act_ticket"        # update / comment on tickets
    ACT_ESCALATE = "act_escalate"    # create escalations / follow-up tasks
    APPROVE_CREDIT = "approve_credit"  # authorise a service credit payout


@dataclass(frozen=True)
class User:
    id: str
    name: str
    role: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    # Max service-credit value (in account currency) this user may approve directly.
    # Anything larger must be escalated rather than actioned.
    credit_approval_limit: float = 0.0

    def can(self, perm: str) -> bool:
        return perm in self.permissions


_ALL_READ = {Perm.READ_DOCS, Perm.READ_DATA, Perm.DETECT_ISSUES}

# Mock staff directory keyed by an API token. In production this is your IdP/session.
USERS: dict[str, User] = {
    "token-analyst": User(
        id="u_analyst",
        name="Riya (Support Analyst)",
        role="support_analyst",
        # Read-only analyst: can see data and the ops view, but cannot change anything.
        permissions=frozenset(_ALL_READ),
        credit_approval_limit=0.0,
    ),
    "token-agent": User(
        id="u_agent",
        name="Marco (Support Agent)",
        role="support_agent",
        permissions=frozenset(_ALL_READ | {Perm.READ_PII, Perm.ACT_TICKET, Perm.ACT_ESCALATE}),
        # Can approve small good-will credits; larger ones must be escalated.
        credit_approval_limit=2000.0,
    ),
    "token-manager": User(
        id="u_manager",
        name="Dana (Ops Manager)",
        role="ops_manager",
        permissions=frozenset(
            _ALL_READ
            | {Perm.READ_PII, Perm.ACT_TICKET, Perm.ACT_ESCALATE, Perm.APPROVE_CREDIT}
        ),
        credit_approval_limit=25000.0,
    ),
}

DEFAULT_TOKEN = "token-agent"


def resolve_user(token: str | None) -> User:
    """Map an auth token to a staff user. Falls back to the default agent for demo ease."""
    return USERS.get(token or "", USERS[DEFAULT_TOKEN])


def public_directory() -> list[dict]:
    """Non-sensitive view of selectable demo users for the UI role switcher."""
    return [
        {
            "token": token,
            "name": u.name,
            "role": u.role,
            "permissions": sorted(u.permissions),
            "credit_approval_limit": u.credit_approval_limit,
        }
        for token, u in USERS.items()
    ]


class AccessDenied(Exception):
    """Raised by tools when the current user lacks a required permission."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
