"""Top-level picklable entry point for the MV PF data-generation background job.

Runs in a spawned subprocess (see pf_datagen/run_manager.py): loads its
run_config.json, builds the grid + historical scenarios once, builds the
requested topology variants once, then solves every (topology variant x
historical scenario) pair with the canonical backward/forward-sweep solver,
batching inserts into the MVPFScenario* tables every `chunk_commit_size`
scenarios.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def _update_run_config(run_dir: str, updates: dict) -> None:
    config_path = Path(run_dir) / "run_config.json"
    with open(config_path) as f:
        data = json.load(f)
    data.update(updates)
    with open(config_path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def run_pf_datagen(run_dir: str) -> dict:
    import gridarena.database as db
    from gridarena.pf_datagen.grid_loader import branch_admittance, get_mv_grid_topology
    from gridarena.pf_datagen.perturbation import build_variants, perturb_admittances
    from gridarena.pf_datagen.schemas import PFDataGenRequest
    from gridarena.pf_datagen.scenario_builder import build_scenarios
    from gridarena.pf_datagen.ybus import build_ybus_entries
    from gridarena.powerflow.powerflow_algorithm import full_pf

    run_path = Path(run_dir)
    with open(run_path / "run_config.json") as f:
        run_data = json.load(f)

    _update_run_config(run_dir, {"status": "running"})

    try:
        mv_grid_id = run_data["mv_grid_id"]
        request = PFDataGenRequest(**{k: run_data[k] for k in PFDataGenRequest.model_fields if k in run_data})

        seed = request.seed if request.seed is not None else int(np.random.SeedSequence().entropy % (2**32))
        rng = np.random.default_rng(seed)

        conn, cursor = db.get_db_connection()
        try:
            db.create_mv_database(conn, cursor)
            db.create_pf_datagen_database(conn, cursor)
            topology = get_mv_grid_topology(mv_grid_id, cursor)
            node_ids = list(topology.node_id_to_index.keys())
            scenarios = build_scenarios(
                mv_grid_id, topology.node_id_to_index, request.scenario_count,
                request.load_noise_sigma, request.historical_database_id,
                request.reassignment_period_timesteps, rng, cursor,
            )
        finally:
            conn.close()

        variants = build_variants(
            request.topology_perturbation, topology.branches, node_ids,
            topology.substation_node_id, rng,
        )

        ref_voltage = complex(topology.nominal_voltage_kv * 1000.0, 0.0)
        all_connection_ids = {b.connection_id for b in topology.branches}

        total = len(scenarios) * len(variants)
        completed = 0
        failed = 0
        pending_bus, pending_branch, pending_ybus, pending_runtime = [], [], [], []

        conn, cursor = db.get_db_connection()
        try:
            for variant in variants:
                active_ids = all_connection_ids - variant.disabled_connection_ids
                energised = variant.energised_node_ids
                sub_branches = [
                    b for b in topology.branches
                    if b.connection_id in active_ids
                    and b.from_node_id in energised and b.to_node_id in energised
                ]

                if not sub_branches:
                    # The substation is islanded from everything -- nothing to solve.
                    for scenario in scenarios:
                        pending_runtime.append((
                            f"{run_data['run_id']}-{scenario['timestamp']}-{variant.variant_idx}",
                            scenario["timestamp"], variant.variant_idx, 0.0, False,
                        ))
                        failed += 1
                    completed, failed, pending_bus, pending_branch, pending_ybus, pending_runtime = _maybe_flush(
                        db, run_data["run_id"], conn, cursor, run_dir,
                        pending_bus, pending_branch, pending_ybus, pending_runtime,
                        completed, failed, request.chunk_commit_size, force=False,
                    )
                    continue

                sub_node_ids = [nid for nid in node_ids if nid in energised]
                sub_index = {nid: i for i, nid in enumerate(sub_node_ids)}

                overrides = (
                    perturb_admittances(sub_branches, request.admittance_perturbation.sigma, rng)
                    if request.admittance_perturbation.enabled else {}
                )

                connections = []
                admittances = []
                branch_y = {}
                for b in sub_branches:
                    r_ov, x_ov = overrides.get(b.connection_id, (None, None))
                    y = branch_admittance(b, r_ov, x_ov)
                    branch_y[b.connection_id] = y
                    connections.append([sub_index[b.from_node_id], sub_index[b.to_node_id]])
                    admittances.append([y])
                admittances_arr = np.array(admittances)

                ybus_entries = build_ybus_entries(sub_branches, branch_y)

                for scenario in scenarios:
                    output_group_id = f"{run_data['run_id']}-{scenario['timestamp']}-{variant.variant_idx}"
                    S = np.array([scenario["S"][topology.node_id_to_index[nid]] for nid in sub_node_ids])

                    t0 = time.time()
                    try:
                        volt_values, converged, _n_iter = full_pf(
                            S, connections, admittances_arr, ref_voltage, return_diagnostics=True,
                        )
                    except Exception as e:
                        logger.warning("PF solve failed for %s: %s", output_group_id, e)
                        volt_values, converged = None, False
                    solve_ms = (time.time() - t0) * 1000.0

                    pending_runtime.append((
                        output_group_id, scenario["timestamp"], variant.variant_idx, solve_ms, bool(converged),
                    ))

                    if converged and volt_values is not None:
                        completed += 1
                        for nid in sub_node_ids:
                            idx = sub_index[nid]
                            s = S[idx]
                            v = volt_values[idx]
                            bus_type = "REF" if nid == topology.substation_node_id else "PQ"
                            pending_bus.append((
                                output_group_id, scenario["timestamp"], variant.variant_idx, nid,
                                s.real, s.imag, abs(v), float(np.degrees(np.angle(v))), bus_type,
                            ))
                        for b in sub_branches:
                            y = branch_y[b.connection_id]
                            i, j = sub_index[b.from_node_id], sub_index[b.to_node_id]
                            i_flow = (volt_values[i] - volt_values[j]) * y
                            s_flow = volt_values[i] * np.conj(i_flow)
                            z = 1 / y
                            thermal_violation = b.nom_curr_a is not None and abs(i_flow) > b.nom_curr_a
                            pending_branch.append((
                                output_group_id, scenario["timestamp"], variant.variant_idx, b.connection_id,
                                b.from_node_id, b.to_node_id, s_flow.real, s_flow.imag,
                                z.real, z.imag, True, b.nom_curr_a, bool(thermal_violation),
                            ))
                        for (i_node, j_node, g, bsus) in ybus_entries:
                            pending_ybus.append((
                                output_group_id, scenario["timestamp"], variant.variant_idx, i_node, j_node, g, bsus,
                            ))
                    else:
                        failed += 1

                    completed, failed, pending_bus, pending_branch, pending_ybus, pending_runtime = _maybe_flush(
                        db, run_data["run_id"], conn, cursor, run_dir,
                        pending_bus, pending_branch, pending_ybus, pending_runtime,
                        completed, failed, request.chunk_commit_size, force=False,
                    )

            _maybe_flush(
                db, run_data["run_id"], conn, cursor, run_dir,
                pending_bus, pending_branch, pending_ybus, pending_runtime,
                completed, failed, request.chunk_commit_size, force=True,
            )
        finally:
            conn.close()

        metrics = {
            "total_output_groups": total,
            "converged": completed,
            "non_converged": failed,
            "n_scenarios": len(scenarios),
            "n_topology_variants": len(variants),
        }

        _update_run_config(run_dir, {
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "completed_scenarios": completed,
            "failed_scenarios": failed,
            "total_scenarios": total,
            "n_topology_variants": len(variants),
            "seed_used": seed,
            "metrics": metrics,
        })
        return {"status": "completed", "metrics": metrics}

    except Exception as e:
        logger.error("PF datagen run failed: %s", e, exc_info=True)
        _update_run_config(run_dir, {
            "status": "failed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        })
        return {"status": "failed", "error": str(e)}


def _maybe_flush(
    db, run_id, conn, cursor, run_dir,
    pending_bus, pending_branch, pending_ybus, pending_runtime,
    completed, failed, chunk_commit_size, force,
):
    """Commit the pending batch (and report progress) once it reaches
    `chunk_commit_size` runtime rows, or unconditionally when `force=True`."""
    if not force and len(pending_runtime) < chunk_commit_size:
        return completed, failed, pending_bus, pending_branch, pending_ybus, pending_runtime

    if pending_runtime:
        db.insert_pf_datagen_batch(run_id, pending_bus, pending_branch, pending_ybus, pending_runtime, conn, cursor)
        _update_run_config(run_dir, {"completed_scenarios": completed, "failed_scenarios": failed})

    return completed, failed, [], [], [], []
