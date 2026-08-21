# AI Tool Usage

- **Claude Code (Anthropic)** was used as the primary coding assistant to scaffold the
  backend and frontend, write the ingestion/retrieval/tool layers, and generate the sample
  data pack. I directed the architecture decisions (internal-ops context, BM25 over vectors,
  source-authority precedence, parameterised queries, prepare→confirm→execute) and reviewed
  and tested all generated code.
- **Claude (claude-sonnet-5)** is the runtime model powering the agent's tool-use loop in
  the application itself.

Every component was verified with local tests (ingestion, retrieval ranking, PII redaction
by role, access-control denials, the calculation tool, issue detection, and the two-phase
confirmation flow) before being considered done.
