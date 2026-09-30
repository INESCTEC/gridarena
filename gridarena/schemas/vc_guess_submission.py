from typing import Annotated, Dict, List, Optional

from pydantic import BaseModel, Field

from gridarena.schemas.types import Phase

# Well above any realistic grid's node/scenario count -- just bounds
# pathological payloads from driving unbounded per-guess DB work.
_MAX_SCENARIOS = 5000
_MAX_NODE_SOLUTIONS = 5000


class NodeVoltageSolution(BaseModel):
    node_id: str
    phase: Optional[Phase] = None
    corrected_voltage: float
    adjusted_power_active: Optional[float] = None
    adjusted_power_reactive: Optional[float] = None


class VCGuessSubmission(BaseModel):
    guess_id: str
    grid_id: str
    guesses: Dict[str, Annotated[List[NodeVoltageSolution], Field(max_length=_MAX_NODE_SOLUTIONS)]] = Field(
        max_length=_MAX_SCENARIOS
    )
