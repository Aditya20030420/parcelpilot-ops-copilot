# AI Tool Usage

- **Claude Code (Anthropic)** was used as the primary coding assistant to scaffold the
  backend and frontend, write the ingestion/retrieval/tool layers, and generate a stand-in
  sample data pack. I directed the architecture decisions (internal-ops context, BM25 over
  vectors, source-authority precedence, parameterised queries, prepare→confirm→execute) and
  reviewed and tested all generated code.
- The runtime agent uses the **OpenAI SDK against an OpenAI-compatible endpoint**, which
  keeps the provider swappable. It was tested end-to-end on **Google Gemini
  (`gemini-3.5-flash-lite`)** via Gemini's OpenAI-compatible API; it runs unchanged on
  OpenAI or Groq by swapping the key/base URL/model.

Every component was verified with local tests (ingestion, retrieval ranking, PII redaction
by role, access-control denials, the calculation tool, issue detection, and the two-phase
confirmation flow) before being considered done.
