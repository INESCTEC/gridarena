# Adding New Agents to the gridarena LLM System

This guide explains how to create a new agent and integrate it with the existing LLM chat system. By following these steps, your agent will be discoverable via the chat interface, have its own tools, documentation (served via RAG), and mock fallback data.

---

## Architecture Overview

The LLM system is a multi-agent orchestration layer built on top of the gridarena REST API. Understanding the data flow is essential before adding a new agent:

```
User message (WebSocket)
  │
  ▼
ChatSession.process_message()          ← gridarena/llm/chat.py
  │
  ├─ 1. Keyword matching selects relevant agents
  │     └─ dispatcher.get_relevant_agents()   ← gridarena/llm/dispatcher.py
  │
  ├─ 2. RAG retrieves documentation chunks for those agents
  │     └─ retriever.get_relevant_docs()      ← gridarena/llm/rag/retriever.py
  │
  ├─ 3. LLM receives: system prompt + RAG context + user message + ALL tool schemas
  │     └─ LLM decides which tool to call (or answers directly)
  │
  ├─ 4. Tool call dispatched to the correct agent
  │     └─ dispatcher.run_tool()              ← gridarena/llm/dispatcher.py
  │         └─ agent.handle(tool_name, args)  ← gridarena/llm/agents/<agent>.py
  │             └─ Calls the actual FastAPI router function (with mock fallback)
  │
  └─ 5. LLM interprets the tool result and responds to the user
```

### Key components per agent

| Component | Location | Purpose |
|-----------|----------|---------|
| Agent class | `gridarena/llm/agents/<name>_agent.py` | Tool execution logic with mock fallback |
| Tool schemas | `gridarena/llm/tools/<name>_tools.py` | OpenAI-format function definitions the LLM can call |
| Documentation | `gridarena/llm/docs/<name>.md` | Domain knowledge, chunked and embedded for RAG |
| Mock data | `gridarena/llm/mocks/<name>_mock.py` | Fallback responses when the real API is unavailable |
| Dispatcher wiring | `gridarena/llm/dispatcher.py` | Keyword routing + tool-to-agent mapping |
| RAG registration | `gridarena/llm/rag/embedder.py` | Maps agent name to its documentation file |

---

## Step-by-Step Implementation

The example below creates a hypothetical **ForecastAgent** that exposes two tools: one to generate a load forecast and one to retrieve forecast results.

### Step 1: Define the Tool Schemas

Create `gridarena/llm/tools/forecast_tools.py`:

```python
FORECAST_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_load_forecast",
            "description": (
                "Generate a load forecast for a grid. Use when the user asks "
                "to predict future power consumption or load profiles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "grid_id": {
                        "type": "string",
                        "description": "The grid to forecast.",
                    },
                    "horizon_hours": {
                        "type": "integer",
                        "description": "Forecast horizon in hours (default 24).",
                    },
                },
                "required": ["grid_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_forecast_results",
            "description": (
                "Retrieve results of a previously generated load forecast."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "forecast_id": {
                        "type": "string",
                        "description": "The forecast run identifier.",
                    },
                },
                "required": ["forecast_id"],
            },
        },
    },
]
```

**Guidelines for tool schemas:**
- The `description` field is critical — the LLM uses it to decide *when* to call the tool. Write it from the user's perspective ("Use when the user asks to...").
- Keep `required` minimal; use sensible defaults for optional parameters.
- Parameter descriptions should be concise but unambiguous.

### Step 2: Register the Tools

Edit `gridarena/llm/tools/__init__.py` — add the import and extend `ALL_TOOLS`:

```python
from .forecast_tools import FORECAST_TOOLS
# ... existing imports ...

ALL_TOOLS = [
    *GRID_TOOLS,
    *HISTORICAL_TOOLS,
    *PHASE_TOOLS,
    *TOPOLOGY_TOOLS,
    *STATE_TOOLS,
    *VOLTAGE_TOOLS,
    *POWERFLOW_TOOLS,
    *FORECAST_TOOLS,          # ← add this line
]
```

### Step 3: Create Mock Data

Create `gridarena/llm/mocks/forecast_mock.py`:

