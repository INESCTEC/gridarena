# Chat

Two independent chat surfaces:

- **Grid assistant** — a tool-using WebSocket session that answers questions about
  registered grids and runs benchmark/power-flow tools on request. Backed by eight
  built-in agents (`gridarena/llm/agents/`), routed by keyword match
  (`gridarena/llm/dispatcher.py`), with retrieval-augmented context drawn from the built-in
  agent docs (`gridarena/llm/docs/*.md`).
- **Document assistants** *(optional, off by default)* — user-created, read-only knowledge
  bases built from uploaded Markdown files. A document assistant has **no tools**, cannot
  reach the grid assistant's prompt or tool list, and answers only from its own attached
  documents, citing the file and section for every factual claim.

See [Architecture › LLM Chat](../architecture.md#llm-chat) for the subsystem design.

**Base path:** `/chat`

Also serves a browser UI at `/chat/ui` (grid assistant) and a configuration overview at
`/chat/ui/config`, each with a "Document Assistants" button when the feature is enabled.

## What the assistant can and cannot do

- It can query registered grids, measurements, historical data, and run/submit benchmark
  and power-flow operations — through router functions called **directly, in-process**, not
  over HTTP. No route-level dependency (including an API key, if configured per
  `improvement_plan.md` task C2) applies to this path; the WebSocket itself would need to be
  authenticated separately if the deployment requires that.
- It **cannot upload or register grids, measurements, or historical data** on the user's
  behalf — the three tools that once attempted this always called their router with the
  wrong argument and never worked. The assistant is instructed to tell the user to use the
  web UI or the REST endpoint instead.
- Destructive tools (`delete_grid`, `delete_measurements`, `delete_historical_database`,
  `delete_historical_series_records`) are **disabled by default**
  (`LVGPLAY_LLM_ENABLE_DESTRUCTIVE=0`). When enabled, a deletion still requires both an
  explicit `confirmed: true` argument from the model **and** an independent, server-side
  check that the user's own last message reads as an affirmative reply — a confirmation
  embedded in retrieved or injected text is not sufficient on its own.
- A tool call can fail (bad input, a database outage, a bug). The assistant is told to
  report the failure plainly and never fabricate a result — earlier versions substituted
  hard-coded mock data on any exception, which this now never does.
- Tool results are size-capped (`LVGPLAY_LLM_MAX_TOOL_RESULT_CHARS`, default 8000
  characters); a result larger than that is truncated with `"truncated": true` and a hint to
  narrow the query, and the assistant is told to surface that explicitly rather than guess
  at the missing data. Conversation history is trimmed to an estimated token budget
  (`LVGPLAY_LLM_HISTORY_TOKEN_BUDGET`, default 24000), oldest messages first.
- A single user turn can span up to `LVGPLAY_LLM_MAX_TOOL_ROUNDS` (default 4) rounds of tool
  calls before the assistant is forced to answer with whatever it has gathered — enough for
  a workflow like "fetch the benchmark data, then submit my guesses" to complete in one
  turn. A tool called with identical arguments more than a couple of times in one turn is
  treated as a stuck loop and blocked.
- Only the tool schemas owned by the agent(s) matched to the message's keywords are sent to
  the model on a given request (falling back to the full set when nothing matched, or after
  a tool call names something outside the offered set) — this is a token-cost optimization,
  not a security boundary; nothing stops the model from asking about a different agent's
  domain in a follow-up message once its tools are back in scope.
- Retrieved documentation (both the built-in RAG docs and, for a document assistant, its
  attached files) is never placed in the system prompt. It is passed as a separate,
  clearly-delimited `<reference>`-tagged user message, and the system prompt explicitly
  instructs the model to treat that content as material to read, never as instructions to
  follow.

## Endpoints

### `GET /chat/config`

Returns the current LLM agent configuration — model/endpoint settings (no secrets) and
every built-in agent's currently-advertised tools (destructive tools are omitted here too
when the flag that gates them is off).

**Response** `200`

