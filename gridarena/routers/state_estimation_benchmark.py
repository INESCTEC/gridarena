"""State Estimation Router with endpoints to retrieve training data, retrieve estimation input,
submit predictions, and compute score based on squared error."""

import logging
from collections import defaultdict
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import gridarena.benchmarks.state_estimation as se
import gridarena.database as db
import gridarena.schemas as sc

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

router = APIRouter()


@router.get("/training-state-data")
async def get_training_state_data(
    noise_difficulty: Literal["clean", "easy", "medium", "hard"] = Query("clean"),
    observability: Literal["clean", "easy", "medium", "hard"] = Query("medium"),
):
    """
    Retrieves historical measurement data for all nodes and timestamps in the grids
    that allow information to be retrieved for state estimation training,
    structured by masked grid and node identifiers. This endpoint ensures that
    no real identifiers are exposed.

    The function ensures that grid and node masks are generated beforehand,
    and then returns the data grouped hierarchically as follows:

    Returns:
        dict: Dictionary with training data, eg.::

        {
            "grids": {
                masked_grid_id: {
                    masked_node_id: [
                        {
                            "datetime": str,
                            "phase": str,
                            "power_active": float,
                            "power_reactive": float,
                            "voltage_magnitude": float,
                            "voltage_angle": float
                        },
                        ...
                    ],
                    ...
                },
                ...
            }
        }
    """
    conn, cursor = db.get_db_connection()
    try:
        # Get grids marked for training state estimation
        cursor.execute(
            """
            SELECT grid_id FROM GridUsage WHERE state_estimation_train = 1
        """
        )
        grids_for_training = set(row[0] for row in cursor.fetchall())

        se.ensure_grid_masks(cursor)
        se.ensure_all_node_masks(cursor)

        data = {"grids": {}}

        # Use psycopg3's support for arrays when passing grid IDs
        cursor.execute(
            """
            SELECT m.grid_id, gm.masked_id, m.node_id, nm.masked_node_id,
                   m.datetime, m.phase, m.power_active, m.power_reactive,
                   m.voltage_magnitude, m.voltage_angle
            FROM "Measurements" m
            JOIN GridMask gm ON gm.grid_id = m.grid_id
            JOIN NodeMask nm ON nm.grid_id = m.grid_id AND nm.node_id = m.node_id AND nm.phase = m.phase
            WHERE m.grid_id = ANY(%s)
            ORDER BY m.grid_id, m.node_id, m.datetime
            """,
            (list(grids_for_training),),  # Pass grids as a list
        )

        grids = defaultdict(lambda: defaultdict(list))

        BATCH_SIZE = 5000
        while True:
            batch = cursor.fetchmany(BATCH_SIZE)
            if not batch:
                break
            for (
                grid_id,
                masked_gid,
                node_id,
                masked_nid,
                dt,
                phase,
                p_act,
                p_rea,
                v_mag,
                v_ang,
            ) in batch:
                grids[masked_gid][masked_nid].append(
                    {
                        "datetime": dt,
                        "phase": phase,
                        "power_active": p_act,
                        "power_reactive": p_rea,
                        "voltage_magnitude": v_mag,
                        "voltage_angle": v_ang,
                    }
                )

        data["grids"] = grids
        noise_profile = se.get_noise_profile(noise_difficulty)
        corrupted = se.corrupt_training_dataset(grids, noise_profile, difficulty=noise_difficulty)

        conn.commit()
        return {
            "noise_difficulty": noise_difficulty,
            "noise_profile": noise_profile,
            "grids": corrupted,
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.get("/state-data")
async def get_state_estimation_input(
    user_id: str = Query(...),
    noise_difficulty: Literal["clean", "easy", "medium", "hard"] = Query("clean"),
    observability: Literal["clean", "easy", "medium", "hard"] = Query("medium"),
):
    """
    Retrieves state estimation input data for all grids using masked identifiers.

    This endpoint is idempotent per user: if the caller already has an open
    (not yet submitted via POST /submit-estimates) estimation task, that same
    task -- same masked grid, timestamp, and known/unknown split -- is
    returned again rather than creating a new one. A new task is only
    created once no open task exists (first call, or the previous one was
    already submitted). `noise_difficulty` and the measurement-history
    window still apply fresh on every call; `observability` only affects the
    known/unknown split, so it's only used when a new task is created.

    Args:
        user_id (str): Identifier for the user requesting the data, used to manage task persistence.

    Returns:
        dict: Dictionary with test data, eg.::

          {
            "Masked GridID": str,
            "Estimation Task ID": str,
            "Current State": {
                "known_nodes": { masked_node_id: {measurement_at_timestamp} },
                "unknown_nodes": [ masked_node_id, ... ]
            },
            "Measurement Data": {
                masked_node_id: [ {measurement}, ... ]   # all days < timestamp
            }
        }
    """
    conn, cursor = db.get_db_connection()
    try:
        se.ensure_grid_masks(cursor)
        se.ensure_all_node_masks(cursor)

        open_task = se.get_open_task_for_user(cursor, user_id)
        if open_task is not None:
            selected_grid = open_task["grid_id"]
            selected_time = open_task["timestamp"]
            selected_eid = open_task["estimation_id"]
        else:
            # Get grids marked for testing state estimation
            cursor.execute(
                """
                SELECT grid_id FROM GridUsage WHERE state_estimation_test = 1
            """
            )
            rows = cursor.fetchall()
            grids_for_testing = set(
                row[0] for row in rows
            )  # Use 'rows' instead of calling fetchall() again

            selected_grid = se.get_random_grid(cursor)
            if selected_grid not in grids_for_testing:
                raise HTTPException(
                    status_code=404, detail="No grids available for state estimation testing"
                )

            selected_time = se.random_timestamp_for_grid(cursor, selected_grid)
            selected_eid = se.create_estimation_task(
                cursor,
                selected_grid,
                selected_time,
                user_id,
                observability=observability,
            )

        masked_grid = se.get_masked_grid(cursor, selected_grid)

        obs_profile = se.get_observability_profile(observability)
        unknown_history_seconds = int(float(obs_profile["unknown_history_hours"]) * 3600.0)

        known_nodes, historic_data = se.get_actual_state(
            cursor,
            selected_eid,
            unknown_history_seconds=unknown_history_seconds,
            known_history_seconds=1,
        )

        noise_profile = se.get_noise_profile(noise_difficulty)
        known_nodes_cor, historic_data_cor = se.corrupt_estimation_input(
            known_nodes=known_nodes,
            measurement_data=historic_data,
            noise_profile=noise_profile,
            masked_grid_id=masked_grid,
            estimation_id=selected_eid,
        )

        unknown_nodes = sorted([k for k in historic_data_cor.keys() if k not in known_nodes_cor])

        conn.commit()

        response = {
            "Masked GridID": masked_grid,
            "Estimation Task ID": selected_eid,
            "noise_difficulty": noise_difficulty,
            "noise_profile": noise_profile,
            "observability": observability,
            "observability_profile": obs_profile,
            "Current State": {
                "known_nodes": known_nodes_cor,
                "unknown_nodes": unknown_nodes,
            },
            "Measurement Data": historic_data_cor,
        }

        return response

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.post("/submit-estimates")
async def submit_state_estimates(submission: sc.StateEstimateSubmission):
    """
    Receives and stores submitted voltage estimates for a specific estimation task.

    The request must include:
      - A masked grid ID
      - A list of masked node IDs with corresponding voltage magnitude and angle
      - A user ID and estimation task ID
      - The timestamp of the estimate

    For each masked node ID, the corresponding real node ID and phase are resolved
    and the values are stored in the `StateEstimates` table. Existing estimates for
    the same key will be replaced.

    Args:
        submission (StateEstimateSubmission): The submission payload containing user, task, and voltage estimates.

    Returns:
        dict: Submission report dictionary, eg.::

          {
            "status": "submitted"
          }

    Raises:
        HTTPException 404: If a mask cannot be resolved to a real ID.
        HTTPException 500: If a database error occurs.
    """
    conn, cursor = db.get_db_connection()
    try:
        # Resolve masked grid ID to real grid ID
        try:
            real_gid = se.resolve_grid_id_from_mask(cursor, submission.grid_id)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Masked grid ID '{submission.grid_id}' not found. "
                       "Download estimation input first to generate the mapping.",
            )

        # Ensure the grid is eligible for state estimation (testing or training)
        cursor.execute(
            """
            SELECT 1 FROM GridUsage WHERE grid_id = %s AND (state_estimation_train = 1 OR state_estimation_test = 1)
        """,
            (real_gid,),
        )
        if cursor.fetchone() is None:
            raise HTTPException(status_code=400, detail="Grid is not eligible for state estimation")

        # Validate estimation_id exists for this user
        cursor.execute(
            "SELECT 1 FROM EstimationTasks WHERE user_id = %s AND estimation_id = %s LIMIT 1",
            (submission.user_id, submission.estimation_id),
        )
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=422,
                detail=f"Estimation task '{submission.estimation_id}' not found for user '{submission.user_id}'. "
                       "Download estimation input first to create a task.",
            )

        for node_id_data in submission.estimates:
            masked_node_id = node_id_data.masked_node_id
            try:
                real_nid, phase = se.resolve_node_id_from_mask(cursor, real_gid, masked_node_id)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"Masked node ID '{masked_node_id}' not found for grid '{submission.grid_id}'.",
                )
            real_data = [real_gid, real_nid, phase]
            se.insert_state_estimation(cursor, submission, node_id_data, real_data)

        conn.commit()
        return {"status": "submitted", "accepted": len(submission.estimates)}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.get("/state-score")
