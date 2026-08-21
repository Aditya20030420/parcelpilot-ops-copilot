"""Tool definitions, access-control enforcement, and dispatch.

Two kinds of tools:
  * READ tools run immediately and return data.
  * STATE-CHANGING tools never execute on the model's say-so. They `prepare` a proposal
    (summary + payload) that is registered as a PendingAction and surfaced to the user for
    explicit confirmation. Only /api/confirm calls `execute`.

Every tool checks the caller's permissions here, in the tool layer. The model is *told*
about the rules in its prompt, but it cannot bypass them because the enforcement is the
code below, not the instructions.
"""
from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Any, Callable

from ..auth import AccessDenied, Perm
from ..core.session import PendingAction
from .context import ToolContext

# Column-name patterns considered PII / commercially sensitive. Redacted for users
# lacking READ_PII.
_PII_PATTERNS = re.compile(
    r"email|phone|mobile|contact|address|ssn|tax|billing|card|iban|account_no|"
    r"contract_value|rate_card|price|discount",
    re.I,
)


def _require(ctx: ToolContext, perm: str, action: str) -> None:
    if not ctx.user.can(perm):
        raise AccessDenied(
            f"User '{ctx.user.name}' (role={ctx.user.role}) is not authorised to {action}."
        )


def _redact_rows(rows: list[dict], allow_pii: bool) -> tuple[list[dict], list[str]]:
    if allow_pii:
        return rows, []
    redacted_cols: set[str] = set()
    out = []
    for r in rows:
        nr = {}
        for k, v in r.items():
            if v not in (None, "") and _PII_PATTERNS.search(str(k)):
                nr[k] = "[redacted]"
                redacted_cols.add(k)
            else:
                nr[k] = v
        out.append(nr)
    return out, sorted(redacted_cols)


# ---------------------------------------------------------------------------
# READ TOOLS
# ---------------------------------------------------------------------------
def tool_search_documents(ctx: ToolContext, query: str, customer: str | None = None,
                          include_deprecated: bool = False, top_k: int = 5) -> dict:
    _require(ctx, Perm.READ_DOCS, "search documents")
    hits = ctx.knowledge.docs.search(
        query, top_k=top_k, customer=customer, include_deprecated=include_deprecated
    )
    return {
        "query": query,
        "customer_scope": customer,
        "results": [
            {
                "source": h.chunk.title,
                "doc_id": h.chunk.doc_id,
                "tier": h.chunk.tier,
                "authority": h.chunk.authority,
                "status": h.chunk.status,
                "applies_to_customer": h.chunk.customer_scope,
                "page": h.chunk.page,
                "excerpt": h.chunk.text,
                "relevance": round(h.score, 3),
            }
            for h in hits
        ],
        "guidance": (
            "Higher 'authority' = more trustworthy on conflict. A customer_contract "
            "overrides general policy for that customer only. 'deprecated' sources are "
            "context only; do not base answers on them."
        ),
    }


def tool_list_data_tables(ctx: ToolContext) -> dict:
    _require(ctx, Perm.READ_DATA, "read operational data")
    return {"tables": ctx.knowledge.data.list_tables(),
            "snapshot_time": ctx.knowledge.snapshot_time.isoformat()}


def tool_query_operational_data(ctx: ToolContext, table: str,
                                filters: list[dict] | None = None,
                                columns: list[str] | None = None,
                                limit: int = 25) -> dict:
    _require(ctx, Perm.READ_DATA, "read operational data")
    res = ctx.knowledge.data.query_table(table, filters=filters, columns=columns, limit=limit)
    if "rows" in res:
        rows, redacted = _redact_rows(res["rows"], allow_pii=ctx.user.can(Perm.READ_PII))
        res["rows"] = rows
        if redacted:
            res["redacted_columns"] = redacted
            res["note"] = ("Some columns are hidden because your role lacks PII access. "
                           "Escalate to a manager if the customer's request requires them.")
    return res


def tool_get_reference_time(ctx: ToolContext) -> dict:
    return {
        "reference_time": ctx.knowledge.snapshot_time.isoformat(),
        "note": "Use this as 'now' for all time-based reasoning (SLA breaches, cutoffs, etc.).",
    }


