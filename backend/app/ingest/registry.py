"""Source-reliability metadata for the document pack.

The assessment is explicit that the corpus is *deliberately imperfect*: some docs are
deprecated, customer contracts override general policy, and historical tickets can be
wrong. We make source authority an explicit, machine-readable property so retrieval can
rank by trust and the agent can resolve conflicts deterministically instead of guessing.

Authority tiers (higher wins on conflict):
    50  customer_contract  - a specific customer's negotiated agreement. Overrides general
                             policy, but ONLY for that customer's account.
    40  current_sop        - current standard operating procedure (cancellations/credits).
    35  current_policy     - current general support policy.
    20  product_docs       - product operations guide / known issues.
    10  deprecated_policy  - superseded policy. Context only; never the basis for an answer.
     5  historical_ticket  - past resolutions. Context only; may be incorrect.
"""
from __future__ import annotations

from dataclasses import dataclass

AUTHORITY = {
    "customer_contract": 50,
    "current_sop": 40,
    "current_policy": 35,
    "product_docs": 20,
    "deprecated_policy": 10,
    "historical_ticket": 5,
}


@dataclass(frozen=True)
class DocMeta:
    doc_id: str
    title: str
    tier: str
    # For customer_contract docs: the account this contract governs. None = applies generally.
    customer_scope: str | None = None
    status: str = "active"  # active | deprecated
    note: str = ""

    @property
    def authority(self) -> int:
        return AUTHORITY.get(self.tier, 0)


# Keyed by the source filename (case-insensitive match on the stem). Any PDF not listed
# here is ingested with a conservative default tier so the system still works if the pack
# filenames differ slightly from the spec.
KNOWN_DOCS: dict[str, DocMeta] = {
    "01_support_policy_v3_current": DocMeta(
        "support_policy_v3", "Support Policy v3 (CURRENT)", "current_policy",
        note="Authoritative general support policy.",
    ),
    "02_support_policy_v2_deprecated": DocMeta(
        "support_policy_v2", "Support Policy v2 (DEPRECATED)", "deprecated_policy",
        status="deprecated",
        note="Superseded by v3. Use only to explain what changed; never as the basis for an answer.",
    ),
    "03_cancellation_and_service_credit_sop_v4": DocMeta(
        "cancel_credit_sop_v4", "Cancellation & Service Credit SOP v4", "current_sop",
        note="Current operating procedure for cancellations and service credits.",
    ),
    "04_product_operations_guide_and_known_issues": DocMeta(
        "product_ops_guide", "Product Operations Guide & Known Issues", "product_docs",
        note="Product behaviour and known issues.",
    ),
    "05_northstar_logistics_enterprise_agreement": DocMeta(
        "northstar_agreement", "Northstar Logistics Enterprise Agreement", "customer_contract",
        customer_scope="Northstar Logistics",
        note="Overrides general policy for Northstar Logistics only.",
    ),
    "06_lumenworks_service_agreement": DocMeta(
        "lumenworks_agreement", "LumenWorks Service Agreement", "customer_contract",
        customer_scope="LumenWorks",
        note="Overrides general policy for LumenWorks only.",
    ),
}


def meta_for_filename(stem: str) -> DocMeta:
    key = stem.strip().lower()
    if key in KNOWN_DOCS:
        return KNOWN_DOCS[key]
    # Heuristic fallbacks so an unexpected filename still gets sensible metadata.
    low = key
    if "deprecated" in low:
        tier = "deprecated_policy"
    elif "sop" in low or "credit" in low or "cancellation" in low:
        tier = "current_sop"
    elif "agreement" in low or "contract" in low:
        tier = "customer_contract"
    elif "product" in low or "known_issues" in low:
        tier = "product_docs"
    else:
        tier = "current_policy"
    return DocMeta(key, stem.replace("_", " ").title(), tier,
                   status="deprecated" if tier == "deprecated_policy" else "active",
                   note="Metadata inferred from filename.")
