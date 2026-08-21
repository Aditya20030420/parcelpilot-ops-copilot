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
    # "staff" = internal ParcelPilot user (may see all accounts, subject to permissions).
    # "customer" = an external customer, hard-scoped to their own account_id.
    kind: str = "staff"
    account_id: str | None = None
    account_name: str | None = None

    def can(self, perm: str) -> bool:
        return perm in self.permissions

    @property
    def is_customer(self) -> bool:
        return self.kind == "customer"


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
    # --- Customers (external). Each is hard-scoped to their own account. They can read
    # their own data + their agreement + general policy, and raise an escalation to a human.
    # They can never see other accounts, internal ops views, or take internal actions.
    "token-cust-northstar": User(
        id="cust_northstar", name="Northstar Logistics (customer)", role="customer",
        kind="customer", account_id="ACCT-001", account_name="Northstar Logistics",
        permissions=frozenset({Perm.READ_DOCS, Perm.READ_DATA, Perm.READ_PII, Perm.ACT_ESCALATE}),
    ),
    "token-cust-lumenworks": User(
        id="cust_lumenworks", name="LumenWorks (customer)", role="customer",
        kind="customer", account_id="ACCT-002", account_name="LumenWorks",
        permissions=frozenset({Perm.READ_DOCS, Perm.READ_DATA, Perm.READ_PII, Perm.ACT_ESCALATE}),
    ),
    "token-cust-beacon": User(
        id="cust_beacon", name="Beacon Retail (customer)", role="customer",
        kind="customer", account_id="ACCT-003", account_name="Beacon Retail",
        permissions=frozenset({Perm.READ_DOCS, Perm.READ_DATA, Perm.READ_PII, Perm.ACT_ESCALATE}),
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
            "kind": u.kind,
            "account_id": u.account_id,
            "account_name": u.account_name,
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
