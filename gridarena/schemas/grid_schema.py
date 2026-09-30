"""Contains Pydantic schemas for a Grid and its dependent components: Nodes, Connections, and Cables."""

from typing import List, Optional

from pydantic import BaseModel

from gridarena.schemas.cables import Cable
from gridarena.schemas.nodes import Node


class Connection(BaseModel):
    connection_id: str
    from_node_id: str
    to_node_id: str
    length: float
    cable_id: str


class Grid(BaseModel):
    grid_id: str
    nodes: List[Node]
    connections: Optional[List[Connection]] = None
    cables: Optional[List[Cable]] = None
