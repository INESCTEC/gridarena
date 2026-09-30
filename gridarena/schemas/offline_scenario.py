"""Pydantic schemas for Offline Scenario operations."""

from typing import Dict, Optional

from pydantic import BaseModel, Field


class ConnectionChange(BaseModel):
    action: str
    connection_id: str
    from_node_id: Optional[str] = None
    to_node_id: Optional[str] = None
    cable_id: Optional[str] = None
    length: Optional[float] = None


class CloneRequest(BaseModel):
    name: str = ""
    description: str = ""


class PowerLimitsUpdate(BaseModel):
    power_limits: Dict[str, float] = Field(
        ..., description="Map of node_id to max power in kW. Nodes not listed are uncapped.",
    )