```python
FORECAST_RUN_MOCK = {
    "forecast_id": "fc_mock_001",
    "grid_id": "grid_001",
    "horizon_hours": 24,
    "status": "completed",
    "created_at": "2025-07-01T00:00:00",
}

FORECAST_RESULTS_MOCK = {
    "forecast_id": "fc_mock_001",
    "grid_id": "grid_001",
    "predictions": [
        {"timestamp": "2025-07-01T01:00:00", "load_kw": 12.3},
        {"timestamp": "2025-07-01T02:00:00", "load_kw": 11.8},
        {"timestamp": "2025-07-01T03:00:00", "load_kw": 10.5},
    ],
}
```

**Guidelines:**
- Mock data should match the exact structure of the real API response.
- Include enough records to demonstrate the shape (3-5 items is sufficient).
- The LLM will use this data to generate a meaningful response even when the backend is down.

### Step 4: Create the Agent Class

Create `gridarena/llm/agents/forecast_agent.py`:

```python
from gridarena.llm.base_agent import BaseAgent
from gridarena.llm.mocks.forecast_mock import (
    FORECAST_RUN_MOCK,
    FORECAST_RESULTS_MOCK,
)
from gridarena.routers.forecast import (
    run_load_forecast,
    get_forecast_results,
)


class ForecastAgent(BaseAgent):

    async def _run(self, grid_id: str, horizon_hours: int = 24):
        self.last_queried_grid = grid_id
        self._record("run_load_forecast", grid_id=grid_id)
        return await self._safe_call(
            run_load_forecast, FORECAST_RUN_MOCK,
            grid_id=grid_id, horizon_hours=horizon_hours,
        )

    async def _results(self, forecast_id: str):
        self._record("get_forecast_results", forecast_id=forecast_id)
        return await self._safe_call(
            get_forecast_results, FORECAST_RESULTS_MOCK,
            forecast_id=forecast_id,
        )

    async def handle(self, tool_name: str, tool_args: dict, rag_context: str = ""):
        if tool_name == "run_load_forecast":
            return await self._run(
                grid_id=tool_args["grid_id"],
                horizon_hours=tool_args.get("horizon_hours", 24),
            )
        elif tool_name == "get_forecast_results":
            return await self._results(forecast_id=tool_args["forecast_id"])
        return await super().handle(tool_name, tool_args, rag_context)
```

**Key patterns to follow:**
- Inherit from `BaseAgent`.
- One private method per tool (`_run`, `_results`), each using `_safe_call` with its corresponding mock.
- `handle()` dispatches `tool_name` to the correct private method.
- Call `self._record(...)` for query history tracking.
- Set `self.last_queried_grid` when the tool operates on a specific grid.
- The final `return await super().handle(...)` raises `NotImplementedError` for unknown tools — do not silently ignore them.

### Step 5: Export the Agent

Edit `gridarena/llm/agents/__init__.py`:

```python
from .forecast_agent import ForecastAgent
# ... existing imports ...
```

### Step 6: Wire the Dispatcher

Edit `gridarena/llm/dispatcher.py` — three changes:

**a) Import the agent (top of file):**
```python
from gridarena.llm.agents import (
    # ... existing imports ...
    ForecastAgent,
)
```

**b) Add keyword mappings:**
```python
KEYWORD_TO_AGENT = {
    # ... existing entries ...
    "forecast": ["ForecastAgent"],
    "prediction": ["ForecastAgent"],
    "load profile": ["ForecastAgent"],
}
```

**c) Add tool-to-agent mappings:**
```python
TOOL_TO_AGENT_CLASS = {
    # ... existing entries ...
    "run_load_forecast": ForecastAgent,
    "get_forecast_results": ForecastAgent,
}
```

**d) Add to the dispatcher factory:**
```python
def create_dispatcher():
    agents = {
        # ... existing agents ...
        ForecastAgent: ForecastAgent(),
    }
    return agents
```

### Step 7: Write the Documentation (RAG Source)

Create `gridarena/llm/docs/forecast.md`:

