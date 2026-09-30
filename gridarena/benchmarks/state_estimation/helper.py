"""Helper function for state estimation benchmarks"""

import hashlib
import random
import uuid
from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple

import numpy as np

from gridarena.benchmarks.general_noise import Difficulty as NoiseDifficulty
from gridarena.benchmarks.general_noise import (
    corrupt_measurement_record as _corrupt_record,
)
from gridarena.benchmarks.general_noise import get_profile as _get_profile
from gridarena.benchmarks.general_noise import get_series_rng


def _all_grid_ids(cursor) -> List[str]:
    cursor.execute("""SELECT DISTINCT grid_id FROM "Measurements" """)
    return [r[0] for r in cursor.fetchall()]


def _new_unique_mask(cursor, table: str, col: str) -> str:
    """Create an 10-hex masked id unique within the given table/col."""

    while True:
        m = uuid.uuid4().hex[:10]
        cursor.execute(f"SELECT 1 FROM {table} WHERE {col} = %s", (m,))
        if cursor.fetchone() is None:
            return m


def ensure_grid_masks(cursor):
    """Ensure all grids have the unique mask identifier."""

    for gid in _all_grid_ids(cursor):
        cursor.execute(
            """SELECT masked_id FROM GridMask \
                       WHERE grid_id = %s""",
            (gid,),
        )
        if cursor.fetchone() is None:
            masked = _new_unique_mask(cursor, table="GridMask", col="masked_id")
            cursor.execute(
                """INSERT INTO GridMask (grid_id, masked_id) \
                    VALUES (%s, %s)""",
                (gid, masked),
            )


def ensure_all_node_masks(cursor):
    """Ensure NodeMask exists for every (grid_id, node_id)."""

    cursor.execute(
        """SELECT DISTINCT grid_id, node_id, phase \
                   FROM "Measurements" """
    )
    for gid, nid, phase in cursor.fetchall():
        cursor.execute(
            """
            SELECT masked_node_id
            FROM NodeMask
            WHERE grid_id = %s AND node_id = %s AND phase = %s
            """,
            (gid, nid, phase),
        )
        if cursor.fetchone() is None:
            masked = _new_unique_node_mask(cursor, gid)
            cursor.execute(
                """
                INSERT INTO NodeMask (grid_id, node_id, phase, masked_node_id)
                VALUES (%s, %s, %s, %s)
                """,
                (gid, nid, phase, masked),
            )


def _new_unique_node_mask(cursor, grid_id: str) -> str:
    """Create an 10-hex masked node id unique within a grid."""

    while True:
        m = uuid.uuid4().hex[:10]
        cursor.execute(
            """
            SELECT 1
            FROM NodeMask
            WHERE grid_id = %s AND masked_node_id = %s
            """,
            (grid_id, m),
        )
        if cursor.fetchone() is None:
            return m


def iter_grids_with_masks(cursor) -> Iterator[Tuple[str, str]]:
    """Query database for mapping grid_id <-> masked_id."""

    cursor.execute("""SELECT grid_id, masked_id FROM GridMask""")
    for gid, mid in cursor.fetchall():
        yield gid, mid


def get_random_grid(cursor) -> str:
    # Get only the grids marked for testing (state_estimation_test = 1)
    cursor.execute(
        """
        SELECT grid_id
        FROM GridUsage
        WHERE state_estimation_test = 1
    """
    )
    grids_for_testing = [row[0] for row in cursor.fetchall()]

    if not grids_for_testing:
        raise ValueError("No grids available for state estimation testing")

    return str(random.choice(grids_for_testing))


def get_masked_grid(cursor, grid_id: str) -> str:
    """Get the masked id from the randomly selected grid."""

    cursor.execute("""SELECT masked_id FROM GridMask WHERE grid_id = %s""", (grid_id,))
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"No masked grid for grid_id={grid_id}")
    return row[0]


