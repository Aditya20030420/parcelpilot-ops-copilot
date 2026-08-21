"""Anthropic tool schemas exposed to the model."""
from __future__ import annotations

_FILTER_ITEM = {
    "type": "object",
    "properties": {
        "column": {"type": "string", "description": "Column name from the table schema."},
        "op": {"type": "string",
               "enum": ["eq", "neq", "contains", "gt", "gte", "lt", "lte", "in"],
               "default": "eq"},
        "value": {"description": "Value to compare against (string/number, or array for 'in')."},
    },
    "required": ["column", "value"],
}

def to_openai_tools() -> list[dict]:
    """Convert the tool schemas to OpenAI chat-completions 'function' format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOL_SCHEMAS
    ]


TOOL_SCHEMAS = [
    {
        "name": "search_documents",
        "description": (
            "Search policies, SOPs, product docs, and customer agreements. Returns excerpts "
            "with source authority metadata. Pass `customer` when the question is about a "
            "specific account so their contract is scoped in. Deprecated docs are excluded "
            "unless include_deprecated=true."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "customer": {"type": "string", "description": "Account/customer name, if known."},
                "include_deprecated": {"type": "boolean", "default": False},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_data_tables",
        "description": "List the operational data tables (accounts, orders, tickets) and their columns. Call this before querying if unsure of the schema.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "query_operational_data",
        "description": (
            "Query a structured table (accounts/orders/tickets) with parameterised filters. "
            "PII columns are redacted if your role lacks access."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "filters": {"type": "array", "items": _FILTER_ITEM},
                "columns": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "default": 25},
            },
            "required": ["table"],
        },
    },
    {
        "name": "get_reference_time",
        "description": "Get the dataset snapshot time to use as 'now' for all time-based reasoning.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "compute",
        "description": ("Deterministic calculations. operation='service_credit' (needs "
                        "order_value, credit_percentage) or 'hours_between' (needs ISO "
                        "start_time, end_time)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["service_credit", "hours_between"]},
                "order_value": {"type": "number"},
                "credit_percentage": {"type": "number"},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
            },
            "required": ["operation"],
        },
    },
    {
        "name": "detect_issues",
        "description": ("Proactive scan of ticket data for SLA breaches, clustered/repeated "
                        "issues, and accounts under pressure. For authorised ops users."),
        "input_schema": {
            "type": "object",
            "properties": {
                "focus": {"type": "string"},
                "sla_hours": {"type": "number", "default": 24},
            },
        },
    },
    # --- state-changing (require confirmation) ---
    {
        "name": "create_escalation",
        "description": ("Prepare an escalation to the human support team. Does NOT execute — "
                        "it stages the escalation for the user to confirm. Use when the request "
                        "needs human judgment, an unsupported exception, or exceeds your authority."),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "account": {"type": "string"},
                "reason": {"type": "string"},
                "requested_outcome": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"],
                             "default": "normal"},
            },
            "required": ["reason", "requested_outcome"],
        },
    },
    {
        "name": "update_ticket",
        "description": "Prepare a ticket update (status change and/or comment). Requires confirmation before it is applied.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "new_status": {"type": "string"},
                "comment": {"type": "string"},
            },
            "required": ["ticket_id"],
        },
    },
    {
        "name": "create_follow_up_task",
        "description": "Prepare a follow-up task for the ops team. Requires confirmation before it is created.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "due_in_hours": {"type": "number"},
                "account": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["title", "due_in_hours"],
        },
    },
]