```markdown
# Forecast Agent

## Overview

The Forecast Agent generates load predictions for registered grids using
historical measurement data. It answers questions about expected future
power consumption and load profiles.

A grid must have historical data uploaded before a forecast can be generated.

---

## Typical Workflow

1. Register a grid and upload historical measurements.
2. Run a load forecast for a specific horizon (e.g. 24 hours).
3. Retrieve and inspect the forecast results.

---

## Functions

### run_load_forecast

Use when the user wants to predict future load, generate a consumption
forecast, or estimate expected power for upcoming hours.

**Parameters:**
- `grid_id` (string, required): The grid to forecast.
- `horizon_hours` (integer, optional, default 24): How many hours ahead
  to predict.

**Returns:** A forecast run confirmation with `forecast_id` and status.

**Example:**
```json
{"grid_id": "grid_001", "horizon_hours": 48}
```

---

### get_forecast_results

Use when the user wants to see the output of a forecast that was already
generated — predicted load values at each future timestamp.

**Parameters:**
- `forecast_id` (string, required): The forecast run identifier
  returned by `run_load_forecast`.

**Returns:** A list of `{timestamp, load_kw}` predictions.

**Example:**
```json
{"forecast_id": "fc_001"}
```
```

**Guidelines for documentation files:**
- Start with an `## Overview` that explains what the agent does and when to use it.
- Include a `## Typical Workflow` section showing how this agent fits into the larger pipeline.
- Document every function with `**Parameters**`, `**Returns**`, and a JSON `**Example**`.
- Write descriptions from the *user's perspective* — "Use when the user wants to..." — because the RAG system injects these chunks into the LLM's system prompt.
- Keep each function section under ~200 words so it fits cleanly into a single RAG chunk.

### Step 8: Register in the RAG Embedder

Edit `gridarena/llm/rag/embedder.py` — add the mapping:

```python
AGENT_DOC_FILES = {
    # ... existing entries ...
    "ForecastAgent": "forecast.md",
}
```

After this change, delete the existing ChromaDB database directory (`gridarena/llm/rag/chroma_db/`) and restart the application. The RAG system will re-embed all documents including the new one on first startup.

---

## Summary: Files to Create or Edit

| Action | File |
|--------|------|
| **Create** | `gridarena/llm/tools/forecast_tools.py` |
| **Create** | `gridarena/llm/mocks/forecast_mock.py` |
| **Create** | `gridarena/llm/agents/forecast_agent.py` |
| **Create** | `gridarena/llm/docs/forecast.md` |
| **Edit** | `gridarena/llm/tools/__init__.py` — add `FORECAST_TOOLS` to `ALL_TOOLS` |
| **Edit** | `gridarena/llm/agents/__init__.py` — add `ForecastAgent` import |
| **Edit** | `gridarena/llm/dispatcher.py` — add keywords, tool mapping, dispatcher entry |
| **Edit** | `gridarena/llm/rag/embedder.py` — add `"ForecastAgent": "forecast.md"` |
| **Delete** | `gridarena/llm/rag/chroma_db/` — force RAG re-embedding on next startup |

No changes are needed in `app.py`, `chat.py`, `base_agent.py`, or the router itself. The existing orchestration discovers the new agent automatically through the dispatcher registries.

---

## Checklist Before Merging

- [ ] Tool schemas have clear `description` fields the LLM can reason about.
- [ ] `handle()` covers every tool name defined in the schemas.
- [ ] Mock data matches the real API response structure.
- [ ] Documentation covers every function with parameters, returns, and examples.
- [ ] `KEYWORD_TO_AGENT` keywords are lowercase and specific enough to avoid collisions with existing agents.
- [ ] `TOOL_TO_AGENT_CLASS` has one entry per tool name — no tool can belong to two agents.
- [ ] `create_dispatcher()` includes the new agent class.
- [ ] `AGENT_DOC_FILES` maps the exact class name (e.g. `"ForecastAgent"`) to the markdown file.
- [ ] The old `chroma_db/` directory has been deleted so RAG re-embeds on startup.
- [ ] The agent works end-to-end: ask a question in the chat UI, verify the correct tool is called, and the response is coherent.
