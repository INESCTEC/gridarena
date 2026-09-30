import hashlib
import json
import logging
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import gridarena.benchmarks.phase_identification as pi
import gridarena.benchmarks.topology_discovery as td
import gridarena.database as db
import gridarena.powerflow.get_grid_info as gd
import gridarena.schemas as sc

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

router = APIRouter()


@router.get("/training-topology-data")
async def get_topology_identification_data(
    difficulty: Literal["clean", "easy", "medium", "hard"] = Query("clean"),
):
    """
    Retrieves historical measurement and grid data for all grids for training
    a topology discovery algorithm

    Returns:
        dict: Dictionary with the retrieved information, eg.::

        {
            grid_id1: {
                node1_id: [ {measurement1}, ... ],
                node2_id: [ {measurement2}, ... ],
                ...
            },
            grid_id2: {
                ...
            }
        }

    Raises:
        HTTPException: If no measurements are found or a database error occurs.
    """
    conn, cursor = db.get_db_connection()
    try:
        # Filter grids marked for topology detection (training)
        cursor.execute(
            """
            SELECT grid_id FROM GridUsage WHERE topology_detection_train = 1
            """
        )
        grids_for_training = set(row[0] for row in cursor.fetchall())

        # Get measurements filtered for topology detection training
        measurements = pi.get_all_measurements(
            cursor, task_type="topology_detection", phase_type="train"
        )

        # Fetch topology data for the same grids
        node_id_to_index_per_grid, connections_per_grid, conn_data_per_grid = (
            td.get_all_grids_topology(cursor, grids_for_training)
        )

        # Difficulty profile (platform-controlled)
        profile = td.get_corruption_profile(difficulty=difficulty)

        # Seeded RNG per (grid_id, node_id, phase, difficulty) => deterministic across calls
        rngs: Dict[tuple, random.Random] = {}

        all_data = defaultdict(lambda: defaultdict(list))

        for grid_id, node_id, phase, dt, p_act, p_rea, v_mag, v_ang in measurements:
            rng_key = (grid_id, node_id, phase)
            if rng_key not in rngs:
                seed = hashlib.sha256(f"{grid_id}:{node_id}:{phase}:{difficulty}".encode()).hexdigest()
                rngs[rng_key] = random.Random(seed)

            record = {
                "datetime": dt,
                "power_active": p_act,
                "power_reactive": p_rea,
                "voltage_magnitude": v_mag,
                "voltage_angle": v_ang,
                "phase": phase,
            }

            # Corrupt only numeric measurement fields; datetime/phase unchanged.
            record = td.corrupt_measurement_record(record, rngs[rng_key], profile)

            all_data[grid_id][node_id].append(record)

        conn.commit()
        return {
            "difficulty": difficulty,
            "profile": profile,
            "grids": all_data,
            "node to corresponding index": node_id_to_index_per_grid,
            "topology (index)": connections_per_grid,
            "conn_data": conn_data_per_grid,
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.get("/topology-data")
async def get_topology_discovery_data(
    difficulty: Literal["clean", "easy", "medium", "hard"] = Query("clean"),
):
    """
    Retrieves historical measurement and grid data with topology hidden for all grids

    Returns:
        dict: Return the test data for the topology discovery benchmark, eg.::

        {
            grid_id1: {
                ...
            },
            grid_id2: {
                ...
            }
        }

    Raises:
        HTTPException: If no measurements are found or a database error occurs.
    """
    conn, cursor = db.get_db_connection()
    try:
        # Filter grids marked for topology detection (testing)
        cursor.execute(
            """
            SELECT grid_id FROM GridUsage WHERE topology_detection_test = 1
            """
        )
        grids_for_testing = set(row[0] for row in cursor.fetchall())

        # Build/load anonymisation mappings
        grid_mapping = td.build_load_grid_anon_keys_for_grids(cursor, grids_for_testing)
        # grid_mapping: { real_grid_id -> anon_grid_id }

        # Get measurements filtered for topology detection testing
        measurements = pi.get_all_measurements(
            cursor, task_type="topology_detection", phase_type="test"
        )

        # (Topology is intentionally not returned here; it's the hidden target.)
        td.get_all_grids_topology(cursor, grids_for_testing)

        profile = td.get_corruption_profile(
            difficulty=difficulty,
        )

        # Seeded RNG per (anon_grid_id, node_id, phase, difficulty) => deterministic across calls
        rngs: Dict[tuple, random.Random] = {}
        all_data = defaultdict(lambda: defaultdict(list))

        for grid_id, node_id, phase, dt, p_act, p_rea, v_mag, v_ang in measurements:
            # Only include grids that are in the test set (defensive)
            if grid_id not in grids_for_testing:
                continue

            anon_grid_id = grid_mapping[grid_id]

            rng_key = (anon_grid_id, node_id, phase)
            if rng_key not in rngs:
                seed = hashlib.sha256(f"{anon_grid_id}:{node_id}:{phase}:{difficulty}".encode()).hexdigest()
                rngs[rng_key] = random.Random(seed)

            record = {
                "datetime": dt,
                "power_active": p_act,
                "power_reactive": p_rea,
                "voltage_magnitude": v_mag,
                "voltage_angle": v_ang,
                "phase": phase,
            }

            record = td.corrupt_measurement_record(record, rngs[rng_key], profile)
            all_data[anon_grid_id][node_id].append(record)

        conn.commit()
        return {
            "difficulty": difficulty,
            "profile": profile,
            "grids": all_data,
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.post("/submit-results")
async def submit_topology_guesses(topology_guess: sc.TopologyGuessSubmission):
    """
    Endpoint to submit user guesses for the topologies.
    Guesses are stored in the database.

    Parameters:
        topology_guess (TopologyGuessSubmission): JSON with guess_id, grid_id and guesses.

    Returns:
        dict: Submission status dictionary, eg.::

        {
            "status": "submitted",
            "summary": {
                "submitted": int,
                "duplicates_skipped": int
            }
        }
    """
    conn, cursor = db.get_db_connection()
    try:
        # Resolve: if provided grid_id is an anonymised key, map it back to real grid_id.
        try:
            real_grid_id = td.resolve_real_grid_id(cursor, topology_guess.grid_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        cursor.execute("SELECT 1 FROM grids WHERE grid_id = %s", (real_grid_id,))
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=422,
                detail=f"Grid '{topology_guess.grid_id}' not found. "
                       "Ensure the grid exists before submitting.",
            )

        guesses_json = json.dumps(topology_guess.guesses)

        cursor.execute(
            """
            INSERT INTO "TopologyUserGuesses" (guess_id, grid_id, guessed_topology)
            VALUES (%s, %s, %s)
            ON CONFLICT (guess_id, grid_id)
            DO UPDATE SET
                guessed_topology = EXCLUDED.guessed_topology,
                timestamp = CURRENT_TIMESTAMP
            """,
            (
                topology_guess.guess_id,
                real_grid_id,
                guesses_json,
            ),
        )

        conn.commit()
        return {"status": "submitted", "accepted_edges": len(topology_guess.guesses)}

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
    Returns the guessing accuracy of a user for a given grid,
    without revealing the correct topology.

    Parameters:
        guess_id (str): The user making the guesses.
        grid_id (str): The grid for which the guesses were made.

    Returns:
        dict: Dictionary with the score information, eg.::

        {
            "guess_id": str,
            "grid_id": str,
            "total_guesses": int,
            "correct": int,
            "accuracy": float (0–1)
        }
    """
    conn, cursor = db.get_db_connection()
    try:
        # Resolve anon->real if needed (or passthrough real)
        try:
            real_grid_id = td.resolve_real_grid_id(cursor, grid_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        cursor.execute(
            """
            SELECT guessed_topology
            FROM "TopologyUserGuesses"
            WHERE guess_id = %s AND grid_id = %s
            """,
            (guess_id, real_grid_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"No topology guess found for guess_id={guess_id}, grid_id={grid_id}",
            )

        guessed_topology = json.loads(row[0])  # list of [u, v]

        node_id_to_index = gd.get_nodes_from_grid(real_grid_id, cursor)
        connections, conn_data = gd.get_grid_connections(cursor, real_grid_id, node_id_to_index)

        true_edges = {tuple(sorted(edge)) for edge in connections}
        guessed_edges = {tuple(sorted(edge)) for edge in guessed_topology}

        correct = len(true_edges & guessed_edges)
        extra = len(guessed_edges - true_edges)
        missed = len(true_edges - guessed_edges)

        accuracy = round(correct / len(true_edges), 4) if true_edges else 0.0

        # IMPORTANT: return the grid_id the user asked about (anon or real),
        # so you don't leak the real ID if they used anon.
        return {
            "guess_id": guess_id,
            "grid_id": grid_id,
            "total_true_edges": len(true_edges),
            "guessed_edges": len(guessed_edges),
            "correct": correct,
            "incorrect_extra": extra,
            "missed": missed,
            "accuracy": accuracy,
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def topology_discovery_ui(request: Request):
    """Main UI page for Topology Discovery."""
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute("SELECT grid_id FROM grids ORDER BY grid_id")
        grids = [row[0] for row in cursor.fetchall()]
    except Exception:
        logger.warning("Failed to load grid list for Topology Discovery UI", exc_info=True)
        grids = []
    finally:
        conn.close()

    return templates.TemplateResponse("benchmarks/topology_discovery.html", {
        "request": request,
        "title": "Topology Discovery",
        "active": "topology_discovery",
        "grids": grids,
    })
