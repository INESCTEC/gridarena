from typing import List

from pydantic import BaseModel, Field

# Well above any realistic grid's node count -- just bounds pathological
# payloads from driving unbounded per-estimate DB work.
_MAX_ESTIMATES = 5000


class Estimate(BaseModel):
    masked_node_id: str
    voltage_magnitude: float
    voltage_angle: float


class StateEstimateSubmission(BaseModel):
    user_id: str
    estimation_id: str
    grid_id: str  # masked grid id
    timestamp: str
    estimates: List[Estimate] = Field(max_length=_MAX_ESTIMATES)  # masked_node_id -> Estimate
