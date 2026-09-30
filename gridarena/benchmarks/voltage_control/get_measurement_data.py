"""Helper functions for voltage control router"""

import math
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

# Nominal/band used consistently across difficulty metrics + scoring
NOMINAL_VOLTAGE: float = 230.0
VOLTAGE_BAND: float = 0.05  # ±5%


def _get_violation_snapshots(
    cursor,
    voltage_threshold: float,
    direction: str,
    grids_to_include: Optional[set] = None,
    phase_type: str = None,
):
    """
    Retrieves full measurement snapshots for each grid and timestamp where at least one node
    has a voltage violation (above or below threshold), filtered by grids and phase_type.

    Args:
        direction: "over" for voltage_magnitude > threshold, "under" for < threshold.
    """
    op = ">" if direction == "over" else "<"
    query = f"""
        SELECT DISTINCT m.grid_id, m.datetime
        FROM "Measurements" m
        JOIN "gridusage" gu ON m.grid_id = gu.grid_id
        WHERE m.voltage_magnitude {op} %s
    """
    params: List[Any] = [voltage_threshold]

    if phase_type:
        if phase_type not in ["train", "test"]:
            raise ValueError(f"Unsupported phase type: {phase_type}")
        column_name = f"voltage_control_{phase_type}"
        query += f" AND gu.{column_name} = 1"

    if grids_to_include:
        query += " AND m.grid_id = ANY(%s)"
        params.append(list(grids_to_include))

    cursor.execute(query, params)
    valid_snapshots = cursor.fetchall()
    label = "above" if direction == "over" else "below"
    if not valid_snapshots:
        raise Exception(f"No measurement snapshots found {label} threshold {voltage_threshold}.")

    snapshot_grid_ids = list({s[0] for s in valid_snapshots})
    snapshot_datetimes = list({s[1] for s in valid_snapshots})
    snapshot_set = set(valid_snapshots)

    cursor.execute(
        """
        SELECT m.grid_id, m.node_id, m.phase, m.datetime, m.power_active, m.power_reactive,
               m.voltage_magnitude, m.voltage_angle
        FROM "Measurements" m
        WHERE m.grid_id = ANY(%s) AND m.datetime = ANY(%s)
        ORDER BY m.grid_id, m.datetime, m.node_id, m.phase
        """,
        (snapshot_grid_ids, snapshot_datetimes),
    )

    measurements = [
        row for row in cursor.fetchall()
        if (row[0], row[3]) in snapshot_set
    ]

    return measurements


def get_all_measurements_over(
    cursor,
    voltage_threshold: float = 0.0,
    grids_to_include: Optional[set] = None,
    phase_type: str = None,
):
    return _get_violation_snapshots(cursor, voltage_threshold, "over", grids_to_include, phase_type)


def get_all_measurements_under(
    cursor,
    voltage_threshold: float = 0.0,
    grids_to_include: Optional[set] = None,
    phase_type: str = None,
):
    return _get_violation_snapshots(cursor, voltage_threshold, "under", grids_to_include, phase_type)