```json
{
  "model": "gpt-4o-mini",
  "api_url": "https://api.example.com/v1",
  "api_key_configured": true,
  "temperature": 0.2,
  "max_tokens_with_tools": 1024,
  "max_tokens_interpretation": 1024,
  "verify_ssl": true,
  "agents": [
    {
      "name": "GridAgent",
      "description": "Manages electrical network models — register, query, and delete grid topologies (nodes, connections, cables).",
      "tools": [{ "name": "get_grid_data", "description": "Fetch a grid's nodes, connections, and cables." }],
      "keywords": ["grid", "topology"],
      "has_rag_docs": true,
      "rag_doc_file": "grid.md"
    }
  ],
  "total_tools": 21
}
```

`api_key_configured` reports only whether an API key is set, never the key itself.

---

### `WS /chat/ws`

Drives one interactive grid-assistant session. Each WebSocket connection gets its own
server-side `ChatSession` with independent conversation history — a new connection starts a
fresh session, and there is no way to resume a previous one.

!!! note "Long messages are rejected client-side of the LLM call"
    A `user_message` longer than 8,000 characters is never sent to the LLM backend — the
    session replies immediately with a plain `assistant_message`-shaped rejection text
    asking the caller to shorten it.

!!! warning "Errors are sanitized before being sent to the client"
    If processing a message raises an exception, the full exception is logged server-side
    only; the client receives a generic
    `{"type": "error", "content": "An internal error occurred..."}`, never the raw exception
    text — except a missing `LLM_API_KEY`, which is reported as its own specific, safe
    configuration-error message rather than folded into the generic one.

**Client → Server messages**

```json
{ "type": "user_message", "content": "What's the voltage at node N1 in grid001?" }
```

Any message without `"type": "user_message"` is silently ignored.

**Server → Client messages**

Sent once per tool round, when more than one round is possible:

```json
{ "type": "status", "content": "Tool round 1 of 4..." }
```

Sent once per tool call, before it runs, and again after it completes:

```json
{ "type": "status", "content": "Running get_grid_data...", "tool_name": "get_grid_data" }
{ "type": "tool_result", "tool_name": "get_grid_data", "agent": "GridAgent", "summary": "Completed get_grid_data" }
```

Sent once per user message, with the assistant's final reply:

```json
{ "type": "assistant_message", "content": "Node N1 is at 229.8 V (0.999 pu)." }
```

Sent instead of `assistant_message` if processing the message failed:

```json
{ "type": "error", "content": "An internal error occurred while processing your message. Please try again." }
```

A client disconnect is logged server-side and simply ends the session — no closing message
is sent.

---

## Document assistants

*(behind `LVGPLAY_ALLOW_DOCUMENT_AGENTS=1`, default off)*

A document assistant is a small, user-created knowledge base: a name, a description, and a
set of attached Markdown source files. It has no tools, never sees the grid assistant's
system prompt, and its retrieval collection is structurally unreachable from the grid
assistant's own retrieval path (`get_relevant_docs` raises if ever asked to query a
document-assistant collection). Attaching hostile or manipulative text to a document
assistant cannot make it call a tool or affect any other session — there is nothing there
for it to call.

### Why Markdown only

Source files must be `.md` or `.markdown`, valid UTF-8. Anything else is rejected with
`415`. This was a deliberate choice, not a first pass to be extended later: it means the
feature needs no new document-parsing dependency (chunking reuses the same heading-aware
splitter as the built-in RAG docs), and it means every citation can point at a real,
addressable section — a PDF's page number is not something a browser can jump to the way a
heading anchor is. If a source is a PDF or Word document, convert it to Markdown first and
keep the heading structure: citations are generated per-heading, so a document with no
headings still ingests fine (as a single, whole-document section) but its citations will
all point at the top of the page rather than a specific place in it.

### Limits

| Variable | Default | Applies to |
|---|---|---|
| `LVGPLAY_LLM_MAX_SOURCE_MB` | `5` | Per-file upload size. Oversized files are rejected with `413`. |
| `LVGPLAY_LLM_MAX_SOURCES_PER_AGENT` | `20` | Total attached files per agent. Rejected with `422` once reached. |
| `LVGPLAY_LLM_DOC_CHUNKS_PER_ANSWER` | `6` | Excerpts retrieved per question. |

