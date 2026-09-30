import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Literal, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import gridarena.benchmarks.voltage_control as vc
import gridarena.database as db
import gridarena.schemas as sc

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

router = APIRouter()

Difficulty = Literal["clean", "easy", "medium", "hard"]
ScenarioType = Literal["Overvoltages", "Undervoltages"]


def _to_plain_dict(x: Any) -> Any:
    """Recursively convert defaultdicts and nested containers to plain serialisable objects."""
    if isinstance(x, defaultdict):
        x = dict(x)
    if isinstance(x, dict):
        return {k: _to_plain_dict(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_to_plain_dict(v) for v in x]
    return x


def _quantile_thresholds(values: List[float]) -> Tuple[float, float]:
    """
    Return (t1, t2) so that:
      easy:   score <= t1
      medium: t1 < score < t2
      hard:   score >= t2
    using 33% and 66% quantiles.
    """
    if not values:
        return 0.0, 0.0
    s = sorted(values)
    n = len(s)
    i1 = int(round(0.33 * (n - 1)))
    i2 = int(round(0.66 * (n - 1)))
    return s[i1], s[i2]


def _difficulty_filter_keys(
    hardness_by_key: Dict[Tuple[str, Any], float],
    difficulty: Difficulty,
) -> Tuple[set, Dict[str, float]]:
    """
    Filter scenario keys (grid_id, datetime) by hardness quantiles.
    Returns (selected_keys, profile_metadata).
    """
    keys = list(hardness_by_key.keys())

    if difficulty == "clean":
        return set(keys), {"method": "none", "t1": 0.0, "t2": 0.0}

    scores = [hardness_by_key[k] for k in keys]
    t1, t2 = _quantile_thresholds(scores)

    if difficulty == "easy":
        selected = {k for k in keys if hardness_by_key[k] <= t1}
    elif difficulty == "medium":
        selected = {k for k in keys if t1 < hardness_by_key[k] < t2}
    else:  # hard
        selected = {k for k in keys if hardness_by_key[k] >= t2}

    return selected, {"method": "quantiles_33_66", "t1": float(t1), "t2": float(t2)}


@router.get("/training-scenarios")
async def get_training_voltage_control_data(
    voltage_limit: float,
    Scenario: ScenarioType = Query(...),
    difficulty: Difficulty = Query("clean"),
):
    """
    Retrieve training snapshots + reference solutions.
    Difficulty filters which snapshots you return (scenario hardness), not just data corruption.

    Returns:
      {
        "difficulty": "...",
        "difficulty_profile": {...},
        "grids": {
          grid_id: {
            datetime: {
              "measurements": [...],
              "solutions": [...],
              "metrics": {...}
            }
          }
        }
      }
    """
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute("""SELECT grid_id FROM GridUsage WHERE voltage_control_train = 1""")
        grids_for_training = set(row[0] for row in cursor.fetchall())

        if Scenario == "Overvoltages":
            measurements = vc.get_all_measurements_over(
                cursor, voltage_limit, grids_for_training, phase_type="train"
            )
        else:
            measurements = vc.get_all_measurements_under(
                cursor, voltage_limit, grids_for_training, phase_type="train"
            )

        # Group into snapshots: (grid_id, dt) -> list[measurement_dict]
        snapshots: Dict[Tuple[str, Any], List[Dict[str, Any]]] = {}
        tmp = defaultdict(lambda: defaultdict(list))

        for grid_id, node_id, phase, dt, p_act, p_rea, v_mag, v_ang in measurements:
            tmp[grid_id][dt].append(
                {
                    "node_id": node_id,
                    "phase": phase,
                    "datetime": dt,
                    "power_active": p_act,
                    "power_reactive": p_rea,
                    "voltage_magnitude": v_mag,
                    "voltage_angle": v_ang,
                }
            )

        for grid_id, dt_dict in tmp.items():
            for dt, meas in dt_dict.items():
                snapshots[(grid_id, dt)] = meas

        sol_query = """
            SELECT node_id, phase, corrected_voltage, adjusted_power_active, adjusted_power_reactive, created_at
            FROM "VoltageControlSolutions"
            WHERE grid_id = %s AND datetime = %s
        """

        scenario_payload: Dict[Tuple[str, Any], Dict[str, Any]] = {}
        hardness_by_key: Dict[Tuple[str, Any], float] = {}
        has_solutions_by_key: Dict[Tuple[str, Any], bool] = {}

        grid_complexity_cache: Dict[str, Dict[str, Any]] = {}

        for (grid_id, dt), meas in snapshots.items():
            if grid_id not in grid_complexity_cache:
                grid_complexity_cache[grid_id] = vc.get_grid_complexity_metrics(cursor, grid_id)
            gcp = grid_complexity_cache[grid_id]
            grid_cnorm = float(gcp["grid_complexity_norm"])

            cursor.execute(sol_query, (grid_id, dt))
            sol_rows = cursor.fetchall()

            solutions = [
                {
                    "node_id": r[0],
                    "phase": r[1],
                    "corrected_voltage": r[2],
                    "adjusted_power_active": r[3],
                    "adjusted_power_reactive": r[4],
                    "created_at": r[5],
                }
                for r in sol_rows
            ]

            has_solutions = len(solutions) > 0
            has_solutions_by_key[(grid_id, dt)] = has_solutions

            metrics = vc.compute_snapshot_metrics(
                measurements=meas,
                solutions=solutions if solutions else None,
                nominal_voltage=vc.NOMINAL_VOLTAGE,
                band=vc.VOLTAGE_BAND,
                grid_complexity_norm=grid_cnorm,
                grid_complexity_profile=gcp,
            )
            hardness = float(metrics["hardness_score"])

            scenario_payload[(grid_id, dt)] = {
                "measurements": meas,
                "solutions": solutions,
                "metrics": metrics,
            }
            hardness_by_key[(grid_id, dt)] = hardness

        # Prefer snapshots that have solutions
        keys_all = list(snapshots.keys())
        keys_with_solutions = [k for k in keys_all if has_solutions_by_key.get(k, False)]

        if keys_with_solutions:
            preferred_keys = keys_with_solutions
            hardness_for_filter = {k: hardness_by_key[k] for k in preferred_keys}
            prefer_mode = "solutions_only"
        else:
            preferred_keys = keys_all
            hardness_for_filter = hardness_by_key
            prefer_mode = "no_solutions_found_fallback_all"

        selected_keys, diff_profile = _difficulty_filter_keys(hardness_for_filter, difficulty)
        diff_profile = {
            **diff_profile,
            "preference": prefer_mode,
            "preferred_population": len(preferred_keys),
        }

        all_data = defaultdict(lambda: defaultdict(dict))
        ordered_selected = [k for k in preferred_keys if k in selected_keys]
        for grid_id, dt in ordered_selected:
            all_data[grid_id][dt] = scenario_payload[(grid_id, dt)]

        conn.commit()

        return _to_plain_dict(
            {
                "difficulty": difficulty,
                "difficulty_profile": diff_profile,
                "scenario": Scenario,
                "voltage_limit": voltage_limit,
                "grids": all_data,
            }
        )

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.get("/voltage-control-data")
async def get_voltage_control_data(
    voltage_limit: float,
    Scenario: ScenarioType = Query("Overvoltages"),
    difficulty: Difficulty = Query("clean"),
):
    """
    Retrieve testing snapshots with hidden reference solutions.
    Difficulty filters which snapshots you return.

    Returns:
      {
        "difficulty": "...",
        "difficulty_profile": {...},
        "grids": { grid_id: { anonymised_key: [ ...measurements... ] } }
      }
    """
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute("""SELECT grid_id FROM GridUsage WHERE voltage_control_test = 1""")
        grids_for_testing = set(row[0] for row in cursor.fetchall())

        if Scenario == "Overvoltages":
            measurements = vc.get_all_measurements_over(
                cursor, voltage_limit, grids_for_testing, phase_type="test"
            )
        else:
            measurements = vc.get_all_measurements_under(
                cursor, voltage_limit, grids_for_testing, phase_type="test"
            )

        # Group snapshot measurements
        snapshots = defaultdict(lambda: defaultdict(list))
        for grid_id, node_id, phase, dt, p_act, p_rea, v_mag, v_ang in measurements:
            snapshots[grid_id][dt].append(
                {
                    "node_id": node_id,
                    "phase": phase,
                    "power_active": p_act,
                    "power_reactive": p_rea,
                    "voltage_magnitude": v_mag,
                    "voltage_angle": v_ang,
                }
            )

        sol_query = """
            SELECT node_id, phase, corrected_voltage, adjusted_power_active, adjusted_power_reactive, created_at
            FROM "VoltageControlSolutions"
            WHERE grid_id = %s AND datetime = %s
        """

        hardness_by_key: Dict[Tuple[str, Any], float] = {}
        has_solutions_by_key: Dict[Tuple[str, Any], bool] = {}

        grid_complexity_cache: Dict[str, Dict[str, Any]] = {}

        keys_all: List[Tuple[str, Any]] = []
        for grid_id, dt_dict in snapshots.items():
            if grid_id not in grid_complexity_cache:
                grid_complexity_cache[grid_id] = vc.get_grid_complexity_metrics(cursor, grid_id)
            gcp = grid_complexity_cache[grid_id]
            grid_cnorm = float(gcp["grid_complexity_norm"])

            for dt, meas in dt_dict.items():
                key = (grid_id, dt)
                keys_all.append(key)

                cursor.execute(sol_query, (grid_id, dt))
                sol_rows = cursor.fetchall()
                has_solutions_by_key[key] = len(sol_rows) > 0

                solutions = [
                    {
                        "node_id": r[0],
                        "phase": r[1],
                        "corrected_voltage": r[2],
                        "adjusted_power_active": r[3],
                        "adjusted_power_reactive": r[4],
                        "created_at": r[5],
                    }
                    for r in sol_rows
                ]

                metrics = vc.compute_snapshot_metrics(
                    measurements=meas,
                    solutions=solutions if solutions else None,
                    nominal_voltage=vc.NOMINAL_VOLTAGE,
                    band=vc.VOLTAGE_BAND,
                    grid_complexity_norm=grid_cnorm,
                    grid_complexity_profile=gcp,
                )
                hardness_by_key[key] = float(metrics["hardness_score"])

        keys_with_solutions = [k for k in keys_all if has_solutions_by_key.get(k, False)]

        if keys_with_solutions:
            preferred_keys = keys_with_solutions
            hardness_for_filter = {k: hardness_by_key[k] for k in preferred_keys}
            prefer_mode = "solutions_only"
        else:
            preferred_keys = keys_all
            hardness_for_filter = hardness_by_key
            prefer_mode = "no_solutions_found_fallback_all"

        selected_keys, diff_profile = _difficulty_filter_keys(hardness_for_filter, difficulty)
        diff_profile = {
            **diff_profile,
            "preference": prefer_mode,
            "preferred_population": len(preferred_keys),
        }

        selected_snapshots = {(gid, dt) for (gid, dt) in selected_keys}
        mapping = vc.build_load_voltage_timestamp_keys(selected_snapshots, cursor)

        all_data = defaultdict(lambda: defaultdict(list))
        ordered_selected = [k for k in preferred_keys if k in selected_snapshots]
        for grid_id, dt in ordered_selected:
            anon_key = mapping[(grid_id, dt)]
            all_data[grid_id][anon_key].extend(snapshots[grid_id][dt])

        conn.commit()

        return _to_plain_dict(
            {
                "difficulty": difficulty,
                "difficulty_profile": diff_profile,
                "scenario": Scenario,
                "voltage_limit": voltage_limit,
                "grids": all_data,
            }
        )

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.post("/submit-results")
async def submit_voltage_control_guesses(vc_guess: sc.VCGuessSubmission):
    """Submit user guesses for voltage control."""
    conn, cursor = db.get_db_connection()
    try:
        # Validate grid exists
        cursor.execute("SELECT 1 FROM grids WHERE grid_id = %s", (vc_guess.grid_id,))
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=422,
                detail=f"Grid '{vc_guess.grid_id}' not found.",
            )

        # Validate all anon keys exist in the mapping
        if vc_guess.guesses:
            submitted_keys = list(vc_guess.guesses.keys())
            cursor.execute(
                'SELECT anonymised_key FROM "VoltageTimestampMapping" WHERE grid_id = %s AND anonymised_key = ANY(%s)',
                (vc_guess.grid_id, submitted_keys),
            )
            valid_keys = {row[0] for row in cursor.fetchall()}

            invalid = set(submitted_keys) - valid_keys
            if invalid:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown anonymised keys: {sorted(invalid)[:10]}. "
                           "Keys must match those returned by the voltage-control-data endpoint.",
                )

        for anon_key, node_solutions in vc_guess.guesses.items():
            guessed_voltages = {
                sol.node_id: {"phase": sol.phase, "corrected_voltage": sol.corrected_voltage}
                for sol in node_solutions
            }
            guessed_loads = {
                sol.node_id: {
                    "adjusted_power_active": sol.adjusted_power_active,
                    "adjusted_power_reactive": sol.adjusted_power_reactive,
                }
                for sol in node_solutions
            }

            cursor.execute(
                """
                INSERT INTO "VCUserGuesses" (guess_id, grid_id, anonymised_key, guessed_voltages, guessed_loads)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (guess_id, grid_id, anonymised_key)
                DO UPDATE SET
                    guessed_voltages = EXCLUDED.guessed_voltages,
                    guessed_loads = EXCLUDED.guessed_loads,
                    timestamp = CURRENT_TIMESTAMP
                """,
                (
                    vc_guess.guess_id,
                    vc_guess.grid_id,
                    anon_key,
                    json.dumps(guessed_voltages),
                    json.dumps(guessed_loads),
                ),
            )

        conn.commit()
        return {
            "status": "submitted",
            "accepted": len(vc_guess.guesses),
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.get("/score")
async def get_score(guess_id: str, grid_id: str = Query(...)):
    """
    Score includes a smooth penalty for large total |ΔP| per timestamp (no hard budget).
    """
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute(
            """
            SELECT vug.anonymised_key, vug.guessed_voltages, vug.guessed_loads, vtm.datetime
            FROM "VCUserGuesses" vug
            JOIN "VoltageTimestampMapping" vtm ON vug.anonymised_key = vtm.anonymised_key
            WHERE vug.guess_id = %s AND vug.grid_id = %s
            """,
            (guess_id, grid_id),
        )
        user_rows = cursor.fetchall()
        if not user_rows:
            raise HTTPException(
                status_code=404,
                detail=f"No guesses found for guess_id={guess_id} and grid_id={grid_id}",
            )

        # --- Tunables for reference-based scoring ---
        V_TOL = 1.0  # volts: "close enough to optimal voltages"
        V_REF = 1.0  # volts: sets how fast voltage_factor decays when missing target
        K = 2.0  # steepness

        nominal_voltage = vc.NOMINAL_VOLTAGE
        low = (1.0 - vc.VOLTAGE_BAND) * nominal_voltage
        high = (1.0 + vc.VOLTAGE_BAND) * nominal_voltage

        sol_query = """
            SELECT node_id, phase, corrected_voltage, adjusted_power_active, adjusted_power_reactive
            FROM "VoltageControlSolutions"
            WHERE grid_id = %s AND datetime = %s
        """

        total_nodes = 0
        total_score = 0.0
        per_timestamp_results = []

        for anon_key, guessed_voltages_json, guessed_loads_json, datetime in user_rows:
            guessed_voltages = json.loads(guessed_voltages_json)
            guessed_loads = json.loads(guessed_loads_json)

            cursor.execute(
                """
                SELECT node_id, phase, voltage_magnitude, power_active, power_reactive
                FROM "Measurements"
                WHERE grid_id = %s AND datetime = %s
                ORDER BY node_id, phase
                """,
                (grid_id, datetime),
            )
            original_rows = cursor.fetchall()
            if not original_rows:
                continue

            # Fetch reference solutions (if any) for this timestamp
            cursor.execute(sol_query, (grid_id, datetime))
            sol_rows = cursor.fetchall()
            reference_available = len(sol_rows) > 0

            # Build reference voltage lookup keyed by (node_id, phase)
            ref_v_by_np = {}
            if reference_available:
                for node_id, phase, v_corr, p_adj, q_adj in sol_rows:
                    # corrected_voltage should exist if you're calling them "optimal voltages"
                    if v_corr is not None:
                        ref_v_by_np[(str(node_id), str(phase))] = float(v_corr)

            node_results = []
            node_scores = []

            # For effort penalty
            sum_abs_dp = 0.0
            sum_abs_p = 0.0

            # For reference voltage error
            sum_abs_v_err = 0.0
            v_err_count = 0

            # --- Iterate nodes/phases in the measurement snapshot ---
            for node_id, phase, v_meas, p_meas, q_meas in original_rows:
                node_id_s = str(node_id)
                phase_s = str(phase)

                corrected_data = guessed_voltages.get(node_id_s)
                adjusted_data = guessed_loads.get(node_id_s)

                # Only score where user provided a voltage for the matching phase
                if not corrected_data or corrected_data.get("phase") != phase_s:
                    continue

                v_corr = float(corrected_data.get("corrected_voltage", v_meas))

                # If user didn't provide adjusted P, treat it as unchanged
                p_corr = (
                    float(adjusted_data.get("adjusted_power_active", p_meas))
                    if adjusted_data
                    else float(p_meas)
                )

                # accumulate effort stats
                dp = p_corr - float(p_meas)
                sum_abs_dp += abs(dp)
                sum_abs_p += abs(float(p_meas))

                # reference voltage error if reference exists + has this node/phase
                if reference_available:
                    v_ref = ref_v_by_np.get((node_id_s, phase_s))
                    if v_ref is not None:
                        sum_abs_v_err += abs(v_corr - v_ref)
                        v_err_count += 1

                # --- Node-level diagnostics (kept from old scoring; useful to inspect) ---
                before_dev = abs(float(v_meas) - nominal_voltage)
                after_dev = abs(v_corr - nominal_voltage)

                voltage_score = (before_dev - after_dev) / (before_dev + 1e-6)
                voltage_score = max(min(voltage_score, 1.0), -1.0)

                if abs(float(p_meas)) > 1e-6:
                    power_penalty = 1.0 - min(1.0, abs(p_corr - float(p_meas)) / abs(float(p_meas)))
                else:
                    power_penalty = 1.0

                was_bad = (float(v_meas) < low) or (float(v_meas) > high)
                now_good = low <= v_corr <= high
                bonus = 1.0 if was_bad and now_good else 0.0

                # Old node_score (diagnostic only when reference-based scoring is active)
                node_score = 0.7 * max(voltage_score, 0.0) + 0.2 * power_penalty + 0.1 * bonus

                node_results.append(
                    {
                        "node_id": node_id_s,
                        "phase": phase_s,
                        "measured_voltage": float(v_meas),
                        "corrected_voltage": v_corr,
                        "measured_power_active": float(p_meas),
                        "corrected_power_active": p_corr,
                        "voltage_score": round(voltage_score, 4),
                        "power_penalty": round(power_penalty, 4),
                        "bonus": bonus,
                        "node_score": round(node_score, 4),
                        # Optional: expose reference voltage if present for easier debugging
                        "reference_corrected_voltage": (
                            round(ref_v_by_np[(node_id_s, phase_s)], 6)
                            if reference_available and (node_id_s, phase_s) in ref_v_by_np
                            else None
                        ),
                    }
                )
                node_scores.append(node_score)

            if not node_results:
                continue

            nodes_total = len(node_results)
            effort_norm = sum_abs_dp / (sum_abs_p + 1e-6)
            effort_factor = vc.effort_factor(effort_norm)

            # --- Timestamp score ---
            if reference_available and v_err_count > 0:
                v_mae = sum_abs_v_err / float(v_err_count)
                voltage_ok = v_mae <= V_TOL

                if voltage_ok:
                    # Lexicographic: once you match optimal voltages (within tolerance),
                    # only effort matters (lower effort => higher score)
                    timestamp_score = float(effort_factor)
                    voltage_factor = 1.0
                    mode = "ref_voltage_then_effort"
                else:
                    # Missed the optimal voltages -> penalise voltage miss strongly,
                    # still penalise effort as well
                    voltage_factor = 1.0 / (1.0 + (max(0.0, v_mae) / max(V_REF, 1e-9)) ** K)
                    timestamp_score = float(voltage_factor) * float(effort_factor)
                    mode = "ref_voltage_miss_penalised"

                avg_node_score = sum(node_scores) / len(node_scores)
                per_timestamp_results.append(
                    {
                        "anonymised_key": anon_key,
                        "datetime": datetime,
                        "nodes_total": nodes_total,
                        "mode": mode,
                        "reference_available": True,
                        "reference_voltage_mae": round(float(v_mae), 6),
                        "reference_voltage_tol": V_TOL,
                        "voltage_factor": round(float(voltage_factor), 6),
                        "effort_norm": round(float(effort_norm), 6),
                        "effort_factor": round(float(effort_factor), 6),
                        "timestamp_score": round(float(timestamp_score), 4),
                        # Keep old diagnostic signal too
                        "average_node_score_diagnostic": round(float(avg_node_score), 4),
                        "nodes": node_results,
                        "reference_voltage_coverage": round(v_err_count / max(nodes_total, 1), 6),
                    }
                )
            else:
                # Fallback to your previous scoring when no reference exists (or no overlap)
                avg_node_score = sum(node_scores) / len(node_scores)
                timestamp_score = avg_node_score * effort_factor
                per_timestamp_results.append(
                    {
                        "anonymised_key": anon_key,
                        "datetime": datetime,
                        "nodes_total": nodes_total,
                        "mode": "outcome_only_fallback",
                        "reference_available": False,
                        "average_node_score": round(float(avg_node_score), 4),
                        "effort_norm": round(float(effort_norm), 6),
                        "effort_factor": round(float(effort_factor), 6),
                        "timestamp_score": round(float(timestamp_score), 4),
                        "nodes": node_results,
                    }
                )

            total_nodes += nodes_total
            total_score += float(timestamp_score) * nodes_total

        overall_score = round(total_score / total_nodes, 4) if total_nodes else 0.0

        return {
            "guess_id": guess_id,
            "grid_id": grid_id,
            "total_nodes": total_nodes,
            "overall_score": overall_score,
            "per_timestamp": per_timestamp_results,
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def voltage_control_ui(request: Request):
    """UI for Voltage Control Benchmark."""
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute("SELECT grid_id FROM grids ORDER BY grid_id")
        grids = [row[0] for row in cursor.fetchall()]
    except Exception:
        logger.warning("Failed to load grid list for Voltage Control UI", exc_info=True)
        grids = []
    finally:
        conn.close()

    return templates.TemplateResponse("benchmarks/voltage_control.html", {
        "request": request,
        "title": "Voltage Control",
        "active": "voltage_control",
        "grids": grids,
    })
