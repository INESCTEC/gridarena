"""Defines the Node data model for representing node properties in the grid database."""

from typing import Optional

from pydantic import BaseModel


class Node(BaseModel):
    node_id: str
    coord_lat: Optional[float] = None
    coord_lon: Optional[float] = None
    coord_error: Optional[int] = None
