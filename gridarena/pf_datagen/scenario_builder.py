"""Builds PF scenarios for an MV grid from a Historical database (see
gridarena/routers/historical.py), with a randomized series-to-point assignment
that's redrawn on a fixed period.

The database's series must all share one grid_level -- that determines the
population strategy:
- "MV": every MV connection point gets its own randomly-drawn MV series;
  that series' own values are the point's injection directly. No dependency
  on any real LV grid being connected.
- "LV": for every MV connection point that has a real LV grid attached
  (get_connected_load_points), that LV grid's node count worth of LV series
  are drawn as "virtual node slots"; the point's injection is their sum --
  mirroring insert_mv_database.py::get_summed_pv()'s "sum across nodes"
  convention, just fed by synthetic per-node curves instead of real ones.
- "Feeder": same connection points as "LV"; the number of connected points
  determines how many Feeder series are drawn (distinct if the database has
  enough, else with replacement) and assigned one-to-one.

The scenario timestamp axis is the database's own declared timeline
(HistoricalTimestamp), downsampled to scenario_count exactly like before.
Every reassignment_period_timesteps consecutive scenarios (in timestamp
order) share one random assignment; crossing into the next block of that
many scenarios redraws it.
"""

from typing import Dict, List, Tuple

import numpy as np


def get_connected_load_points(mv_grid_id: str, cursor) -> List[dict]:
    """MV connection-point nodes that have an LV grid attached via a transformer.

    Returns a list of {"node_id": ..., "lv_grid_id": ...}. Used by the "LV"
    and "Feeder" source types to determine which points to populate (and,
    for "LV", each point's node count).
    """
    cursor.execute(
        """
        SELECT cp."NodeId", t.lv_grid_id
        FROM "MVTransformer" t
        JOIN "MVConnectionPoint" cp
            ON cp."ConnectionPointId" = t."ConnectionPointId" AND cp.mv_grid_id = t.mv_grid_id
        WHERE t.mv_grid_id = %s AND t.lv_grid_id IS NOT NULL
        """,
        (mv_grid_id,),
    )
    return [{"node_id": r[0], "lv_grid_id": r[1]} for r in cursor.fetchall()]


def get_all_mv_connection_points(mv_grid_id: str, cursor) -> List[str]:
    """Every connection point in the grid, regardless of whether it has a
    real LV grid attached. Used by the "MV" source type."""
    cursor.execute('SELECT "NodeId" FROM "MVConnectionPoint" WHERE mv_grid_id = %s', (mv_grid_id,))
    return [r[0] for r in cursor.fetchall()]


def get_historical_source_type(database_id: str, cursor) -> str:
    """The single grid_level shared by every series in the database ("MV",
    "LV", or "Feeder"). Raises if the database is empty or mixes levels."""
    cursor.execute('SELECT DISTINCT grid_level FROM "HistoricalSeries" WHERE database_id = %s', (database_id,))
    levels = {r[0] for r in cursor.fetchall()}
    if not levels:
        raise Exception(f"Historical database '{database_id}' has no series.")
    if len(levels) > 1:
        raise Exception(
            f"Historical database '{database_id}' mixes grid levels ({sorted(levels)}) -- "
            "PF data generation requires every series in the database to share one grid_level."
        )
    return levels.pop()


def get_historical_timeline(database_id: str, cursor) -> List:
    cursor.execute('SELECT datetime FROM "HistoricalTimestamp" WHERE database_id = %s ORDER BY datetime', (database_id,))
    return [r[0] for r in cursor.fetchall()]


def get_historical_series_ids(database_id: str, grid_level: str, cursor) -> List[str]:
    """series_id list for this database/grid_level, restricted to series
    that actually have power data -- a voltage-only series can't supply a
    P/Q injection even if it's tagged the right level."""
    cursor.execute(
        """
        SELECT DISTINCT s.series_id
        FROM "HistoricalSeries" s
        JOIN "HistoricalRecords" r
            ON r.database_id = s.database_id AND r.series_id = s.series_id
        WHERE s.database_id = %s AND s.grid_level = %s AND r.power_active IS NOT NULL
        """,
        (database_id, grid_level),
    )
    return [r[0] for r in cursor.fetchall()]