def get_open_task_for_user(cursor, user_id: str) -> Optional[Dict[str, Any]]:
    """Return this user's not-yet-submitted estimation task, if any.

    An EstimationTasks row group (one row per node) is "open" until a
    matching submission lands in StateEstimates via POST /submit-estimates.
    Used so GET /state-data is idempotent: repeated calls before submitting
    return the same task instead of minting a new one every time.
    """
    cursor.execute(
        """
        SELECT DISTINCT et.estimation_id, et.grid_id, et.timestamp
        FROM EstimationTasks et
        WHERE et.user_id = %s
          AND NOT EXISTS (
              SELECT 1 FROM StateEstimates se
              WHERE se.user_id = et.user_id AND se.estimation_id = et.estimation_id
          )
        LIMIT 1
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {"estimation_id": row[0], "grid_id": row[1], "timestamp": row[2]}


def random_timestamp_for_grid(cursor, grid_id: str) -> str:
    """Select random timestamp from the selected grid"""

    cursor.execute(
        """SELECT DISTINCT datetime FROM "Measurements" WHERE grid_id = %s""",
        (grid_id,),
    )
    ts_list = [r[0] for r in cursor.fetchall()]
    if not ts_list:
        raise ValueError(f"No timestamps available for grid_id {grid_id}")
    return random.choice(ts_list)


ObservabilityDifficulty = Literal["clean", "easy", "medium", "hard"]

# Observability is defined by NON-observable fraction ranges.
_OBS_PROFILES: Dict[str, Dict[str, float]] = {
    "clean": {"min_non_obs_frac": 0.0, "max_non_obs_frac": 0.0, "unknown_history_hours": 0.0},
    "easy": {"min_non_obs_frac": 0.0, "max_non_obs_frac": 1.0 / 3.0, "unknown_history_hours": 1.0},
    "medium": {
        "min_non_obs_frac": 1.0 / 3.0,
        "max_non_obs_frac": 2.0 / 3.0,
        "unknown_history_hours": 6.0,
    },
    "hard": {
        "min_non_obs_frac": 2.0 / 3.0,
        "max_non_obs_frac": 0.999,
        "unknown_history_hours": 12.0,
    },
}


def get_noise_profile(difficulty: NoiseDifficulty) -> Dict[str, float]:
    # Kept for backward-compatibility with your router.
    return _get_profile(difficulty)


def get_observability_profile(difficulty: ObservabilityDifficulty) -> Dict[str, float]:
    if difficulty not in _OBS_PROFILES:
        raise ValueError(f"Unsupported observability difficulty: {difficulty}")
    return dict(_OBS_PROFILES[difficulty])


def corrupt_measurement_like_record(
    record: Dict[str, Any],
    rng: random.Random,
    profile: Dict[str, float],
) -> Dict[str, Any]:
    # Backward-compatible wrapper name used internally in this module.
    return _corrupt_record(record, rng, profile)


def corrupt_training_dataset(
    grids: Dict[str, Dict[str, List[Dict[str, Any]]]],
    noise_profile: Dict[str, float],
    difficulty: str = "clean",
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    rngs: Dict[tuple, random.Random] = {}
    out: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for mgid, nodes in grids.items():
        out[mgid] = {}
        for mnid, series in nodes.items():
            seed = hashlib.sha256(f"{mgid}:{mnid}:{difficulty}:training".encode()).hexdigest()
            rng_key = (mgid, mnid, "training")
            if rng_key not in rngs:
                rngs[rng_key] = random.Random(seed)
            out[mgid][mnid] = [
                corrupt_measurement_like_record(rec, rngs[rng_key], noise_profile) for rec in series
            ]
    return out


def corrupt_estimation_input(
    known_nodes: Dict[str, Dict[str, Any]],
    measurement_data: Dict[str, List[Dict[str, Any]]],
    noise_profile: Dict[str, float],
    masked_grid_id: str,
    estimation_id: str,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    rngs: Dict[tuple, random.Random] = {}
    out_known: Dict[str, Dict[str, Any]] = {}
    out_hist: Dict[str, List[Dict[str, Any]]] = {}

    for mnid, rec in known_nodes.items():
        rng = get_series_rng(rngs, (masked_grid_id, mnid, estimation_id, "known"))
        out_known[mnid] = corrupt_measurement_like_record(rec, rng, noise_profile)

    for mnid, series in measurement_data.items():
        rng = get_series_rng(rngs, (masked_grid_id, mnid, estimation_id, "history"))
        out_hist[mnid] = [
            corrupt_measurement_like_record(rec, rng, noise_profile) for rec in series
        ]

    return out_known, out_hist


def _pick_unknown_count(
    n_nodes: int,
    observability: ObservabilityDifficulty,
    rng: random.Random,
) -> int:
    """
    Picks number of NON-observable nodes (unknown at target timestamp) according to:
      clean:  0 unknown
      easy:   [0, 1/3)
      medium: [1/3, 2/3)
      hard:   [2/3, ~1)
    For easy/medium/hard, enforces at least 1 unknown and 1 known when n_nodes >= 2.
    """
    obs = get_observability_profile(observability)

    if observability == "clean":
        return 0

    min_f = float(obs["min_non_obs_frac"])
    max_f = float(obs["max_non_obs_frac"])

    f = rng.uniform(min_f, max_f)  # in [min_f, max_f)
    n_unknown = int(round(f * n_nodes))

    if n_nodes >= 2:
        n_unknown = max(1, min(n_unknown, n_nodes - 1))
    else:
        n_unknown = 0

    return n_unknown


def create_estimation_task(
    cursor,
    grid_id: str,
    timestamp: str,
    user_id: str,
    observability: ObservabilityDifficulty = "medium",
):
    cursor.execute(
        """
        SELECT DISTINCT node_id, phase
        FROM "Measurements"
        WHERE grid_id = %s AND datetime = %s
        ORDER BY node_id
        """,
        (grid_id, timestamp),
    )
    nodes = [nodes_info for nodes_info in cursor.fetchall()]
    n_nodes = len(nodes)

    # Non-deterministic split (changes each call), like phase/topology corruption
    split_rng = random.Random()

    n_unknown = _pick_unknown_count(n_nodes, observability, split_rng)

    nodes_shuffled = list(nodes)
    split_rng.shuffle(nodes_shuffled)
    unknown_set = set(nodes_shuffled[:n_unknown])

    chosen_estimation_id = uuid.uuid4().hex[:10]

    for node_id, phase in nodes:
        known = 0 if (node_id, phase) in unknown_set else 1
        cursor.execute(
            """
            INSERT INTO EstimationTasks (
              user_id, estimation_id, grid_id, timestamp, node_id, phase, known
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (user_id, chosen_estimation_id, grid_id, timestamp, node_id, phase, known),
        )

    return chosen_estimation_id


def get_actual_state(
    cursor,
    estimation_id: str,
    unknown_history_seconds: int = 60 * 60 * 12,
    known_history_seconds: int = 1,
):
    # Fetch task nodes + their masks in a single JOIN
    cursor.execute(
        """
        SELECT et.grid_id, et.timestamp, et.node_id, et.phase, et.known,
               nm.masked_node_id
        FROM EstimationTasks et
        JOIN NodeMask nm ON nm.grid_id = et.grid_id
                        AND nm.node_id = et.node_id
                        AND nm.phase = et.phase
        WHERE et.estimation_id = %s
        ORDER BY et.node_id
        """,
        (estimation_id,),
    )
    nodes = cursor.fetchall()

    if not nodes:
        return {}, {}

    # Collect known nodes for batch measurement fetch
    grid_id = nodes[0][0]
    target_ts = nodes[0][1]
    known_keys = []
    unknown_keys = []

    for _gid, _ts, node_id, phase, known, mask_node in nodes:
        if known == 1:
            known_keys.append((node_id, phase, mask_node))
        else:
            unknown_keys.append((node_id, phase, mask_node))

    actual_state = {}

    # Batch fetch measurements for known nodes at target timestamp
    if known_keys:
        known_node_ids = [k[0] for k in known_keys]
        known_phases = [k[1] for k in known_keys]
        cursor.execute(
            """
            SELECT node_id, phase, power_active, power_reactive,
                   voltage_magnitude, voltage_angle
            FROM "Measurements"
            WHERE grid_id = %s AND datetime = %s
              AND (node_id, phase) IN (
                  SELECT unnest(%s::text[]), unnest(%s::text[])
              )
            """,
            (grid_id, target_ts, known_node_ids, known_phases),
        )
        meas_map = {(r[0], r[1]): r[2:] for r in cursor.fetchall()}

        for node_id, phase, mask_node in known_keys:
            measurement = meas_map.get((node_id, phase))
            if measurement is None:
                raise ValueError(
                    f"No measurement for known node {node_id} phase {phase} at {target_ts}"
                )
            actual_state[mask_node] = {
                "power_active": measurement[0],
                "power_reactive": measurement[1],
                "voltage_magnitude": measurement[2],
                "voltage_angle": measurement[3],
            }

    # Batch fetch history for known nodes
    historic_data = {}
    if known_keys:
        k_node_ids = [k[0] for k in known_keys]
        k_phases = [k[1] for k in known_keys]
        cursor.execute(
            """
            SELECT node_id, phase, datetime, power_active, power_reactive,
                   voltage_magnitude, voltage_angle
            FROM "Measurements"
            WHERE grid_id = %s AND phase = ANY(%s) AND node_id = ANY(%s)
              AND datetime < %s - make_interval(secs => %s)
            """,
            (grid_id, k_phases, k_node_ids, target_ts, int(known_history_seconds)),
        )
        for row in cursor.fetchall():
            nid, ph = row[0], row[1]
            mask_node = next(m for n, p, m in known_keys if n == nid and p == ph)
            historic_data.setdefault(mask_node, []).append({
                "datetime": row[2],
                "power_active": row[3],
                "power_reactive": row[4],
                "voltage_magnitude": row[5],
                "voltage_angle": row[6],
            })

    # Batch fetch history for unknown nodes
    if unknown_keys:
        u_node_ids = [k[0] for k in unknown_keys]
        u_phases = [k[1] for k in unknown_keys]
        cursor.execute(
            """
            SELECT node_id, phase, datetime, power_active, power_reactive,
                   voltage_magnitude, voltage_angle
            FROM "Measurements"
            WHERE grid_id = %s AND phase = ANY(%s) AND node_id = ANY(%s)
              AND datetime < %s - make_interval(secs => %s)
            """,
            (grid_id, u_phases, u_node_ids, target_ts, int(unknown_history_seconds)),
        )
        for row in cursor.fetchall():
            nid, ph = row[0], row[1]
            mask_node = next(m for n, p, m in unknown_keys if n == nid and p == ph)
            historic_data.setdefault(mask_node, []).append({
                "datetime": row[2],
                "power_active": row[3],
                "power_reactive": row[4],
                "voltage_magnitude": row[5],
                "voltage_angle": row[6],
            })

    # Ensure all nodes have an entry in historic_data (even if empty)
    for _, _, mask_node in known_keys + unknown_keys:
        historic_data.setdefault(mask_node, [])

    return actual_state, historic_data


def resolve_grid_id_from_mask(cursor, masked_grid_id):

    cursor.execute(
        """
        SELECT grid_id
        FROM GridMask
        WHERE masked_id = %s
        """,
        (masked_grid_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Masked grid id {masked_grid_id} not found")
    return row[0]


def resolve_node_id_from_mask(cursor, grid_id, masked_node_id):
    cursor.execute(
        """
        SELECT node_id, phase
        FROM NodeMask
        WHERE grid_id = %s AND masked_node_id = %s
        """,
        (grid_id, masked_node_id),
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Masked node id {masked_node_id} not found")
    node_id, phase = row
    return node_id, phase


def get_predicted_voltages(cursor, user_id, estimation_id):

    cursor.execute(
        """
        SELECT node_id, phase, voltage_magnitude, voltage_angle
        FROM StateEstimates
        WHERE user_id = %s AND estimation_id = %s
        """,
        (user_id, estimation_id),
    )

    data = cursor.fetchall()

    voltage_prediction = []
    voltage_angles = []

    for node_id, phase, v_mag, v_ang in data:
        voltage_prediction.append(v_mag)
        voltage_angles.append(v_ang)

    return np.asarray(voltage_prediction), np.asarray(voltage_angles)


def get_real_voltages(cursor, user_id, estimation_id):

    cursor.execute(
        """
        SELECT et.grid_id, et.timestamp, et.node_id, et.phase,
               m.voltage_magnitude, m.voltage_angle
        FROM EstimationTasks et
        JOIN "Measurements" m
          ON m.grid_id = et.grid_id
         AND m.node_id = et.node_id
         AND m.datetime = et.timestamp
         AND m.phase = et.phase
        WHERE et.user_id = %s AND et.estimation_id = %s AND et.known = 0
        ORDER BY et.node_id, et.phase
        """,
        (user_id, estimation_id),
    )

    data = cursor.fetchall()

    voltage_meas = [row[4] for row in data]
    voltage_angs = [row[5] for row in data]

    return np.asarray(voltage_meas), np.asarray(voltage_angs)


def get_state_estimation_score(predict_voltage, predict_angles, true_voltage, true_angles):

    v_mag_diff = np.mean((predict_voltage - true_voltage) ** 2)
    ang_dif = np.mean(np.abs(np.sin(predict_angles - true_angles)))

    return v_mag_diff + ang_dif


def insert_state_estimation(cursor, submission, node_id_data, real_data):

    v_mag = node_id_data.voltage_magnitude
    v_ang = node_id_data.voltage_angle

    user_id = submission.user_id
    estimation_id = submission.estimation_id
    timestamp = submission.timestamp

    real_gid, real_nid, phase = real_data

    cursor.execute(
        """
        INSERT INTO StateEstimates (
            user_id, estimation_id, grid_id, timestamp, node_id, phase,
            voltage_magnitude, voltage_angle
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, estimation_id, grid_id, timestamp, node_id, phase)
        DO UPDATE SET
            voltage_magnitude = EXCLUDED.voltage_magnitude,
            voltage_angle = EXCLUDED.voltage_angle
        """,
        (
            user_id,
            estimation_id,
            real_gid,
            timestamp,
            real_nid,
            phase,
            v_mag,
            v_ang,
        ),
    )
