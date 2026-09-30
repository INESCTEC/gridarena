"""Contract tests binding tool schemas to agents to the router signatures they call.

Each LLM tool schema advertises a set of keyword arguments to the model. The agent that
implements the tool then calls a FastAPI router function directly (in-process, no HTTP
layer) with a hand-written set of keyword arguments. Nothing before this file checked that
those two argument lists actually match -- which is exactly how three tools
(register_grid, upload_historical_database, register_measurements_data) shipped calling
their router with `file_path=...` when the real parameter is `file`, raising TypeError on
every single invocation. See LLM-2, which removed those three tools.
"""

import importlib
import inspect

import pytest
from fastapi.params import Body, File, Query

from gridarena.llm import dispatcher as dispatcher_module
from gridarena.llm import tools as tools_module

# tool name -> (dotted module the router function is imported INTO, the bound name there).
# Agents do `from gridarena.routers.x import y` at module load time, so patching
# gridarena.routers.x.y would miss the call entirely -- the agent module already holds its
# own reference. This mirrors improvement_plan.md task H3-D.
TOOL_LOCATIONS = {
    "get_grid_data": ("gridarena.llm.agents.grid_agent", "get_grid"),
    "delete_grid": ("gridarena.llm.agents.grid_agent", "delete_grid"),
    "delete_measurements": ("gridarena.llm.agents.measurements_agent", "delete_measurements"),
    "get_measurements_data": ("gridarena.llm.agents.measurements_agent", "get_measurements_data"),
    "delete_historical_database": ("gridarena.llm.agents.historical_agent", "delete_historical_database"),
    "delete_historical_series_records": (
        "gridarena.llm.agents.historical_agent", "delete_historical_series_records",
    ),
    "get_historical_series_data": ("gridarena.llm.agents.historical_agent", "get_historical_series_data"),
    "get_training_phase_data": ("gridarena.llm.agents.phase_agent", "get_training_phase_identification_data"),
    "get_phase_identification_data": ("gridarena.llm.agents.phase_agent", "get_phase_identification_data"),
    "submit_phase_guesses": ("gridarena.llm.agents.phase_agent", "submit_phase_guesses"),
    "get_phase_score": ("gridarena.llm.agents.phase_agent", "get_score"),
    "get_training_topology_data": ("gridarena.llm.agents.topology_agent", "get_topology_identification_data"),
    "get_topology_discovery_data": ("gridarena.llm.agents.topology_agent", "get_topology_discovery_data"),
    "submit_topology_guesses": ("gridarena.llm.agents.topology_agent", "submit_topology_guesses"),
    "get_topology_score": ("gridarena.llm.agents.topology_agent", "get_score"),
    "get_training_state_data": ("gridarena.llm.agents.state_agent", "get_training_state_data"),
    "get_state_estimation_input": ("gridarena.llm.agents.state_agent", "get_state_estimation_input"),
    "submit_state_estimates": ("gridarena.llm.agents.state_agent", "submit_state_estimates"),
    "get_state_estimation_score": ("gridarena.llm.agents.state_agent", "get_state_estimation_score"),
    "get_training_voltage_control_data": (
        "gridarena.llm.agents.voltage_agent", "get_training_voltage_control_data",
    ),
    "get_voltage_control_data": ("gridarena.llm.agents.voltage_agent", "get_voltage_control_data"),
    "submit_voltage_control_guesses": ("gridarena.llm.agents.voltage_agent", "submit_voltage_control_guesses"),
    "get_voltage_control_score": ("gridarena.llm.agents.voltage_agent", "get_score"),
    "run_power_flow": ("gridarena.llm.agents.powerflow_agent", "run_power_flow"),
    "get_power_flow_results": ("gridarena.llm.agents.powerflow_agent", "get_power_flow_results"),
}

# Minimal valid argument set per tool -- enough to satisfy any Pydantic submission model
# the agent builds before it even reaches the (patched) router call.
MINIMAL_ARGS = {
    "get_grid_data": {"grid_id": "g1", "table": "Node"},
    "delete_grid": {"grid_id": "g1", "confirmed": True},
    "delete_measurements": {"grid_id": "g1", "confirmed": True},
    "get_measurements_data": {"grid_id": "g1"},
    "delete_historical_database": {"database_id": "d1", "confirmed": True},
    "delete_historical_series_records": {"database_id": "d1", "series_id": "s1", "confirmed": True},
    "get_historical_series_data": {"database_id": "d1", "series_id": "s1"},
    "get_training_phase_data": {},
    "get_phase_identification_data": {},
    "submit_phase_guesses": {"guess_id": "u1", "grid_id": "g1", "guesses": {"m1": "R"}},
    "get_phase_score": {"guess_id": "u1", "grid_id": "g1"},
    "get_training_topology_data": {},
    "get_topology_discovery_data": {},
    "submit_topology_guesses": {"guess_id": "u1", "grid_id": "g1", "guesses": [[1, 2]]},
    "get_topology_score": {"guess_id": "u1", "grid_id": "g1"},
    "get_training_state_data": {},
    "get_state_estimation_input": {"user_id": "u1"},
    "submit_state_estimates": {
        "user_id": "u1", "estimation_id": "e1", "grid_id": "g1", "timestamp": "2025-01-01T00:00:00",
        "estimates": [{"masked_node_id": "m1", "voltage_magnitude": 1.0, "voltage_angle": 0.0}],
    },
    "get_state_estimation_score": {"user_id": "u1", "estimation_id": "e1"},
    "get_training_voltage_control_data": {"voltage_limit": 1.1},
    "get_voltage_control_data": {"voltage_limit": 1.1},
    "submit_voltage_control_guesses": {
        "guess_id": "u1", "grid_id": "g1",
        "guesses": {"s1": [{"node_id": "N1", "corrected_voltage": 1.0}]},
    },
    "get_voltage_control_score": {"guess_id": "u1", "grid_id": "g1"},
    "run_power_flow": {"grid_id": "g1", "phase": "R"},
    "get_power_flow_results": {"grid_id": "g1", "phase": "R"},
}