def tool_compute(ctx: ToolContext, operation: str,
                 order_value: float | None = None,
                 credit_percentage: float | None = None,
                 start_time: str | None = None,
                 end_time: str | None = None) -> dict:
    """Deterministic calculations done in code, not by the model.

    operation:
      - 'service_credit': amount = order_value * credit_percentage / 100, with a check
        against the caller's approval limit.
      - 'hours_between': whole/fractional hours between two ISO timestamps.
    """
    _require(ctx, Perm.READ_DATA, "run calculations")
    if operation == "service_credit":
        if order_value is None or credit_percentage is None:
            return {"error": "service_credit needs order_value and credit_percentage."}
        amount = round(order_value * credit_percentage / 100.0, 2)
        limit = ctx.user.credit_approval_limit
        return {
            "operation": operation,
            "order_value": order_value,
            "credit_percentage": credit_percentage,
            "credit_amount": amount,
            "your_approval_limit": limit,
            "requires_higher_approval": amount > limit,
            "note": ("This credit exceeds your approval limit — prepare an escalation for "
                     "manager approval rather than actioning it." if amount > limit
                     else "Within your approval limit."),
        }
    if operation == "hours_between":
        a, b = _to_dt(start_time), _to_dt(end_time)
        if not a or not b:
            return {"error": "hours_between needs valid ISO start_time and end_time."}
        hours = round((b - a).total_seconds() / 3600.0, 2)
        return {"operation": operation, "start_time": start_time, "end_time": end_time,
                "hours": hours}
    return {"error": f"Unknown operation '{operation}'."}


def _to_dt(v: str | None) -> dt.datetime | None:
    if not v:
        return None
    try:
        return dt.datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(v, fmt)
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# PROACTIVE ISSUE DETECTION  (Client Problem 1)
# ---------------------------------------------------------------------------
def tool_detect_issues(ctx: ToolContext, focus: str | None = None,
                       sla_hours: float = 24.0) -> dict:
    """Scan ticket data for patterns worth attention: SLA risk, clustered complaints,
    repeated product issues. Heuristic and schema-adaptive — it inspects whatever ticket
    table exists in the workbook."""
    _require(ctx, Perm.DETECT_ISSUES, "view the proactive operations dashboard")
    data = ctx.knowledge.data
    now = ctx.knowledge.snapshot_time
    ticket_tbl = None
    for t in data.list_tables():
        if re.search(r"ticket|support|case|issue", t["table"], re.I):
            ticket_tbl = t
            break
    if ticket_tbl is None:
        return {"error": "No ticket-like table found in the workbook."}

    tbl = data.resolve_table(ticket_tbl["table"])
    assert tbl is not None
    cols = {c.lower(): c for c in tbl.columns}

    def col(*names: str) -> str | None:
        for n in names:
            for lc, orig in cols.items():
                if n in lc:
                    return orig
        return None

    c_status = col("status", "state")
    c_sev = col("severity", "priority")
    c_created = col("created", "opened", "date")
    c_sla = col("sla")
    c_category = col("category", "type", "issue", "subject", "topic")
    c_account = col("account", "customer", "client")
    c_id = col("ticket_id", "ticket", "id", "case")

    findings: list[dict] = []
    open_rows = [r for r in tbl.rows
                 if not (c_status and re.search(r"closed|resolved|done", str(r.get(c_status, "")), re.I))]

    # 1) SLA breach / at-risk.
    if c_created:
        breaching = []
        for r in open_rows:
            created = _to_dt(str(r.get(c_created))) if r.get(c_created) else None
            if not created:
                continue
            age_h = (now - created).total_seconds() / 3600.0
            limit = _num_or(r.get(c_sla), sla_hours) if c_sla else sla_hours
            if age_h >= limit:
                breaching.append({"ticket": r.get(c_id), "account": r.get(c_account),
                                  "age_hours": round(age_h, 1), "sla_hours": limit,
                                  "severity": r.get(c_sev)})
        if breaching:
            breaching.sort(key=lambda x: x["age_hours"], reverse=True)
            findings.append({
                "type": "sla_breach",
                "priority": "high",
                "title": f"{len(breaching)} open ticket(s) at or past SLA",
                "detail": breaching[:10],
            })

    # 2) Clusters by category (possible systemic issue).
    if c_category:
        counts: dict[str, list] = {}
        for r in open_rows:
            key = str(r.get(c_category) or "unknown").strip().lower()
            counts.setdefault(key, []).append(r.get(c_id))
        clusters = [{"category": k, "count": len(v), "tickets": v[:10]}
                    for k, v in counts.items() if len(v) >= 3 and k != "unknown"]
        clusters.sort(key=lambda x: x["count"], reverse=True)
        if clusters:
            findings.append({
                "type": "issue_cluster", "priority": "medium",
                "title": "Repeated issue categories across open tickets",
                "detail": clusters[:8],
            })

    # 3) Accounts with multiple open tickets (possible escalating relationship).
    if c_account:
        by_acct: dict[str, int] = {}
        for r in open_rows:
            by_acct[str(r.get(c_account))] = by_acct.get(str(r.get(c_account)), 0) + 1
        hot = sorted(({"account": k, "open_tickets": v} for k, v in by_acct.items() if v >= 3),
                     key=lambda x: x["open_tickets"], reverse=True)
        if hot:
            findings.append({
                "type": "account_pressure", "priority": "medium",
                "title": "Accounts with several open tickets", "detail": hot[:8],
            })

    return {
        "reference_time": now.isoformat(),
        "ticket_table": ticket_tbl["table"],
        "open_tickets": len(open_rows),
        "findings": findings or [{"type": "none", "priority": "info",
                                  "title": "No notable patterns detected."}],
    }


