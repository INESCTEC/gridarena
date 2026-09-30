"""Load grid topology from the database into a GridConfig for the RL environment."""

import logging

import numpy as np

import gridarena.database as db
from gridarena.powerflow.get_grid_info import (
    get_grid_admitances,
    get_grid_connections,
    get_nodes_from_grid,
)
from gridarena.rl.schemas import GridConfig

logger = logging.getLogger(__name__)


def build_grid_config_from_db(
    grid_id: str,
    volt_ref: float = 230.0,
    p_min_kw: float = -20.0,
    p_max_kw: float = 30.0,
    violation_threshold: float = 0.1,
    reward_scale: float = 100.0,
    admittance_scale: float = 1.0,
) -> GridConfig:
    """Fetch grid topology from the DB and return a pure-numpy GridConfig."""
    conn, cursor = db.get_db_connection()
    try:
        node_id_to_index = get_nodes_from_grid(grid_id, cursor)
        connections, conn_data = get_grid_connections(cursor, grid_id, node_id_to_index)
        admittances_raw = get_grid_admitances(cursor, conn_data)
    finally:
        conn.close()

    grid_topology = np.array(connections)
    admittances = admittances_raw.flatten() * admittance_scale
    n_nodes = len(node_id_to_index)

    logger.info(
        "Loaded grid %s: %d nodes, %d edges", grid_id, n_nodes, len(connections),
    )

    return GridConfig(
        grid_topology=grid_topology,
        admittances=admittances,
        n_nodes=n_nodes,
        volt_ref=volt_ref,
        p_min_kw=p_min_kw,
        p_max_kw=p_max_kw,
        violation_threshold=violation_threshold,
        reward_scale=reward_scale,
    )