def fetch_series_values(database_id: str, series_ids: List[str], timestamps: List, cursor) -> Dict[Tuple[str, object], Tuple[float, float]]:
    """Batched lookup: {(series_id, datetime): (power_active, power_reactive)}
    for exactly the given series/timestamps -- bounds memory/time to what's
    actually used, not the database's full history."""
    if not series_ids or not timestamps:
        return {}
    cursor.execute(
        """
        SELECT series_id, datetime, power_active, power_reactive
        FROM "HistoricalRecords"
        WHERE database_id = %s AND series_id = ANY(%s) AND datetime = ANY(%s)
        """,
        (database_id, series_ids, timestamps),
    )
    return {(r[0], r[1]): (r[2] or 0.0, r[3] or 0.0) for r in cursor.fetchall()}


def _lv_node_count(lv_grid_id: str, cursor) -> int:
    cursor.execute('SELECT COUNT(*) FROM "Node" WHERE grid_id = %s', (lv_grid_id,))
    return cursor.fetchone()[0] or 1


def build_scenarios(
    mv_grid_id: str, node_id_to_index: Dict[str, int], scenario_count: int,
    load_noise_sigma: float, historical_database_id: str, reassignment_period_timesteps: int,
    rng: np.random.Generator, cursor,
) -> List[dict]:
    """Returns a list of {"timestamp": str, "S": np.ndarray complex (n_nodes,)}."""
    source_type = get_historical_source_type(historical_database_id, cursor)

    all_timestamps = get_historical_timeline(historical_database_id, cursor)
    if not all_timestamps:
        raise Exception(f"Historical database '{historical_database_id}' has no declared timeline.")

    if len(all_timestamps) > scenario_count:
        idx = sorted(set(np.linspace(0, len(all_timestamps) - 1, scenario_count, dtype=int).tolist()))
        scenario_timestamps = [all_timestamps[i] for i in idx]
    else:
        scenario_timestamps = all_timestamps

    # ── Population set + per-point pool size (LV only: node count; others: 1) ──
    if source_type == "MV":
        target_points = get_all_mv_connection_points(mv_grid_id, cursor)
        point_pool_size = {p: 1 for p in target_points}
    else:
        load_points = get_connected_load_points(mv_grid_id, cursor)
        if not load_points:
            raise Exception(
                f"MV grid '{mv_grid_id}' has no connected LV grids -- required for "
                f"grid_level='{source_type}' sourcing (use a grid_level='MV' database instead "
                "if you don't have real LV connections)."
            )
        target_points = [lp["node_id"] for lp in load_points]
        if source_type == "LV":
            point_pool_size = {lp["node_id"]: _lv_node_count(lp["lv_grid_id"], cursor) for lp in load_points}
        else:  # "Feeder"
            point_pool_size = {p: 1 for p in target_points}

    series_ids = get_historical_series_ids(historical_database_id, source_type, cursor)
    if not series_ids:
        raise Exception(
            f"No usable '{source_type}' series (with power data) found in historical "
            f"database '{historical_database_id}'."
        )

    # ── Chunk scenarios by reassignment period (every N scenarios, in timestamp
    # order), draw one assignment per chunk ──
    chunk_of_index = [i // reassignment_period_timesteps for i in range(len(scenario_timestamps))]
    chunks = sorted(set(chunk_of_index))

    chunk_assignments: Dict[int, Dict[str, List[str]]] = {}
    all_used_series = set()
    for c in chunks:
        assignment: Dict[str, List[str]] = {}
        if source_type == "Feeder":
            replace = len(series_ids) < len(target_points)
            chosen = rng.choice(series_ids, size=len(target_points), replace=replace)
            for p, s in zip(target_points, chosen):
                assignment[p] = [s]
        else:
            for p in target_points:
                n = point_pool_size[p]
                chosen = rng.choice(series_ids, size=n, replace=True)
                assignment[p] = chosen.tolist()
        chunk_assignments[c] = assignment
        all_used_series.update(s for slots in assignment.values() for s in slots)

    values = fetch_series_values(historical_database_id, list(all_used_series), scenario_timestamps, cursor)

    n_nodes = len(node_id_to_index)
    scenarios = []
    for i, ts in enumerate(scenario_timestamps):
        S = np.zeros(n_nodes, dtype=complex)
        assignment = chunk_assignments[chunk_of_index[i]]
        for point, slot_series in assignment.items():
            idx = node_id_to_index.get(point)
            if idx is None:
                continue
            p_sum, q_sum = 0.0, 0.0
            for s in slot_series:
                p, q = values.get((s, ts), (0.0, 0.0))
                p_sum += p
                q_sum += q
            if load_noise_sigma > 0:
                factor = rng.uniform(1 - load_noise_sigma, 1 + load_noise_sigma)
                p_sum, q_sum = p_sum * factor, q_sum * factor
            S[idx] = complex(p_sum, q_sum)
        scenarios.append({"timestamp": str(ts), "S": S})

    return scenarios
