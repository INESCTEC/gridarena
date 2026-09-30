"""Helper functions for topology benchmark router"""

import uuid
from typing import Any, Dict, List, Tuple, Optional, Set

from gridarena.benchmarks.general_noise import (
    Difficulty,
    get_profile as _get_profile,
    corrupt_measurement_record as _corrupt_record,
)

def ensure_grid_anon_map_database(cursor) -> None:
    """
    Creates the persistent mapping table if it doesn't exist.
    """
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "GridAnonymisedMapping" (
            grid_id TEXT PRIMARY KEY,
            anonymised_grid_key TEXT UNIQUE NOT NULL
        )
        """
    )


def build_load_grid_anon_keys_for_grids(cursor, grid_ids: Set[str]) -> Dict[str, str]:
    """
    Ensures every grid_id in grid_ids has a persistent anonymised key.
    Returns:
        { real_grid_id -> anonymised_grid_key }
    """
    mapping: Dict[str, str] = {}

    for grid_id in grid_ids:
        cursor.execute(
            """
            SELECT anonymised_grid_key
            FROM "GridAnonymisedMapping"
            WHERE grid_id = %s
            """,
            (grid_id,),
        )
        row = cursor.fetchone()

        if row and row[0]:
            mapping[grid_id] = row[0]
            continue

        anon_key = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO "GridAnonymisedMapping" (grid_id, anonymised_grid_key)
            VALUES (%s, %s)
            ON CONFLICT (grid_id)
            DO UPDATE SET anonymised_grid_key = EXCLUDED.anonymised_grid_key
            """,
            (grid_id, anon_key),
        )
        mapping[grid_id] = anon_key

    return mapping


def get_real_grid_id_from_anon(cursor, anon_grid_id: str) -> str:
    """
    Maps anonymised_grid_key -> real grid_id.
    Raises ValueError if anon_grid_id is not found in mapping.
    """
    cursor.execute(
        """
        SELECT grid_id
        FROM "GridAnonymisedMapping"
        WHERE anonymised_grid_key = %s
        """,
        (anon_grid_id,),
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"Invalid anonymised grid ID: {anon_grid_id}")
    return row[0]


def resolve_real_grid_id(cursor, maybe_anon_or_real: str) -> str:
    """
    If maybe_anon_or_real is an anonymised key, return the real grid_id.
    Otherwise, assume it's already a real grid_id and return unchanged.

    (This keeps backwards compatibility: you can still submit/score using real IDs.)
    """
    cursor.execute(
        """
        SELECT grid_id
        FROM "GridAnonymisedMapping"
        WHERE anonymised_grid_key = %s
        """,
        (maybe_anon_or_real,),
    )
    row = cursor.fetchone()
    if row:
        return row[0]
    return maybe_anon_or_real


def get_nodes_for_all_grids(cursor) -> Dict[str, Dict[str, int]]:
    """
    Returns, for all grids, the mapping node_id -> index.
    Ensures 'PT' (if it exists) is at index 0 of each grid.
    Structure:
        {
          grid_id: { node_id: index, ... },
          ...
        }
    """
    # Note the quoted identifiers: "Node" and "NodeId"
    cursor.execute('SELECT grid_id, "NodeId" FROM "Node"')
    rows = cursor.fetchall()
    if not rows:
        raise Exception("No nodes found in any grid.")

    # Aggregate nodes by grid
    nodes_per_grid: Dict[str, List[str]] = {}
    for grid_id, node_id in rows:
        nodes_per_grid.setdefault(grid_id, []).append(node_id)

    # Build mapping per grid, ensuring 'PT' comes first
    node_idx_maps: Dict[str, Dict[str, int]] = {}
    for grid_id, node_ids in nodes_per_grid.items():
        # remove duplicates while preserving order
        seen = set()
        unique_nodes = [n for n in node_ids if not (n in seen or seen.add(n))]

        if not unique_nodes:
            raise Exception(f"No nodes found for grid_id={grid_id}.")

        if "PT" in unique_nodes:
            unique_nodes.remove("PT")
            unique_nodes.insert(0, "PT")

        node_idx_maps[grid_id] = {node_id: idx for idx, node_id in enumerate(unique_nodes)}

    return node_idx_maps


