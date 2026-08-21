# Product Note

## Which client problem I chose, and how I addressed it

I built the **internal support/operations chatbot**, which let me address **both** client
problems, with primary focus on **Problem 1 — Proactive Issue Detection** and Problem 2
woven through the core.

**Problem 1 — Proactive Issue Detection.** Beyond answering questions reactively, an
authorised user can ask the agent to scan support activity, and it calls `detect_issues`,
which inspects the ticket data (schema-adaptively) and surfaces:

- **SLA breaches / at-risk tickets** — open tickets whose age (measured against the dataset
  snapshot time) meets or exceeds their SLA, sorted by how far past they are.
- **Issue clusters** — the same category repeating across open tickets (e.g. several
  `pickup_delay` / CarrierX tickets), a signal of a systemic product issue rather than
  isolated complaints.
- **Accounts under pressure** — accounts with several open tickets at once.

Each finding carries a priority and the underlying ticket IDs so a human can act. The natural
next step (below) is to run this on a schedule and push alerts, turning it from on-demand into
a true monitor.

**Problem 2 — Trust & Reliability** is addressed structurally (see the architecture note):
explicit source-authority tiers, customer contracts overriding general policy, deprecated
docs and historical tickets demoted to context-only, conflicts stated explicitly, and
escalation whenever the agent lacks data or authority or cannot resolve a conflict. The goal
is to make "confidently wrong" hard: when sources disagree the agent names the governing one
and why, and when it can't be sure it hands off to a human rather than guessing.

## What I would build next, prioritised

1. **Scheduled proactive monitoring + alerting** (highest value). Run `detect_issues` on a
   cron, diff against the last run, and push new SLA-risk/cluster alerts to Slack/email. This
   is the difference between a dashboard someone remembers to open and a system that earns
   trust by catching things first.
2. **Grounded citations with click-through.** Return the exact source span (doc + page) behind
   every claim and render it as a citation in the UI. Directly reinforces Problem 2 and speeds
   agent verification.
3. **Evaluation harness.** A labelled set of question→governing-source→expected-answer cases
   (including the deliberate conflicts) run in CI, so policy/data changes can't silently
   regress answer quality. Track groundedness and escalation-appropriateness.
4. **Hybrid retrieval + larger corpus.** Add dense embeddings alongside BM25 and a proper
   vector store once the document set grows beyond a handful of PDFs.
5. **Real integrations.** Swap mocked auth for the IdP and the mocked actions for the real
   ticketing/escalation APIs, with durable sessions (Redis/Postgres) and an audit trail.
6. **Customer-facing variant** reusing the same tool layer, with every query hard-pinned to
   the authenticated `account_id` for strict per-account isolation.

## What I intentionally left out

- **Real authentication** — mocked staff users/roles, per the assessment. The permission
  model is real; only the identity source is stubbed.
- **Real side effects** — actions commit to an in-process audit log rather than a live
  ticketing system. The prepare→confirm→execute split is production-shaped.
- **Persistence & horizontal scale** — sessions and pending actions are in-memory.
- **Token-level streaming** and a heavier design system — kept the UI lean but functional
  (it shows the active tool and confirmation cards, which is what the task asks for).
- **A vector database** — unnecessary at this corpus size; noted as an upgrade path.

## One metric to judge usefulness

**Autonomous resolution rate with a groundedness guardrail** — the share of incoming requests
the agent resolves end-to-end *without* human escalation, measured only among answers that
pass a groundedness check (every claim traceable to a governing source), and paired with a low
rate of incorrect confirmed actions.

This captures the whole point: deflecting real support load *without* sacrificing trust. A bot
that answers everything but is sometimes confidently wrong would score badly (the groundedness
gate and the error rate punish it), and so would a bot that escalates everything safely (low
resolution rate). Optimising this one number pushes toward exactly the product we want.
