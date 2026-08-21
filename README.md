# ParcelPilot Ops Copilot

An internal **support & operations** AI agent for ParcelPilot (B2B logistics). Authorised
staff ask natural-language questions about policies, customer contracts, orders, tickets,
and SLAs; the agent retrieves and reasons over the supplied data pack, runs calculations,
proactively surfaces urgent/unusual issues, and takes actions (escalations, ticket updates,
follow-up tasks) — always behind an explicit confirmation step.

Built for the CalQuity AI Engineer first-round assessment.

> **Chosen context:** the internal ops/support chatbot (one of the two allowed options).
> This also lets it address **Client Problem 1 — Proactive Issue Detection** natively.
> **Client Problem 2 — Trust & Reliability** is addressed throughout via explicit source
> authority, conflict resolution, and escalation-on-uncertainty (see `docs/ARCHITECTURE.md`).

---

## What it does (maps to the minimum requirements)

| Requirement | Where |
| --- | --- |
| 1. Chatbot over natural language, source-aware | `backend/app/agent/*`, BM25 retrieval in `ingest/documents.py` |
| 2. Access control **enforced in the tool layer** | `auth.py` + permission checks in `tools/registry.py` |
| 3. ≥3 distinct tools (doc search, structured lookup/calc, state-changing action) | `tools/registry.py`, `agent/schemas.py` |
| 4. Confirmation before any action | two-phase prepare→confirm in `loop.py` + `/api/confirm` |
| 5. Multi-step requests | agent loop iterates tools until done |
| 6. Chat UI showing the active tool | `frontend/src/App.jsx` tool chips |
| 7. Demo video | see submission |

The agent has **six read tools** and **three state-changing tools**:

- `search_documents` — BM25 retrieval over PDFs, ranked by **source authority**; scopes
  customer contracts to the right account.
- `list_data_tables`, `query_operational_data` — parameterised, role-scoped structured
  queries with **PII redaction**.
- `compute` — deterministic service-credit / duration math (done in code, not the model).
- `get_reference_time` — the dataset snapshot time used as "now".
- `detect_issues` — proactive scan for SLA breaches, issue clusters, accounts under pressure.
- `create_escalation`, `update_ticket`, `create_follow_up_task` — **confirmation-gated**.

---

## Quick start

### 0. Prerequisites
- Python 3.11+, Node 18+
- An Anthropic API key

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env          # then edit .env and set ANTHROPIC_API_KEY
python scripts/make_sample_data.py   # optional: writes a stand-in data pack to ../sample_data
uvicorn app.main:app --reload --port 8000
```

**Data pack:** drop the official pack (`01_..._CURRENT.pdf` … `ParcelPilot_Assessment_Data.xlsx`)
into the top-level `data/` folder. If `data/` is empty, the app automatically falls back to
the generated `sample_data/` pack so it runs out of the box.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (proxies /api to :8000)
```

Or build once and let FastAPI serve it as a single service:

```bash
cd frontend && npm run build       # emits frontend/dist
# now http://localhost:8000 serves the UI + API together
```

---

## Trying it

Use the **role switcher** (top right) to act as:
- **Riya — Support Analyst**: read-only (docs, data, ops view); actions denied.
- **Marco — Support Agent**: read + PII + can prepare actions; credit approval limit ₹2,000.
- **Dana — Ops Manager**: everything, incl. larger approvals (₹25,000).

Example prompts:
- *"Can Northstar cancel ORD-1001 without a cancellation fee? Explain why."*
- *"A pickup is 3 hours late due to carrier fault. Should the customer get a service credit?"*
- *"Scan our open tickets for anything urgent or unusual."*
- *"What changed between the current support policy and the deprecated one?"*
- As Riya: *"Escalate the billing dispute on TKT-5004"* → watch it get **denied** in the tool layer.

`GET /api/audit` returns the side effects any confirmed action committed (handy for the demo).

---

## Layout

```
backend/
  app/
    main.py            FastAPI: /api/chat (SSE), /api/confirm, /api/status, /api/users, /api/audit
    config.py          settings (.env)
    auth.py            mock staff users, roles, permissions
    agent/
      loop.py          Claude tool-use loop + event stream + confirmation interception
      prompts.py       system prompt (reliability precedence, escalation rules)
      schemas.py       tool JSON schemas
    tools/
      registry.py      all tools + access-control enforcement + prepare/execute
      context.py       per-request tool context (user, session)
    ingest/
      documents.py     PDF parse + BM25 retrieval (authority-weighted)
      structured.py    xlsx introspection + parameterised query API + snapshot time
      registry.py      per-document reliability metadata (authority tiers, customer scope)
    core/
      knowledge.py     loads + holds the stores
      session.py       in-memory sessions + pending actions + audit log
  scripts/make_sample_data.py   generates a stand-in data pack
frontend/                        Vite + React chat UI (tool chips, confirmation cards, role switch)
docs/ARCHITECTURE.md             agent/tool/data design, reliability & conflict handling, trade-offs
docs/PRODUCT.md                  chosen client problem, roadmap, what's left out, success metric
```

See `docs/ARCHITECTURE.md` and `docs/PRODUCT.md` for the required notes.
