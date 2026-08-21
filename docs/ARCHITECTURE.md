# Architecture Note

## Overview

ParcelPilot Ops Copilot is an **internal** support/operations agent. A React chat UI talks
to a FastAPI backend that runs a Claude tool-use loop over the supplied data pack. The loop
streams events (Server-Sent Events) so the UI can show which tool is running and render a
confirmation card before any state-changing action executes.

```
React UI ──POST /api/chat (SSE)──▶ FastAPI ──▶ AgentRunner (Claude tool-use loop)
   ▲  tool chips / confirm cards        │            │  chooses tools
   └──── event stream ◀─────────────────┘            ▼
                                          ┌───────── Tools (access-control enforced) ─────────┐
                                          │ search_documents   → BM25 over PDFs (authority)   │
                                          │ query_operational  → xlsx parameterised, PII-safe │
                                          │ compute            → deterministic math           │
                                          │ detect_issues      → proactive ops scan           │
                                          │ create_escalation / update_ticket / follow_up     │
                                          │        (prepare → confirm → execute)              │
                                          └───────────────────────────────────────────────────┘
```

## Agent design

- **Single agent, tool-use loop** (not a rigid pipeline). The model plans, calls a tool,
  observes the result, and repeats until it can answer — which is what makes genuine
  multi-step requests work (look up order → find account → read that account's contract →
  check SOP → compute → decide). Capped at 8 tool iterations per turn as a safety valve.
- **The system prompt encodes policy, not facts.** It carries the current user's role and
  permissions, the reference (snapshot) time, the source-authority precedence, and the rules
  for when to escalate rather than answer. Facts always come from tools; the model is told
  not to invent IDs, numbers, dates, or entitlements.
- **Sessions** hold the full Anthropic message history so context (and confirmations)
  persist across turns. In-memory for the demo; Redis/Postgres in production.

## Tool design

Nine tools in three categories, so the agent has a real choice to make:

1. **Document retrieval** — `search_documents`. BM25 (lexical), chosen over vector search
   because the corpus is tiny (~6 policy/contract PDFs) and the queries are keyword-heavy
   (account names, "cancellation fee", "service credit"). BM25 is deterministic, needs no
   embedding API, and is trivial to explain. Every result carries its source's **authority
   tier**; results are ranked by relevance blended with a small authority prior, and a
   customer's contract is only surfaced when the query is scoped to that customer.
2. **Structured lookup / calculation** — `list_data_tables`, `query_operational_data`,
   `compute`. Queries are **parameterised** (table + whitelisted filter operators), never
   raw SQL from the model, so the data layer stays in control of what can be read. `compute`
   does service-credit and duration math **in code** for determinism.
3. **State-changing actions** — `create_escalation`, `update_ticket`, `create_follow_up_task`.
   These never execute on the model's call; they *prepare* a proposal (see confirmation).

Plus `get_reference_time` and `detect_issues` (proactive ops view, Problem 1).

## Access control & privacy (enforced in the tool layer)

- Real enforcement lives in `tools/registry.py`, not the prompt. Each tool checks the
  caller's fine-grained permissions (`read_docs`, `read_data`, `read_pii`, `detect_issues`,
  `act_ticket`, `act_escalate`, `approve_credit`) and raises `AccessDenied` if missing. The
  model is *told* the rules but cannot bypass them.
- **PII/commercial redaction:** columns matching a sensitive-name pattern (email, phone,
  contact, contract value, rate card, …) are redacted for roles without `read_pii`. The
  agent is told to offer escalation rather than work around a redaction.
- **Role scoping:** a read-only analyst can browse data and the ops view but cannot prepare
  or execute any action; an agent can act up to a credit-approval limit; a manager can
  approve larger credits. Authorization is **re-checked at execution time** in `/api/confirm`,
  not only at prepare time.
- For a customer-facing variant the same layer would additionally pin every query to the
  authenticated `account_id`; that hook is where per-account isolation would live.

## Document & structured-data handling

- **PDFs** → text via `pypdf`, split into paragraph-sized chunks (<900 chars), indexed with
  BM25. Each chunk inherits document metadata: authority tier, status (active/deprecated),
  and customer scope (for contracts).
- **Workbook** → introspected adaptively (first non-empty row = header; remaining rows =
  records) so it works even if the exact column names differ from expectations. The **README
  sheet's snapshot time** is parsed and used as "now" for all time math (SLA age, cancellation
  cutoffs). A parameterised query API with typed operators (eq/neq/contains/gt/gte/lt/lte/in)
  sits on top.

## Source reliability & conflict handling (Client Problem 2)

The pack is deliberately imperfect, so **source authority is a first-class, machine-readable
property** (`ingest/registry.py`). Precedence, highest wins:

1. **Customer contract** (that customer only) — overrides general policy.
2. **Current SOP / current policy.**
3. **Product operations guide.**
4. **Deprecated policy** — context only; never the basis for an answer.
5. **Historical ticket resolutions** — context only; may be wrong.

Retrieval blends relevance with authority; deprecated sources are excluded by default and a
customer contract is scoped to its account. The system prompt instructs the agent to state
conflicts explicitly, name the governing source and why, escalate when it cannot resolve a
conflict or lacks data, and never treat a past ticket answer as authority. Example: TKT-5004's
historical note says "5% fee applies", which contradicts current Policy v3 (10%) and the
Northstar agreement (fee-free ≥2h before pickup) — the agent should follow the contract, not
the stale ticket.

## Confirmation before actions

Two-phase design. When the model calls a state-changing tool, `loop.py` intercepts it:
`prepare_action` builds a human-readable summary + payload, registers a `PendingAction`, and
emits a `confirmation_required` event — **nothing is written**. The UI renders a confirm card.
`POST /api/confirm` (approve/reject) is the *only* path that calls `execute_action`, which
commits to an audit log and injects the outcome back into the conversation so the agent can
acknowledge and continue any remaining steps.

## Major technical trade-offs

- **BM25 vs vector embeddings** — chose lexical for a tiny, keyword-heavy corpus: simpler,
  deterministic, no embedding cost. Upgrade path: hybrid dense+sparse once the corpus grows.
- **Parameterised queries vs text-to-SQL** — chose parameterised for enforceable access
  control and safety, trading some query flexibility.
- **In-memory sessions/actions** — fine for a single-process demo; not durable or horizontally
  scalable. Production: Redis/Postgres + a real task/escalation store.
- **Mocked auth & actions** — per the assessment. The permission model and prepare/execute
  split are real and would sit unchanged behind a real IdP and ticketing API.
- **Non-streaming model text** — tool events stream live; assistant text is emitted per block
  rather than token-by-token, to keep the loop simple. Token streaming is a small add.
- **Deterministic calc in code** — removes a class of arithmetic hallucinations at the cost of
  a few narrow tool operations rather than free-form reasoning.