async def get_state_estimation_score(user_id: str, estimation_id: str):
    """
    Computes the sum of squared errors between predicted and true voltage magnitudes
    and angles for a given estimation task identified by the masked grid ID and timestamp.

    The prediction and ground truth data are resolved using the provided user ID
    and estimation task ID. The score is calculated using a standard error metric
    and returned as a rounded float.

    Args:
        user_id (str): The identifier of the user who submitted the estimates.
        estimation_id (str): The identifier of the estimation task.

    Returns:
        dict: Dictionary with submission score information, eg.::

          {
            "user_id": str,
            "estimation_id": str,
            "score": float  # Sum of squared errors (rounded to 6 decimals)
          }

    Raises:
        HTTPException 404: If the masked grid ID cannot be resolved.
        HTTPException 500: If a database error occurs.
    """

    conn, cursor = db.get_db_connection()

    try:
        predict_voltage, predict_angles = se.get_predicted_voltages(cursor, user_id, estimation_id)
        true_voltage, true_angles = se.get_real_voltages(cursor, user_id, estimation_id)

        score = se.get_state_estimation_score(
            predict_voltage, predict_angles, true_voltage, true_angles
        )

        return {
            "user_id": user_id,
            "estimation_id": estimation_id,
            "score": round(score, 6),
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def state_estimation_ui(request: Request):
    """Main UI page for State Estimation."""
    return templates.TemplateResponse("benchmarks/state_estimation.html", {
        "request": request,
        "title": "State Estimation",
        "active": "state_estimation",
    })