def get_grid_connections_for_all(cursor, node_id_to_index_per_grid: Dict[str, Dict[str, int]], grids_to_include: set) -> Tuple[
    Dict[str, List[List[int]]],
    Dict[str, List[Tuple[str, float]]]
]:
    """
    Returns the connections and metadata for ALL grids, using the already computed indices.
    Filters the connections to only include grids in grids_to_include.
    
    Structures:
        connections_per_grid: { grid_id: [[from_idx, to_idx], ...], ... }
        conn_data_per_grid:   { grid_id: [(cable_id, length), ...], ... }
    """
    cursor.execute(
        'SELECT grid_id, "FromNodeId", "ToNodeId", "CableId", "Length" FROM "Connection"'
    )
    rows = cursor.fetchall()
    if not rows:
        raise Exception("No connections found in any grid.")

    connections_per_grid: Dict[str, List[List[int]]] = {}
    conn_data_per_grid: Dict[str, List[Tuple[str, float]]] = {}

    # Filter connections by the grids in grids_to_include first
    for grid_id, from_node, to_node, cable_id, length in rows:
        if grid_id not in grids_to_include:
            continue  # Skip grids that are not in the list of grids_to_include
        
        # After filtering by grids_to_include, check if the node index map exists
        if grid_id not in node_id_to_index_per_grid:
            raise Exception(f"No node index map for grid_id={grid_id}. Compute nodes first.")

        idx_map = node_id_to_index_per_grid[grid_id]

        try:
            from_idx = idx_map[from_node]
            to_idx = idx_map[to_node]
        except KeyError as e:
            raise Exception(
                f"Node '{e.args[0]}' referenced in Connection but not found in Node for grid_id={grid_id}."
            )

        connections_per_grid.setdefault(grid_id, []).append([from_idx, to_idx])
        conn_data_per_grid.setdefault(grid_id, []).append((cable_id, float(length)))

    # Optional: validate that each grid in grids_to_include has at least one connection
    for grid_id in grids_to_include:
        if grid_id not in connections_per_grid:
            raise Exception(f"No connections found for grid_id={grid_id}.")

    return connections_per_grid, conn_data_per_grid



def get_all_grids_topology(cursor, grids_to_include=None) -> Tuple[
    Dict[str, Dict[str, int]],
    Dict[str, List[List[int]]],
    Dict[str, List[Tuple[str, float]]]
]:
    """
    High-level function that returns, for the specified grids:
      - node_id_to_index_per_grid
      - connections_per_grid
      - conn_data_per_grid

    :param grids_to_include: A set of grid_ids to include in the output. If None, all grids are included.
    """
    node_idx_maps = get_nodes_for_all_grids(cursor)

    # Filter out grids that are not in the grids_to_include list (if provided)
    if grids_to_include:
        node_idx_maps = {grid_id: idx_map for grid_id, idx_map in node_idx_maps.items() if grid_id in grids_to_include}

    connections_map, conn_data_map = get_grid_connections_for_all(cursor, node_idx_maps, grids_to_include)
    
    # Filter the connections and conn_data to include only the selected grids
    if grids_to_include:
        connections_map = {grid_id: connections_map[grid_id] for grid_id in grids_to_include}
        conn_data_map = {grid_id: conn_data_map[grid_id] for grid_id in grids_to_include}

    return node_idx_maps, connections_map, conn_data_map


# ----------------------------
# Corruption / difficulty logic
# Now delegated to gridarena.benchmarks.general_noise
# ----------------------------

def get_corruption_profile(
    difficulty: Difficulty,
    noise_scale: Optional[float] = None,
    outlier_prob: Optional[float] = None,
    outlier_scale: Optional[float] = None,
) -> Dict[str, float]:
    return _get_profile(
        difficulty,
        noise_scale=noise_scale,
        outlier_prob=outlier_prob,
        outlier_scale=outlier_scale,
    )


def corrupt_measurement_record(
    record: Dict[str, Any],
    rng,
    profile: Dict[str, float],
) -> Dict[str, Any]:
    # Keep the same public signature your routers already use.
    return _corrupt_record(record, rng, profile)