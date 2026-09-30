"""Load power measurement data from the database for diffusion model training."""

import logging
from typing import List, Optional, Tuple

import numpy as np

import gridarena.database as db

logger = logging.getLogger(__name__)


def load_power_data_from_db(
    grid_ids: List[str],
    phase: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    p_min: Optional[float] = None,
    p_max: Optional[float] = None,
    require_even_nodes: bool = True,
) -> Tuple[np.ndarray, int, int]:
    """Query Measurements table and return daily snapshot matrices.

    Groups the raw time-series into daily snapshots of shape (n_nodes, n_daily_timesteps).

    Args:
        require_even_nodes: if True (the legacy UNet2D path), an odd node count
            has its last node dropped so the 2D-conv downsampling works. The
            custom permutation-aware backbones never downsample the node axis,
            so callers using them should pass False to keep every node.

    Returns:
        power_snapshots: np.ndarray of shape (n_days, n_nodes, n_daily_timesteps)
        n_nodes: int — number of nodes (after optional even-adjustment)
        n_daily_timesteps: int — inferred measurements per day
    Raises:
        ValueError: if no matching data or insufficient data for at least one full day.
    """
    conn, cursor = db.get_db_connection()
    try:
        sql = """
            SELECT node_id, datetime, power_active
            FROM "Measurements"
            WHERE grid_id = ANY(%s)
        """
        params: list = [grid_ids]

        if phase is not None:
            sql += " AND phase = %s"
            params.append(phase)
        else:
            sql += " AND phase IS NOT NULL"

        if start is not None:
            sql += " AND datetime >= %s"
            params.append(start)
        if end is not None:
            sql += " AND datetime < %s"
            params.append(end)
        if p_min is not None:
            sql += " AND power_active >= %s"
            params.append(p_min)
        if p_max is not None:
            sql += " AND power_active <= %s"
            params.append(p_max)

        sql += " ORDER BY datetime ASC, node_id ASC"

        cursor.execute(sql, params)
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        raise ValueError(
            f"No measurement data found for grids={grid_ids} with the given filters."
        )

    # Build (n_timesteps, n_nodes) matrix
    node_ids = sorted(set(r[0] for r in rows))
    timestamps = sorted(set(r[1] for r in rows))
    node_idx = {nid: i for i, nid in enumerate(node_ids)}
    ts_idx = {ts: i for i, ts in enumerate(timestamps)}

    power_matrix = np.zeros((len(timestamps), len(node_ids)), dtype=np.float64)
    for node_id, dt, p_active in rows:
        power_matrix[ts_idx[dt], node_idx[node_id]] = p_active

    # Remove near-zero columns
    null_mask = np.abs(np.mean(power_matrix, axis=0)) > 1e-8
    power_matrix = power_matrix[:, null_mask]

    if power_matrix.size == 0:
        raise ValueError("All columns were near-zero after filtering.")

    n_nodes = power_matrix.shape[1]

    # The legacy UNet2D backbone requires an even node count — drop last node if
    # odd. Custom backbones (require_even_nodes=False) keep every node.
    if require_even_nodes and n_nodes % 2 != 0:
        logger.info("Odd node count (%d) — dropping last node for UNet2D compatibility", n_nodes)
        power_matrix = power_matrix[:, :-1]
        n_nodes = power_matrix.shape[1]

    # Infer daily timesteps: count unique timestamps on the first day
    dates = sorted(set(ts.date() if hasattr(ts, 'date') else ts for ts in timestamps))
    first_day = dates[0]
    n_daily_timesteps = sum(
        1 for ts in timestamps
        if (ts.date() if hasattr(ts, 'date') else ts) == first_day
    )

    if n_daily_timesteps < 1:
        raise ValueError("Could not infer daily timestep count from the data.")

    n_total = power_matrix.shape[0]
    n_days = n_total // n_daily_timesteps

    if n_days < 1:
        raise ValueError(
            f"Not enough data for a full day: {n_total} timesteps, "
            f"{n_daily_timesteps} per day inferred."
        )

    # Trim to exact multiple of n_daily_timesteps
    usable = n_days * n_daily_timesteps
    power_matrix = power_matrix[:usable, :]

    # Reshape to (n_days, n_nodes, n_daily_timesteps)
    # power_matrix is (usable_timesteps, n_nodes) → transpose to (n_nodes, usable_timesteps)
    # then reshape to (n_nodes, n_days, n_daily_timesteps) and transpose to (n_days, n_nodes, n_daily_timesteps)
    power_snapshots = (
        power_matrix.T
        .reshape(n_nodes, n_days, n_daily_timesteps)
        .transpose(1, 0, 2)
    )

    logger.info(
        "Loaded power data: %d days x %d nodes x %d timesteps/day from %d grids",
        n_days, n_nodes, n_daily_timesteps, len(grid_ids),
    )

    return power_snapshots, n_nodes, n_daily_timesteps