FASTAPI_MARKERS = (Query, File, Body)


def test_every_registered_tool_has_a_schema_and_an_agent(monkeypatch):
    """The full tool schema set (destructive tools included, regardless of whether
    LLM-6's flag currently advertises them) and TOOL_TO_AGENT_CLASS must describe
    exactly the same tool names -- an orphaned schema or handler is a real bug."""
    monkeypatch.setenv("LVGPLAY_LLM_ENABLE_DESTRUCTIVE", "1")
    importlib.reload(tools_module)
    importlib.reload(dispatcher_module)
    try:
        tool_names = {t["function"]["name"] for t in tools_module.ALL_TOOLS}
        agent_tool_names = set(dispatcher_module.TOOL_TO_AGENT_CLASS.keys())
        assert tool_names == agent_tool_names
    finally:
        monkeypatch.delenv("LVGPLAY_LLM_ENABLE_DESTRUCTIVE", raising=False)
        importlib.reload(tools_module)
        importlib.reload(dispatcher_module)


def test_tool_locations_cover_every_tool():
    """This file's own fixtures must not silently fall behind the real tool list
    (the full set, including tools LLM-6 may currently be gating off by default)."""
    tool_names = set(dispatcher_module.TOOL_TO_AGENT_CLASS.keys())
    assert tool_names == set(TOOL_LOCATIONS.keys())
    assert tool_names == set(MINIMAL_ARGS.keys())


@pytest.fixture
def recorder_for(monkeypatch):
    """Patch a tool's router function where the agent imported it; return (calls, real_fn)."""

    def _patch(tool_name: str):
        module_path, bound_name = TOOL_LOCATIONS[tool_name]
        module = importlib.import_module(module_path)
        real_fn = getattr(module, bound_name)
        calls = []

        async def _recorder(*args, **kwargs):
            calls.append(kwargs)
            return {"ok": True}

        monkeypatch.setattr(module, bound_name, _recorder)
        return calls, real_fn

    return _patch


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(TOOL_LOCATIONS.keys()))
async def test_agent_calls_match_router_signatures(tool_name, recorder_for):
    """The agent's call into a router must use only keyword names the router accepts."""
    from gridarena.llm.dispatcher import create_dispatcher, run_tool

    calls, real_fn = recorder_for(tool_name)
    agents = create_dispatcher()

    # "yes" satisfies the LLM-6 destructive-tool confirmation gate for the four
    # delete_* tools; it's a no-op for every other tool.
    await run_tool(tool_name, MINIMAL_ARGS[tool_name], agents, last_user_message="yes")

    assert len(calls) == 1, f"{tool_name} did not call its router function exactly once"
    real_params = set(inspect.signature(real_fn).parameters)
    called_kwargs = set(calls[0].keys())
    assert called_kwargs <= real_params, (
        f"{tool_name} passed unknown keyword(s) {called_kwargs - real_params} "
        f"to {real_fn.__name__}; valid parameters are {real_params}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(TOOL_LOCATIONS.keys()))
async def test_no_router_default_leaks_fieldinfo(tool_name, recorder_for):
    """Every FastAPI Query/File/Body-defaulted router parameter must be passed explicitly.

    Calling a FastAPI path-operation function directly (as these agents do, in-process,
    with no HTTP layer in between) never triggers FastAPI's dependency-injection step. Any
    parameter the agent doesn't pass explicitly falls back to its raw default -- which for
    a Query()/File()/Body() parameter is the marker object itself, not the value it
    describes. That FieldInfo-shaped object then flows into application code expecting a
    string/bool/etc.
    """
    from gridarena.llm.dispatcher import create_dispatcher, run_tool

    calls, real_fn = recorder_for(tool_name)
    agents = create_dispatcher()

    await run_tool(tool_name, MINIMAL_ARGS[tool_name], agents, last_user_message="yes")

    called_kwargs = set(calls[0].keys())
    signature = inspect.signature(real_fn)
    for name, param in signature.parameters.items():
        if isinstance(param.default, FASTAPI_MARKERS):
            assert name in called_kwargs, (
                f"{tool_name} -> {real_fn.__name__} never passes '{name}' explicitly; "
                f"calling it directly would leak the raw {type(param.default).__name__} marker"
            )
