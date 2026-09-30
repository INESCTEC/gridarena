"""Pydantic schemas for representing node/grid-scoped measurement data in a power grid system."""

from typing import List, Optional

from pydantic import BaseModel

from gridarena.schemas.types import Phase

class Measurements(BaseModel):

    datetime: str  # Ver se dá para ser datetime
    phase: Optional[Phase] = None
    power_active: float
    power_reactive: float
    voltage_magnitude: float
    voltage_angle: float


class MeasurementsNodeData(BaseModel):

    node_id: str
    measurements: List[Measurements]


class MeasurementsData(BaseModel):

    grid_id: str
    historical: List[MeasurementsNodeData]
