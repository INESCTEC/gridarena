"""Pydantic schemas for Medium Voltage grids, transformers, and LV grid abstractions."""

from typing import List, Optional

from pydantic import BaseModel


class MVNode(BaseModel):
    node_id: str
    coord_lat: Optional[float] = None
    coord_lon: Optional[float] = None
    node_type: Optional[str] = None


class MVCable(BaseModel):
    cable_id: str
    imp_real: float
    imp_imag: float
    nom_curr: float


class MVConnection(BaseModel):
    connection_id: str
    from_node_id: str
    to_node_id: str
    cable_id: str
    length: float


class MVConnectionPoint(BaseModel):
    connection_point_id: str
    node_id: str
    name: Optional[str] = None


class Transformer(BaseModel):
    transformer_id: str
    connection_point_id: str
    lv_grid_id: Optional[str] = None
    rated_power_kva: float
    primary_voltage_kv: float
    secondary_voltage_v: float = 230.0
    imp_real: Optional[float] = None
    imp_imag: Optional[float] = None
    name: Optional[str] = None
    status: Optional[str] = "active"


class MVGrid(BaseModel):
    mv_grid_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    nominal_voltage_kv: float
    region: Optional[str] = None
    nodes: List[MVNode]
    cables: Optional[List[MVCable]] = None
    connections: Optional[List[MVConnection]] = None
    connection_points: Optional[List[MVConnectionPoint]] = None
    transformers: Optional[List[Transformer]] = None


class ConnectLVRequest(BaseModel):
    lv_grid_id: str
    transformer_id: Optional[str] = None
    rated_power_kva: Optional[float] = None
    primary_voltage_kv: Optional[float] = None
    secondary_voltage_v: Optional[float] = 230.0
    imp_real: Optional[float] = None
    imp_imag: Optional[float] = None
    name: Optional[str] = None


class LVAbstraction(BaseModel):
    lv_grid_id: str
    display_name: Optional[str] = None
    connection_point_id: str
    transformer_id: str
    n_nodes: int = 0
    pv_pairs: Optional[List[dict]] = None