def build_load_voltage_timestamp_keys(
    snapshots: Set[Tuple[str, Any]],
    cursor,
) -> Dict[Tuple[str, Any], str]:
    """
    Ensures every (grid_id, datetime) snapshot has a persistent anonymised key.

    Args:
        snapshots: set of (grid_id, datetime)
    Returns:
        mapping: {(grid_id, datetime) -> anonymised_key}
    """
    mapping: Dict[Tuple[str, Any], str] = {}
    for grid_id, dt in snapshots:
        cursor.execute(
            """
            SELECT anonymised_key
            FROM "VoltageTimestampMapping"
            WHERE grid_id = %s AND datetime = %s
            """,
            (grid_id, dt),
        )
        result = cursor.fetchone()
        if result:
            mapping[(grid_id, dt)] = result[0]
        else:
            anon_key = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO "VoltageTimestampMapping" (grid_id, datetime, anonymised_key)
                VALUES (%s, %s, %s)
                """,
                (grid_id, dt, anon_key),
            )
            mapping[(grid_id, dt)] = anon_key
    return mapping


def get_grid_complexity_metrics(cursor, grid_id: str) -> Dict[str, Any]:
    """
    Compute a per-grid complexity profile using topology tables.

    Uses:
      - Node count
      - Connection count
      - Edge density proxy

    Returns:
      {
        "grid_n_nodes": int,
        "grid_n_connections": int,
        "grid_edge_density": float,
        "grid_complexity_raw": float,
        "grid_complexity_norm": float,   # in [0, 1)
      }
    """
    cursor.execute("""SELECT COUNT(*) FROM "Node" WHERE grid_id = %s""", (grid_id,))
    n_nodes = int((cursor.fetchone() or [0])[0] or 0)

    cursor.execute("""SELECT COUNT(*) FROM "Connection" WHERE grid_id = %s""", (grid_id,))
    n_conn = int((cursor.fetchone() or [0])[0] or 0)

    denom = max(n_nodes - 1, 1)
    edge_density = float(n_conn) / float(denom)

    # Raw complexity: grows with size + connectivity; log keeps it sane across scales
    complexity_raw = 0.60 * math.log1p(n_nodes) + 0.40 * math.log1p(n_conn)

    # Normalise to [0, 1)
    complexity_norm = complexity_raw / (1.0 + complexity_raw) if complexity_raw > 0 else 0.0

    return {
        "grid_n_nodes": n_nodes,
        "grid_n_connections": n_conn,
        "grid_edge_density": round(edge_density, 8),
        "grid_complexity_raw": round(float(complexity_raw), 10),
        "grid_complexity_norm": round(float(complexity_norm), 10),
    }


def compute_snapshot_metrics(
    measurements: List[Dict[str, Any]],
    solutions: Optional[List[Dict[str, Any]]] = None,
    nominal_voltage: float = NOMINAL_VOLTAGE,
    band: float = VOLTAGE_BAND,
    grid_complexity_norm: float = 0.0,
    grid_complexity_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compute scenario hardness metrics for difficulty bucketing.

    - severity: count violations and deviation outside band from measurements
    - effort: total |ΔP| relative to total |P| from solutions (if available)
    - residual: violations remaining after solution corrected_voltage (if available)
    - complexity: per-grid topology complexity (node/edge based), normalised to [0,1)

    Returns dict with a single scalar hardness_score and the components.
    """
    low = (1.0 - band) * nominal_voltage
    high = (1.0 + band) * nominal_voltage

    n = 0
    n_viol = 0
    sum_dev = 0.0
    max_dev = 0.0

    # Build original P lookup for effort
    p_by_node_phase: Dict[Tuple[str, str], float] = {}
    sum_abs_p = 0.0

    for m in measurements:
        n += 1
        v = float(m.get("voltage_magnitude", 0.0))
        node_id = str(m.get("node_id"))
        phase = str(m.get("phase"))
        p = float(m.get("power_active", 0.0))

        p_by_node_phase[(node_id, phase)] = p
        sum_abs_p += abs(p)

        dev = 0.0
        if v < low:
            dev = low - v
        elif v > high:
            dev = v - high

        if dev > 0.0:
            n_viol += 1
            sum_dev += dev
            if dev > max_dev:
                max_dev = dev

    severity_norm = (sum_dev / (nominal_voltage * max(n, 1)))  # relative-ish
    viol_rate = n_viol / max(n, 1)

    effort_norm = None
    residual_rate = None
    residual_viol = None

    if solutions:
        sum_abs_dp = 0.0
        res_viol = 0

        for s in solutions:
            node_id = str(s.get("node_id"))
            phase = str(s.get("phase"))

            p_adj = s.get("adjusted_power_active", None)
            v_corr = s.get("corrected_voltage", None)

            if p_adj is not None and (node_id, phase) in p_by_node_phase:
                p0 = float(p_by_node_phase[(node_id, phase)])
                dp = float(p_adj) - p0
                sum_abs_dp += abs(dp)

            if v_corr is not None:
                v = float(v_corr)
                if (v < low) or (v > high):
                    res_viol += 1

        effort_norm = float(sum_abs_dp / (sum_abs_p + 1e-6))
        residual_viol = int(res_viol)
        residual_rate = float(res_viol / max(len(solutions), 1))

        # hardness combines severity + effort + residual + complexity (modest weight)
        hardness = (
            0.45 * float(severity_norm)
            + 0.35 * float(effort_norm)
            + 0.10 * float(residual_rate)
            + 0.10 * float(grid_complexity_norm)
        )
    else:
        # No solutions available: hardness based on severity + violation rate + complexity
        hardness = (
            0.55 * float(severity_norm)
            + 0.30 * float(viol_rate)
            + 0.15 * float(grid_complexity_norm)
        )

    return {
        "n_nodes": n,
        "n_violations": n_viol,
        "violation_rate": round(float(viol_rate), 6),
        "sum_deviation_volts": round(float(sum_dev), 6),
        "max_deviation_volts": round(float(max_dev), 6),
        "severity_norm": round(float(severity_norm), 8),
        "effort_norm": None if effort_norm is None else round(float(effort_norm), 8),
        "residual_violations": residual_viol,
        "residual_rate": None if residual_rate is None else round(float(residual_rate), 8),
        "grid_complexity_norm": round(float(grid_complexity_norm), 10),
        "grid_complexity_profile": grid_complexity_profile,
        "hardness_score": round(float(hardness), 10),
    }


def effort_factor(effort_norm: float) -> float:
    """
    Smooth penalty factor in (0, 1] applied at timestamp level.
    Higher effort_norm (relative total |ΔP|) -> lower factor.

    Tunable: EFFORT_REF controls how quickly score is penalised.
    """
    EFFORT_REF = 0.15  # ~15% relative total adjustment => factor ~ 0.5
    x = max(0.0, float(effort_norm))
    return 1.0 / (1.0 + (x / max(EFFORT_REF, 1e-9)))