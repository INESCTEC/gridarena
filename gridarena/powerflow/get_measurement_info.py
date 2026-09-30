"""Powerflow Endpoint Helper Functions for Measurement Data Retrieval"""

import math

import numpy as np


def get_measurement_from_timestamp(cursor, grid_id, node_id_to_index, timestamp, phase):
    """
    Retrieves complex power measurements (S = P + jQ) for each node in a given grid
    at a specific timestamp and phase.

    Parameters:
        cursor (psycopg.Cursor): Active database cursor for executing queries.
        grid_id (str): Identifier of the grid to filter measurements.
        node_id_to_index (dict): Mapping from node IDs to their corresponding index positions.
        timestamp (str): ISO 8601 formatted timestamp (e.g. '2024-08-20T14:00:00') at which to retrieve measurements.
        phase (str): Phase identifier ("R", "S", or "T") to filter measurements.

    Returns:
        np.ndarray: Complex-valued numpy array (dtype=complex) of shape (N,), where N is the number of nodes.
                    Each entry corresponds to the complex power (P + jQ) for that node.
                    Nodes with no data at the given timestamp are left as 0+0j.

    Example:
        >>> get_measurement_from_timestamp(cursor, "grid001", {"N1": 0, "N2": 1}, "2024-08-20T14:00:00", "R")
        array([100.+30.j,  85.+20.j])
    """

    cursor.execute(
        """
        SELECT node_id, power_active, power_reactive
        FROM "Measurements"
        WHERE grid_id = %s AND datetime = %s AND phase = %s
        """,
        (grid_id, timestamp, phase),
    )

    measurement_rows = cursor.fetchall()
    S_array = np.zeros(len(node_id_to_index), dtype=complex)

    for node_id, p, q in measurement_rows:
        S_array[node_id_to_index[node_id]] = complex(p, q)

    return S_array


def get_pt_voltage(cursor, grid_id, timestamp, phase):
    """
    Retrieves the complex voltage value at the reference node 'PT' for a given grid,
    timestamp, and electrical phase.

    Parameters:
        cursor (psycopg.Cursor): Active database cursor for executing queries.
        grid_id (str): Identifier of the grid from which to retrieve the reference voltage.
        timestamp (str): ISO 8601 formatted datetime string (e.g. '2024-08-20T14:00:00').
        phase (str): Phase identifier ("R", "S", or "T") to filter the voltage measurement.

    Returns:
        complex: Complex voltage at node 'PT' computed from the magnitude and phase angle,
                 in the form V = magnitude × exp(jθ), where θ is in radians.

    Raises:
        Exception: If no voltage measurement is found for node 'PT' at the given parameters.

    Example:
        >>> get_pt_voltage(cursor, "grid001", "2024-08-20T14:00:00", "R")
        (230.0+5.0j)
    """

    cursor.execute(
        """
        SELECT voltage_magnitude, voltage_angle
        FROM "Measurements"
        WHERE grid_id = %s AND node_id = 'PT'
          AND datetime = %s AND phase = %s
        """,
        (grid_id, timestamp, phase),
    )

    row = cursor.fetchone()
    if not row:
        raise Exception("Reference node PT not found.")

    mag, ang_deg = row
    return mag * np.exp(1j * math.radians(ang_deg))
