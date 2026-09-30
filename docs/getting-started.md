# Getting Started

## Prerequisites

- Python 3.11
- A running PostgreSQL server
- (Optional) Redis, only required for the [Digital Twin](api/digital-twin.md) message
  broker
- (Optional) a CUDA-capable GPU, recommended for [Diffusion Models](api/diffusion.md)
  training and beneficial for [Reinforcement Learning](api/rl.md)

## Installation

```bash
# Clone the repository
git clone <repository_url>
cd <repository_folder>

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate      # Linux / macOS
.venv\Scripts\activate         # Windows

# Install dependencies (installs the gridarena package itself in editable mode too)
pip install -r requirements.txt
```

## Configuration

gridarena is configured entirely through environment variables — there is no
config file. `gridarena/app.py` calls `load_dotenv()` on startup, so a `.env`
file at the repository root is picked up automatically if present (and is
git-ignored).

### Required

| Variable | Description |
|---|---|
| `GRID_DB_DSN` or `DATABASE_URL` | PostgreSQL connection string (e.g. `postgresql://user:password@localhost:5432/gridarena`). `GRID_DB_DSN` takes priority if both are set. The app raises on startup if neither is set. |

### Optional

| Variable | Default | Description |
|---|---|---|
| `DB_POOL_MIN_SIZE` | `2` | Minimum size of the PostgreSQL connection pool (per OS process — see [Architecture](architecture.md#database-layer)). |
| `DB_POOL_MAX_SIZE` | `10` | Maximum size of the PostgreSQL connection pool. |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated list of allowed CORS origins. |
| `LVGPLAY_ANGLE_UNIT` | `deg` | Unit used for voltage-angle values in benchmark noise generation: `deg` or `rad`. |
| `LLM_API_URL` | `https://cpes-llm.inesctec.pt/api` | Base URL of the LLM backend used by the [Chat](api/chat.md) assistant. |
| `LLM_API_KEY` | *(empty)* | API key for the LLM backend. |
| `LLM_MODEL` | `gemma4-31b` | Model name requested from the LLM backend. |
| `LLM_VERIFY_SSL` | `false` | Whether to verify TLS certificates when calling the LLM backend. |
| `LVGPLAY_LLM_ENABLE_DESTRUCTIVE` | `0` | Exposes `delete_grid` / `delete_measurements` / `delete_historical_database` / `delete_historical_series_records` to the chat model. Even when enabled, each call still needs an explicit `confirmed` argument from the model *and* an affirmative reply in the user's own last message — see [Chat](api/chat.md). |
| `LVGPLAY_LLM_MAX_TOOL_RESULT_CHARS` | `8000` | Per-tool-result size cap (characters) before it's truncated in conversation history. |
| `LVGPLAY_LLM_HISTORY_TOKEN_BUDGET` | `24000` | Conversation history is trimmed (oldest messages first) to stay under this estimated token budget. |
| `LVGPLAY_LLM_MAX_TOOL_ROUNDS` | `4` | Maximum tool-call rounds per user turn before the assistant is forced to answer with whatever it has gathered so far. |
| `LVGPLAY_LLM_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Names the embedding model used for RAG (currently always chromadb's bundled ONNX MiniLM). Recorded in the RAG manifest so embedder and retriever are checked against the same value. |
| `LVGPLAY_DATA_DIR` | `./data/llm` | Writable runtime state kept outside the installed package (e.g. document-assistant storage). Created automatically on startup. |
| `REDIS_URL` | `redis://localhost:6379` | Redis instance used as the message broker for [Digital Twin](api/digital-twin.md) data ingestion. |

Digital twins created with `auth_type` other than `none` also reference an
arbitrary environment variable name (`secret_ref`, chosen per-twin) that must
hold the credential used to call the twin's external data source — see the
[Digital Twin API reference](api/digital-twin.md).

### Chat assistant RAG index

The first time the application starts with `LLM_API_KEY` set, it downloads chromadb's
bundled ONNX MiniLM embedding model (a few hundred MB) to embed the built-in agent
documentation (`gridarena/llm/docs/*.md`) into a local vector store at
`gridarena/llm/rag/chroma_db/`. This download happens automatically and needs outbound
network access; on a fully air-gapped deployment, run the application once with network
access first (or copy an already-populated `chroma_db/` directory from another
environment) so the model is cached locally before going offline. Subsequent startups only
re-embed the specific doc files that changed since the last run (tracked in
`chroma_db/manifest.json` by content hash), not the whole index.

### Database setup

The application creates its own tables on first use (each `gridarena/database/create_*`
module runs `CREATE TABLE IF NOT EXISTS ...`), so no separate migration step is
required beyond having an empty, reachable PostgreSQL database available at the
configured DSN.

## Running the application

```bash
uvicorn gridarena.app:app --reload
```

By default the application is available at:

```text
http://127.0.0.1:8000/
```

### Interactive API documentation

FastAPI automatically serves interactive, always-up-to-date API documentation
generated from the router type hints, alongside this handwritten reference:

| UI | URL |
|---|---|
| Swagger UI | `http://127.0.0.1:8000/docs` |
| ReDoc | `http://127.0.0.1:8000/redoc` |
| Raw OpenAPI schema | `http://127.0.0.1:8000/openapi.json` |

### Browser UI

Most functional areas also expose a server-rendered browser UI (Jinja2
templates) under `/<router-prefix>/ui`, e.g. `/grid/ui`, `/mv_grid/ui`,
`/digital-twins/ui`. These UI routes are excluded from the OpenAPI schema
(`include_in_schema=False`) and are not covered by the [API Reference](api/index.md),
which documents the JSON API only.

## Running the tests

```bash
pytest
```

Some test modules exercise the real database and background job machinery end
to end; see [Contributing](contributing.md) for guidance on the test suite and
how to avoid the slower `rl`/`diffusion` tests during day-to-day development.
