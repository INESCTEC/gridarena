"""MV-specific grid topology loader for the PF data-generation pipeline.

Mirrors gridarena/powerflow/get_grid_info.py's LV accessor pattern against the
MV tables ("MVNode"/"MVConnection"/"MVCable") instead of the LV ones, plus a
substation-rooted connectivity helper used by topology perturbation.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

import networkx as nx


@dataclass
class MVBranch:
    connection_id: str
    from_node_id: str
    to_node_id: str
    cable_id: str
    length_m: float
    r_ohm_per_km: float
    x_ohm_per_km: float
    nom_curr_a: Optional[float]


@dataclass
class MVGridTopology:
    mv_grid_id: str
    nominal_voltage_kv: float
    substation_node_id: str
    node_id_to_index: Dict[str, int]
    branches: List[MVBranch]  # root-outward, same order as the MVConnection rows


def get_mv_grid_topology(mv_grid_id: str, cursor) -> MVGridTopology:
    """Load an MV grid's nodes/branches from the database.

    Raises if the grid has no nodes, no connections, or does not have exactly
    one node with NodeType = 'substation' (the reference/slack bus, the
    MV-side analogue of LV's "PT" node).
    """
    cursor.execute('SELECT nominal_voltage_kv FROM "MVGrid" WHERE mv_grid_id = %s', (mv_grid_id,))
    row = cursor.fetchone()
    if row is None:
        raise Exception(f"MV grid '{mv_grid_id}' not found.")
    nominal_voltage_kv = row[0]

    cursor.execute('SELECT "NodeId", "NodeType" FROM "MVNode" WHERE mv_grid_id = %s', (mv_grid_id,))
    node_rows = cursor.fetchall()
    if not node_rows:
        raise Exception(f"No nodes found for MV grid '{mv_grid_id}'.")

    substations = [nid for nid, ntype in node_rows if ntype == "substation"]
    if len(substations) != 1:
        raise Exception(
            f"MV grid '{mv_grid_id}' must have exactly one node with NodeType='substation' "
            f"to act as the reference bus (found {len(substations)})."
        )
    substation_node_id = substations[0]

    node_ids = [nid for nid, _ in node_rows]
    node_ids.remove(substation_node_id)
    node_ids.insert(0, substation_node_id)
    node_id_to_index = {nid: idx for idx, nid in enumerate(node_ids)}

    cursor.execute(
        """
        SELECT c."ConnectionId", c."FromNodeId", c."ToNodeId", c."CableId", c."Length",
               cb."ImpReal", cb."ImpImag", cb."NomCurr"
        FROM "MVConnection" c
        JOIN "MVCable" cb ON cb."CableId" = c."CableId" AND cb.mv_grid_id = c.mv_grid_id
        WHERE c.mv_grid_id = %s
        """,
        (mv_grid_id,),
    )
    conn_rows = cursor.fetchall()
    if not conn_rows:
        raise Exception(f"No connections found for MV grid '{mv_grid_id}'.")

    branches = [
        MVBranch(
            connection_id=cid, from_node_id=fn, to_node_id=tn, cable_id=cable_id,
            length_m=length, r_ohm_per_km=r, x_ohm_per_km=x, nom_curr_a=nom_curr,
        )
        for cid, fn, tn, cable_id, length, r, x, nom_curr in conn_rows
    ]

    return MVGridTopology(
        mv_grid_id=mv_grid_id,
        nominal_voltage_kv=nominal_voltage_kv,
        substation_node_id=substation_node_id,
        node_id_to_index=node_id_to_index,
        branches=branches,
    )


def branch_admittance(branch: MVBranch, r_override: Optional[float] = None,
                       x_override: Optional[float] = None) -> complex:
    """Y = 1/Z for one branch. R/X are ohm/km; length is metres, converted to
    km before computing Z = (R + jX) * L_km (same convention as
    powerflow/get_grid_info.py::get_grid_admitances)."""
    r = branch.r_ohm_per_km if r_override is None else r_override
    x = branch.x_ohm_per_km if x_override is None else x_override
    z = complex(r, x) * (branch.length_m / 1000.0)
    if z == 0:
        raise Exception(f"Zero impedance for connection '{branch.connection_id}'.")
    return 1 / z


def substation_connected_component(
    node_ids: List[str], branches: List[MVBranch], active_connection_ids: Set[str], substation_node_id: str,
) -> Set[str]:
    """Return the set of node ids reachable from the substation using only the
    given active (in-service) branches. Used both to validate the base grid at
    load time and to determine which nodes survive a topology perturbation
    (see pf_datagen/perturbation.py for why disconnected nodes are dropped
    rather than the whole variant being rejected)."""
    G = nx.Graph()
    G.add_nodes_from(node_ids)
    for b in branches:
        if b.connection_id in active_connection_ids:
            G.add_edge(b.from_node_id, b.to_node_id)
    if substation_node_id not in G:
        return set()
    return nx.node_connected_component(G, substation_node_id)
