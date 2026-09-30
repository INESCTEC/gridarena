import copy
import os

from .grid_tools import GRID_TOOLS
from .historical_tools import HISTORICAL_TOOLS
from .measurements_tools import MEASUREMENTS_TOOLS
from .phase_tools import PHASE_TOOLS
from .topology_tools import TOPOLOGY_TOOLS
from .state_tools import STATE_TOOLS
from .voltage_tools import VOLTAGE_TOOLS
from .powerflow_tools import POWERFLOW_TOOLS

# Deep-copied so this module never mutates the *_tools.py constants it was built
# from -- the "x-destructive" pop below would otherwise permanently strip the
# marker from e.g. GRID_TOOLS itself, since Python list unpacking shares the
# same dict objects, not copies.
_ALL = copy.deepcopy([
    *GRID_TOOLS,
    *HISTORICAL_TOOLS,
    *MEASUREMENTS_TOOLS,
    *PHASE_TOOLS,
    *TOPOLOGY_TOOLS,
    *STATE_TOOLS,
    *VOLTAGE_TOOLS,
    *POWERFLOW_TOOLS,
])

# Pop the marker (rather than just read it) so it is never sent to the LLM API --
# it's an internal routing hint, not part of the public tool schema.
DESTRUCTIVE_TOOL_NAMES = {t["function"]["name"] for t in _ALL if t["function"].pop("x-destructive", False)}

ALL_TOOLS = (
    _ALL if os.getenv("LVGPLAY_LLM_ENABLE_DESTRUCTIVE") == "1"
    else [t for t in _ALL if t["function"]["name"] not in DESTRUCTIVE_TOOL_NAMES]
)


def tools_for_agents(agent_names: list[str]) -> list[dict]:
    """Return only the (currently advertised) tool schemas owned by the given
    agent classes -- e.g. a message that only matched "phase" keywords doesn't
    need the historical/voltage/topology schemas on every request.

    The dispatcher import is deferred: dispatcher.py imports DESTRUCTIVE_TOOL_NAMES
    from this module at its own module level, so importing dispatcher.py back at
    this module's top level would be circular.
    """
    from gridarena.llm.dispatcher import TOOL_TO_AGENT_CLASS

    wanted = set(agent_names)
    names = {
        tool_name for tool_name, cls in TOOL_TO_AGENT_CLASS.items()
        if cls.__name__ in wanted
    }
    return [t for t in ALL_TOOLS if t["function"]["name"] in names]