Re-uploading a file whose content exactly matches an already-attached source (by SHA-256)
is a no-op, reported as `"status": "duplicate"` rather than re-embedded.

### `POST /chat/agents`

Creates a document assistant and ingests any files attached at creation time.

**Request body** (`multipart/form-data`)

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Display name. |
| `description` | string | no | Shown in the assistant picker. |
| `files` | file (repeated) | no | Zero or more `.md`/`.markdown` files. |

A rejected file (wrong extension, not UTF-8, too large, or the agent already has too many
sources) does **not** fail the whole request — each file's outcome is reported individually,
so a batch upload can partially succeed.

**Response** `200`

```json
{
  "agent": {
    "agent_id": "a1b2c3d4e5f6",
    "name": "Noise Robustness Papers",
    "description": "Papers on measurement noise in state estimation",
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
    "sources": [
      {
        "source_id": "0123456789ab",
        "filename": "paper.md",
        "sha256": "...",
        "bytes": 1842,
        "chunks": 4,
        "title": "Noise Robustness in Grid State Estimation",
        "headings": ["Introduction", "Noise model", "Estimation procedure", "Results"],
        "uploaded_at": "2026-01-01T00:00:00+00:00"
      }
    ]
  },
  "files": [
    { "filename": "paper.md", "status": "ingested", "source_id": "0123456789ab", "chunks": 4, "title": "Noise Robustness in Grid State Estimation" }
  ]
}
```

A per-file `status` is one of `ingested`, `duplicate`, or `rejected` (with a `detail`
message naming the reason).

---

### `GET /chat/agents`

Lists every document assistant's manifest (agent_id, name, description, and its sources).

---

### `GET /chat/agents/{agent_id}`

Returns one assistant's manifest. `404` if it doesn't exist.

---

### `POST /chat/agents/{agent_id}/sources`

Adds one or more Markdown files to an existing assistant. Same per-file `files` field and
partial-failure reporting as `POST /chat/agents`. `404` if the agent doesn't exist.

---

### `DELETE /chat/agents/{agent_id}/sources/{source_id}`

Removes one source: its file, its manifest entry, and its chunks from the assistant's
retrieval collection. `404` if the source doesn't exist.

---

### `DELETE /chat/agents/{agent_id}`

Removes the assistant entirely — its directory on disk and its retrieval collection.
`404` if it doesn't exist.

---

### `GET /chat/agents/{agent_id}/sources/{source_id}`

Returns the raw Markdown of one source (`text/markdown`), for download.

---

### `GET /chat/agents/{agent_id}/sources/{source_id}/view`

Renders the source to HTML with an `id` attribute on every heading, computed the same way
as the anchor recorded on each retrieval chunk at ingest time — so a citation link
(`.../view#some-anchor`) jumps to the exact section it cites. This is a minimal renderer
(headings become real heading tags; everything else is escaped, paragraph-wrapped text), not
a full Markdown-to-HTML pipeline.

---

### `WS /chat/agents/{agent_id}/ws`

Drives one document-assistant chat session, scoped to that agent's own attached documents
only. `404`-closes (WebSocket close code `1008`) if the feature flag is off or the agent
doesn't exist.

**Client → Server / Server → Client messages** follow the same `user_message` /
`assistant_message` / `error` shape as `WS /chat/ws`, with one addition: `assistant_message`
carries a `citations` array.

```json
{
  "type": "assistant_message",
  "content": "Noise is modelled as additive Gaussian noise at 1% of nominal voltage [1].",
  "citations": [
    {
      "marker": 1,
      "source_id": "0123456789ab",
      "filename": "paper.md",
      "section": "Method > Noise model",
      "anchor": "noise-robustness-in-grid-state-estimation-method-noise-model",
      "snippet": "We model sensor noise as additive Gaussian noise with a standard deviation of 1%..."
    }
  ]
}
```

The assistant is instructed to cite every factual statement with a bracketed number
matching a retrieved excerpt (`[1]`, `[2]`, ...). A citation marker with no matching excerpt
is dropped from the response (logged as a warning) rather than shown broken. If the attached
documents don't contain the answer, the assistant is instructed to say so rather than answer
from outside knowledge.
