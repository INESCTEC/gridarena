import logging
import re

from gridarena.llm.agents import (
    GridAgent,
    HistoricalAgent,
    MeasurementsAgent,
    PhaseAgent,
    PowerflowAgent,
    StateAgent,
    TopologyAgent,
    VoltageAgent,
)
from gridarena.llm.tools import DESTRUCTIVE_TOOL_NAMES

logger = logging.getLogger(__name__)

# A confirmation phrase in the agent's own tool arguments is not enough on its own --
# it could be an instruction injected through retrieved text. This is the independent,
# server-side check: the *user's own last message* (never model- or doc-controlled) must
# also look like an affirmative reply before a destructive tool actually runs.
_AFFIRMATIVE_RE = re.compile(r"^\s*(yes|confirm|delete|go ahead|do it)\b", re.IGNORECASE)

KEYWORD_TO_AGENT = {
    "grid": ["GridAgent"],
    "register": ["GridAgent"],
    "delete grid": ["GridAgent"],
    "measurement": ["MeasurementsAgent"],
    "measurements": ["MeasurementsAgent"],
    "historical": ["HistoricalAgent"],
    "series": ["HistoricalAgent"],
    "phase": ["PhaseAgent"],
    "phase identification": ["PhaseAgent"],
    "topology": ["TopologyAgent"],
    "connection": ["TopologyAgent"],
    "state": ["StateAgent"],
    "estimation": ["StateAgent"],
    "voltage": ["VoltageAgent"],
    "violation": ["VoltageAgent"],
    "overvoltage": ["VoltageAgent"],
    "undervoltage": ["VoltageAgent"],
    "power flow": ["PowerflowAgent"],
    "powerflow": ["PowerflowAgent"],
}

TOOL_TO_AGENT_CLASS = {
    "get_grid_data": GridAgent,
    "delete_grid": GridAgent,
    "delete_measurements": MeasurementsAgent,
    "get_measurements_data": MeasurementsAgent,
    "delete_historical_database": HistoricalAgent,
    "delete_historical_series_records": HistoricalAgent,
    "get_historical_series_data": HistoricalAgent,
    "get_training_phase_data": PhaseAgent,
    "get_phase_identification_data": PhaseAgent,
    "submit_phase_guesses": PhaseAgent,
    "get_phase_score": PhaseAgent,
    "get_training_topology_data": TopologyAgent,
    "get_topology_discovery_data": TopologyAgent,
    "submit_topology_guesses": TopologyAgent,
    "get_topology_score": TopologyAgent,
    "get_training_state_data": StateAgent,
    "get_state_estimation_input": StateAgent,
    "submit_state_estimates": StateAgent,
    "get_state_estimation_score": StateAgent,
    "get_training_voltage_control_data": VoltageAgent,
    "get_voltage_control_data": VoltageAgent,
    "submit_voltage_control_guesses": VoltageAgent,
    "get_voltage_control_score": VoltageAgent,
    "run_power_flow": PowerflowAgent,
    "get_power_flow_results": PowerflowAgent,
}


def _keyword_matched_agents(query: str) -> list[str]:
    query_lower = query.lower()
    relevant = set()
    for keyword, agents in KEYWORD_TO_AGENT.items():
        if keyword in query_lower:
            relevant.update(agents)
    return list(relevant)


def has_keyword_match(query: str) -> bool:
    """True if the query matched at least one routing keyword.

    Used by chat.py (LLM-9) to decide whether the narrowed, keyword-matched tool
    set is trustworthy for this turn, or whether the full tool set should be sent
    instead -- get_relevant_agents()'s own fallback below picks a fixed 3-agent
    default when nothing matches, which is a reasonable default for RAG doc
    selection but too narrow to trust for tool availability.
    """
    return bool(_keyword_matched_agents(query))


def get_relevant_agents(query: str) -> list[str]:
    relevant = _keyword_matched_agents(query)
    if not relevant:
        return ["GridAgent", "VoltageAgent", "PowerflowAgent"]
    return relevant


def create_dispatcher():
    """Create a fresh set of agent instances (one per session for isolation)."""
    agents = {
        GridAgent: GridAgent(),
        HistoricalAgent: HistoricalAgent(),
        MeasurementsAgent: MeasurementsAgent(),
        PhaseAgent: PhaseAgent(),
        TopologyAgent: TopologyAgent(),
        StateAgent: StateAgent(),
        VoltageAgent: VoltageAgent(),
        PowerflowAgent: PowerflowAgent(),
    }
    return agents


async def run_tool(
    tool_name: str, tool_args: dict, agents: dict, last_user_message: str = "", session_id: str = "",
) -> dict:
    agent_class = TOOL_TO_AGENT_CLASS.get(tool_name)
    if not agent_class:
        # A structured error (not a raised exception) so chat.py can recognise this
        # specific case and widen the next round's tool set (LLM-9) -- this is the
        # model calling a name outside the narrowed set it was actually offered.
        logger.warning("Unknown tool requested: %s", tool_name)
        return {
            "agent": "Unknown",
            "function": tool_name,
            "output": {"error": {"type": "unknown_tool", "detail": f"Unknown tool: {tool_name}"}},
        }

    agent = agents[agent_class]
    agent_name = type(agent).__name__

    if tool_name in DESTRUCTIVE_TOOL_NAMES and not _AFFIRMATIVE_RE.match(last_user_message or ""):
        logger.info("Blocked destructive tool %s: no affirmative user message this turn", tool_name)
        return {
            "agent": agent_name,
            "function": tool_name,
            "output": {"error": {
                "type": "confirmation_required",
                "detail": "Ask the user to confirm the deletion, then retry with confirmed=true.",
            }},
        }

    if tool_name in DESTRUCTIVE_TOOL_NAMES:
        logger.warning(
            "Executing destructive tool %s: session=%s args=%s", tool_name, session_id, tool_args,
        )

    result = await agent.handle(tool_name, tool_args)

    return {
        "agent": agent_name,
        "function": tool_name,
        "output": result,
    }
