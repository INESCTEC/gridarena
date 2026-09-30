"""Power-flow comparison: run PF on streamed data and compare against true measurements."""

import logging
import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

import gridarena.database as db
import gridarena.powerflow.get_grid_info as gd
from gridarena.digital_twin.schemas import StreamedMeasurementBatch
from gridarena.powerflow.powerflow_algorithm import full_pf

logger = logging.getLogger(__name__)


def run_comparison(
    batch: StreamedMeasurementBatch,
    phase: str,
    voltage_ref: float = 230.0,
) -> dict:
    """Run power flow using streamed measurements and compare against true voltages.

    Returns a metrics dict suitable for insert_digital_twin_result().
    """
    t0 = time.time()
    grid_id = batch.grid_id
    timestamp = batch.timestamp

    phase_measurements = [m for m in batch.measurements if m.phase == phase or m.phase is None]

    conn, cursor = db.get_db_connection()
    try:
        node_id_to_index = gd.get_nodes_from_grid(grid_id, cursor)
        connections, conn_data = gd.get_grid_connections(cursor, grid_id, node_id_to_index)
        admittances = gd.get_grid_admitances(cursor, conn_data)
    finally:
        conn.close()

    n_nodes = len(node_id_to_index)
    S_array = [0 + 0j] * n_nodes
    true_voltages = {}
    missing_count = 0
    invalid_count = 0
    mapped_nodes = set()

    for m in phase_measurements:
        idx = node_id_to_index.get(m.node_id)
        if idx is None:
            invalid_count += 1
            continue
        mapped_nodes.add(m.node_id)

        try:
            p = float(m.power_active)
            q = float(m.power_reactive)
            S_array[idx] = complex(p, q)
        except (ValueError, TypeError):
            invalid_count += 1
            continue

        if m.voltage_magnitude is not None and m.voltage_magnitude > 0:
            true_voltages[m.node_id] = m.voltage_magnitude

    for node_id in node_id_to_index:
        if node_id not in mapped_nodes and node_id != "PT":
            missing_count += 1

    reference_voltage = voltage_ref + 0j
    pt_measurement = next((m for m in phase_measurements if m.node_id == "PT"), None)
    if pt_measurement and pt_measurement.voltage_magnitude > 0:
        reference_voltage = pt_measurement.voltage_magnitude + 0j

    metrics = {
        "timestamp": timestamp,
        "measurements_count": len(phase_measurements),
        "missing_measurements": missing_count,
        "invalid_measurements": invalid_count,
        "powerflow_algorithm": "backward_forward_sweep",
    }

    try:
        volt_values = full_pf(
            np.array(S_array),
            connections,
            np.array(admittances),
            reference_voltage,
        )
        metrics["convergence_status"] = "converged"

        simulated_voltages = {}
        for node_id, idx in node_id_to_index.items():
            simulated_voltages[node_id] = abs(volt_values[idx])

        voltage_errors = []
        for node_id, true_v in true_voltages.items():
            if node_id in simulated_voltages:
                err = abs(simulated_voltages[node_id] - true_v)
                voltage_errors.append(err)

        if voltage_errors:
            metrics["voltage_mae"] = sum(voltage_errors) / len(voltage_errors)
            metrics["voltage_rmse"] = math.sqrt(sum(e ** 2 for e in voltage_errors) / len(voltage_errors))
            metrics["max_voltage_error"] = max(voltage_errors)

        p_errors = []
        for m in phase_measurements:
            idx = node_id_to_index.get(m.node_id)
            if idx is not None and m.node_id != "PT":
                sim_v = volt_values[idx]
                if abs(sim_v) > 0:
                    sim_s = S_array[idx]
                    p_err = abs(sim_s.real - m.power_active)
                    p_errors.append(p_err)

        if p_errors:
            metrics["active_power_error"] = sum(p_errors) / len(p_errors)

        power_by_node = {}
        for m in phase_measurements:
            power_by_node[m.node_id] = {"power_active": m.power_active, "power_reactive": m.power_reactive}

        details = {}
        for node_id, sim_v in simulated_voltages.items():
            entry = {"simulated_voltage": round(sim_v, 4)}
            if node_id in true_voltages:
                entry["true_voltage"] = true_voltages[node_id]
                entry["error"] = round(abs(sim_v - true_voltages[node_id]), 4)
            if node_id in power_by_node:
                entry["power_active"] = power_by_node[node_id]["power_active"]
                entry["power_reactive"] = power_by_node[node_id]["power_reactive"]
            details[node_id] = entry
        metrics["details"] = details

    except Exception as e:
        logger.error("Power flow failed for grid %s: %s", grid_id, e)
        metrics["convergence_status"] = "failed"
        metrics["details"] = {"error": str(e)}

    elapsed_ms = (time.time() - t0) * 1000
    metrics["execution_time_ms"] = round(elapsed_ms, 2)

    return metrics
