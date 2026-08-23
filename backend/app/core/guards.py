"""Safety guardrails: prompt-injection detection and ID validation.

The assessment's sources are deliberately imperfect and, in general, retrieved documents
and customer-authored ticket text are UNTRUSTED — they could contain text that tries to
steer the model ("ignore previous instructions…"). We treat all retrieved content as data,
never instructions, and additionally flag obvious injection attempts so the UI can show them.

We also validate that any order/ticket/account ID the agent states actually exists in the
data, to catch hallucinated identifiers.
"""
from __future__ import annotations

import re

# Phrases that indicate an attempt to hijack the model's behaviour if they appear *inside
# retrieved content*. This is a heuristic tripwire, not a complete filter — the real defence
# is the system prompt instructing the model to treat tool output as data.
_INJECTION = re.compile(
    r"ignore\s+(?:all|any|the|your|previous|prior|above)\s+(?:instructions|prompts|rules)"
    r"|disregard\s+(?:the|all|any|previous|prior|your)"
    r"|forget\s+(?:the|all|your|previous)\s+(?:instructions|prompt)"
    r"|you\s+are\s+now\b"
    r"|new\s+instructions?\s*:"
    r"|system\s+prompt"
    r"|reveal\s+(?:your\s+)?(?:system\s+)?prompt"
    r"|do\s+not\s+follow\s+(?:the|your|any)"
    r"|act\s+as\s+(?:a|an|the)\b"
    r"|override\s+(?:the|your|all)",
    re.IGNORECASE,
)


def detect_injection(text: str) -> bool:
    """True if the text looks like it contains an instruction-injection attempt."""
    return bool(text) and bool(_INJECTION.search(text))


# Identifiers that come from the data (not the ESC-/TASK- ids we generate ourselves).
_DATA_ID = re.compile(r"\b(?:ORD|TKT|ACCT|ACC)-[A-Za-z0-9]+\b")


def find_data_ids(text: str) -> list[str]:
    """Order/ticket/account-style IDs mentioned in a piece of text, de-duplicated in order."""
    return list(dict.fromkeys(_DATA_ID.findall(text or "")))


def unknown_ids(text: str, known: set[str]) -> list[str]:
    """IDs referenced in text that are NOT present in the known-ID set (likely hallucinated)."""
    return [i for i in find_data_ids(text) if i not in known]