def _num_or(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# STATE-CHANGING TOOLS  (prepare -> confirm -> execute)
# ---------------------------------------------------------------------------
def prepare_create_escalation(ctx: ToolContext, reason: str, requested_outcome: str,
                              ticket_id: str | None = None, account: str | None = None,
                              priority: str = "normal") -> tuple[str, dict]:
    _require(ctx, Perm.ACT_ESCALATE, "create escalations")
    payload = {
        "ticket_id": ticket_id, "account": account, "reason": reason,
        "requested_outcome": requested_outcome, "priority": priority,
        "raised_by": ctx.user.name,
    }
    summary = (f"Escalate {ticket_id or '(no ticket)'} for {account or 'account'} "
               f"[{priority}] — {requested_outcome}")
    return summary, payload


def execute_create_escalation(ctx: ToolContext, payload: dict) -> dict:
    esc_id = f"ESC-{uuid.uuid4().hex[:6].upper()}"
    record = {"kind": "escalation", "escalation_id": esc_id, **payload}
    ctx.store.record_commit(record)
    return {"status": "created", "escalation_id": esc_id, **payload}


def prepare_update_ticket(ctx: ToolContext, ticket_id: str, new_status: str | None = None,
                          comment: str | None = None) -> tuple[str, dict]:
    _require(ctx, Perm.ACT_TICKET, "update tickets")
    payload = {"ticket_id": ticket_id, "new_status": new_status, "comment": comment,
               "updated_by": ctx.user.name}
    bits = [f"status→{new_status}"] if new_status else []
    if comment:
        bits.append(f'comment "{comment[:60]}"')
    summary = f"Update {ticket_id}: " + ", ".join(bits or ["(no changes)"])
    return summary, payload


def execute_update_ticket(ctx: ToolContext, payload: dict) -> dict:
    record = {"kind": "ticket_update", **payload}
    ctx.store.record_commit(record)
    return {"status": "updated", **payload}


def prepare_create_follow_up(ctx: ToolContext, title: str, due_in_hours: float,
                             account: str | None = None, notes: str | None = None) -> tuple[str, dict]:
    _require(ctx, Perm.ACT_ESCALATE, "create follow-up tasks")
    due = (ctx.knowledge.snapshot_time + dt.timedelta(hours=due_in_hours)).isoformat()
    payload = {"title": title, "due_at": due, "account": account, "notes": notes,
               "owner": ctx.user.name}
    summary = f'Follow-up task "{title}" due {due} for {account or "—"}'
    return summary, payload


def execute_create_follow_up(ctx: ToolContext, payload: dict) -> dict:
    task_id = f"TASK-{uuid.uuid4().hex[:6].upper()}"
    record = {"kind": "follow_up_task", "task_id": task_id, **payload}
    ctx.store.record_commit(record)
    return {"status": "created", "task_id": task_id, **payload}


# ---------------------------------------------------------------------------
# Registry metadata (schemas the model sees + dispatch)
# ---------------------------------------------------------------------------
READ_TOOLS: dict[str, Callable] = {
    "search_documents": tool_search_documents,
    "list_data_tables": tool_list_data_tables,
    "query_operational_data": tool_query_operational_data,
    "get_reference_time": tool_get_reference_time,
    "compute": tool_compute,
    "detect_issues": tool_detect_issues,
}

STATE_CHANGING: dict[str, dict[str, Callable]] = {
    "create_escalation": {"prepare": prepare_create_escalation, "execute": execute_create_escalation},
    "update_ticket": {"prepare": prepare_update_ticket, "execute": execute_update_ticket},
    "create_follow_up_task": {"prepare": prepare_create_follow_up, "execute": execute_create_follow_up},
}


def is_state_changing(name: str) -> bool:
    return name in STATE_CHANGING


def dispatch_read(ctx: ToolContext, name: str, args: dict) -> dict:
    fn = READ_TOOLS.get(name)
    if fn is None:
        return {"error": f"Unknown read tool '{name}'."}
    try:
        return fn(ctx, **args)
    except AccessDenied as e:
        return {"error": "access_denied", "message": e.message}
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}


def prepare_action(ctx: ToolContext, name: str, args: dict) -> PendingAction:
    spec = STATE_CHANGING[name]
    summary, payload = spec["prepare"](ctx, **args)
    return PendingAction(
        action_id=f"act_{uuid.uuid4().hex[:10]}",
        session_id=ctx.session_id,
        tool_name=name,
        summary=summary,
        payload=payload,
        created_by=ctx.user.id,
    )


def execute_action(ctx: ToolContext, action: PendingAction) -> dict:
    spec = STATE_CHANGING[action.tool_name]
    return spec["execute"](ctx, action.payload)
