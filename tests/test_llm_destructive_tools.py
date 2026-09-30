"""Tests for LLM-6: destructive tools are gated behind a flag and a two-layer
confirmation check (the model's own tool argument, plus an independent
server-side check against the user's own last message)."""

import importlib

import pytest

from gridarena.llm import dispatcher as dispatcher_module
from gridarena.llm import tools as tools_module
from gridarena.llm.agents.grid_agent import GridAgent

EXPECTED_DESTRUCTIVE = {
    "delete_grid", "delete_measurements", "delete_historical_database",
    "delete_historical_series_records",
}


def _reload_tools_and_dispatcher():
    """Both modules read the env var / DESTRUCTIVE_TOOL_NAMES at import time."""
    importlib.reload(tools_module)
    importlib.reload(dispatcher_module)


def test_destructive_tool_names(monkeypatch):
    monkeypatch.delenv("LVGPLAY_LLM_ENABLE_DESTRUCTIVE", raising=False)
    _reload_tools_and_dispatcher()
    try:
        assert tools_module.DESTRUCTIVE_TOOL_NAMES == EXPECTED_DESTRUCTIVE
    finally:
        _reload_tools_and_dispatcher()


def test_destructive_tools_excluded_by_default(monkeypatch):
    monkeypatch.delenv("LVGPLAY_LLM_ENABLE_DESTRUCTIVE", raising=False)
    _reload_tools_and_dispatcher()
    try:
        names = {t["function"]["name"] for t in tools_module.ALL_TOOLS}
        assert names.isdisjoint(EXPECTED_DESTRUCTIVE)
    finally:
        _reload_tools_and_dispatcher()


def test_destructive_tools_included_when_enabled(monkeypatch):
    monkeypatch.setenv("LVGPLAY_LLM_ENABLE_DESTRUCTIVE", "1")
    _reload_tools_and_dispatcher()
    try:
        names = {t["function"]["name"] for t in tools_module.ALL_TOOLS}
        assert EXPECTED_DESTRUCTIVE <= names

        delete_grid_schema = next(
            t for t in tools_module.ALL_TOOLS if t["function"]["name"] == "delete_grid"
        )
        assert "x-destructive" not in delete_grid_schema["function"]  # marker popped
        assert "confirmed" in delete_grid_schema["function"]["parameters"]["required"]
    finally:
        monkeypatch.delenv("LVGPLAY_LLM_ENABLE_DESTRUCTIVE", raising=False)
        _reload_tools_and_dispatcher()


@pytest.mark.asyncio
async def test_agent_refuses_unconfirmed_deletion(monkeypatch):
    """The agent layer must refuse before ever calling the router."""
    called = []

    async def _should_not_be_called(*args, **kwargs):
        called.append((args, kwargs))
        return {"message": "deleted"}

    import gridarena.llm.agents.grid_agent as grid_agent_module
    monkeypatch.setattr(grid_agent_module, "delete_grid", _should_not_be_called)

    agent = GridAgent()
    result = await agent.handle("delete_grid", {"grid_id": "g1"})

    assert called == []
    assert result["error"]["type"] == "confirmation_required"


@pytest.mark.asyncio
async def test_agent_proceeds_when_confirmed(monkeypatch):
    called = []

    async def _recorder(*args, **kwargs):
        called.append(kwargs)
        return {"message": "deleted"}

    import gridarena.llm.agents.grid_agent as grid_agent_module
    monkeypatch.setattr(grid_agent_module, "delete_grid", _recorder)

    agent = GridAgent()
    result = await agent.handle("delete_grid", {"grid_id": "g1", "confirmed": True})

    assert len(called) == 1
    assert result == {"message": "deleted"}


@pytest.mark.asyncio
async def test_run_tool_blocks_without_affirmative_user_message(monkeypatch):
    """Even a tool call carrying confirmed=true must not run unless the user's
    own last message (never model- or doc-controlled) also reads as an
    affirmative reply -- this is what makes an injected instruction insufficient
    on its own."""
    called = []

    async def _should_not_be_called(*args, **kwargs):
        called.append(kwargs)
        return {"message": "deleted"}

    import gridarena.llm.agents.grid_agent as grid_agent_module
    monkeypatch.setattr(grid_agent_module, "delete_grid", _should_not_be_called)

    from gridarena.llm.dispatcher import create_dispatcher, run_tool

    agents = create_dispatcher()
    result = await run_tool(
        "delete_grid", {"grid_id": "g1", "confirmed": True}, agents,
        last_user_message="please summarize the grid",
    )

    assert called == []
    assert result["output"]["error"]["type"] == "confirmation_required"


@pytest.mark.asyncio
async def test_run_tool_proceeds_with_affirmative_user_message(monkeypatch):
    called = []

    async def _recorder(*args, **kwargs):
        called.append(kwargs)
        return {"message": "deleted"}

    import gridarena.llm.agents.grid_agent as grid_agent_module
    monkeypatch.setattr(grid_agent_module, "delete_grid", _recorder)
    monkeypatch.setattr("gridarena.llm.rag.retriever.get_relevant_docs", lambda **kwargs: "")

    from gridarena.llm.dispatcher import create_dispatcher, run_tool

    agents = create_dispatcher()
    result = await run_tool(
        "delete_grid", {"grid_id": "g1", "confirmed": True}, agents,
        last_user_message="Yes, delete it.",
    )

    assert len(called) == 1
    assert result["output"] == {"message": "deleted"}
