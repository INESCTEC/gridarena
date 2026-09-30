"""Helper functions for phase benchmark router"""

import uuid
from typing import Any, Dict, Optional, Literal

from gridarena.benchmarks.general_noise import (
    Difficulty,
    get_profile as _get_profile,
    corrupt_measurement_record as _corrupt_record,
)

def get_all_measurements(cursor, task_type, phase_type):
    valid_grids = set()

    # Apply phase filter (train or test) if specified
    if phase_type:
        phase_column_mapping = {
            'phase_detection': {
                'train': 'phase_detection_train',
                'test': 'phase_detection_test'
            },
            'topology_detection': {
                'train': 'topology_detection_train',
                'test': 'topology_detection_test'
            },
            'voltage_control': {
                'train': 'voltage_control_train',
                'test': 'voltage_control_test'
            }
        }

        # Check if phase_type and task_type are supported
        if task_type not in phase_column_mapping:
            raise ValueError(f"Unsupported task type: {task_type}")

        if phase_type not in ['train', 'test']:
            raise ValueError(f"Unsupported phase type: {phase_type}")

        # Select the right column based on task and phase type
        column_name = phase_column_mapping[task_type][phase_type]

        # Query valid grids for the specific task and phase
        cursor.execute(f"SELECT grid_id FROM gridusage WHERE {column_name} = 1")
        valid_grids = set(row[0] for row in cursor.fetchall())

    # If no valid grids, return early
    if not valid_grids:
        raise Exception("No valid grids found for the specified task and phase.")

    # Convert valid_grids to a list (psycopg3 handles this automatically)
    valid_grids_list = list(valid_grids)

    # Retrieve measurements in batches to limit memory usage
    cursor.execute(
        """
        SELECT grid_id,
               node_id,
               phase,
               datetime,
               power_active,
               power_reactive,
               voltage_magnitude,
               voltage_angle
        FROM "Measurements"
        WHERE grid_id = ANY(%s)
        ORDER BY grid_id, node_id, phase, datetime
        """, (valid_grids_list,)
    )

    BATCH_SIZE = 5000
    measurements = []
    while True:
        batch = cursor.fetchmany(BATCH_SIZE)
        if not batch:
            break
        measurements.extend(batch)

    if not measurements:
        raise Exception("No measurement data found.")

    return measurements


def build_load_anon_keys(measurements, cursor):
    """
    Ensures that all (grid_id, node_id, phase) combinations in the provided measurement
    data are associated with a persistent anonymised key in the database.

    For each unique (grid_id, node_id, phase) tuple:
        - If an anonymised key already exists in the AnonymisedMapping table, it is loaded.
        - If no key exists, a new UUID is generated, stored in the table, and used.

    Parameters:
        measurements (List[Tuple]): A list of measurement records, where each record is
            expected to be a tuple with at least the first three elements:
            (grid_id, node_id, phase, ...).
        cursor (psycopg.Cursor): Active database cursor for querying and inserting mappings.

    Returns:
        dict: A dictionary mapping each (grid_id, node_id, phase) to its anonymised key.

    Raises:
        psycopg.Error: If any database operation fails.

    Example:
        >>> mapping = build_load_anon_keys(measurements, cursor)
        >>> mapping[('grid001', 'N1', 'R')]
        'a312d3c8-d978-4a2a-91b6-9dc4b7d2e1b2'
    """

    mapping = {}  # (grid_id, node_id, phase) → anonymised_key
    unique_keys = set((r[0], r[1], r[2]) for r in measurements)

    for grid_id, node_id, phase in unique_keys:
        cursor.execute(
            """
            SELECT anonymised_key
            FROM "AnonymisedMapping"
            WHERE grid_id = %s AND node_id = %s AND phase = %s
            """,
            (grid_id, node_id, phase),
        )
        result = cursor.fetchone()
        if result:
            mapping[(grid_id, node_id, phase)] = result[0]
        else:
            anon_key = str(uuid.uuid4())
            mapping[(grid_id, node_id, phase)] = anon_key
            cursor.execute(
                """
                INSERT INTO "AnonymisedMapping" (grid_id, node_id, phase, anonymised_key)
                VALUES (%s, %s, %s, %s)
                """,
                (grid_id, node_id, phase, anon_key),
            )

    return mapping

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
