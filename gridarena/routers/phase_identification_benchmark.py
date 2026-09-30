import hashlib
import logging
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import gridarena.benchmarks.phase_identification as pi
import gridarena.database as db
import gridarena.schemas as sc

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

router = APIRouter()


@router.get("/training-phase-data")
async def get_training_phase_identification_data(
    difficulty: Literal["clean", "easy", "medium", "hard"] = Query("clean"),
):
    """
    Retrieves historical measurement data for all grids for training
    a phase detection algorithm

    Returns:
        dict: {
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
        # Get measurements filtered for phase detection training
        measurements = pi.get_all_measurements(
            cursor, task_type="phase_detection", phase_type="train"
        )

        # Difficulty profile (platform-controlled)
        profile = pi.get_corruption_profile(difficulty=difficulty)

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
            record = pi.corrupt_measurement_record(record, rngs[rng_key], profile)

            all_data[grid_id][node_id].append(record)

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


@router.get("/phase-data")
async def get_phase_identification_data(
    difficulty: Literal["clean", "easy", "medium", "hard"] = Query("clean"),
):
    """
    Retrieves historical measurement data for all grids,
    anonymising (node_id, phase) pairs using persistent random keys.

    Returns:
        dict: Dictionary mapping each grid_id to an inner dictionary of
        anonymised keys and their measurements, e.g.::

            {
                "grid_id1": {
                    "anonymised_key1": [ {"measurement1": ...}, ... ],
                    "anonymised_key2": [ {"measurement2": ...}, ... ],
                },
                "grid_id2": {
                    ...
                }
            }

    Raises:
        HTTPException: If no measurements are found or a database error occurs.
    """
    conn, cursor = db.get_db_connection()
    try:
        measurements = pi.get_all_measurements(
            cursor, task_type="phase_detection", phase_type="test"
        )

        mapping = pi.build_load_anon_keys(measurements, cursor)

        # Platform-controlled corruption profile (no user overrides)
        profile = pi.get_corruption_profile(difficulty=difficulty)

        # Seeded RNG per (grid_id, anon_key, difficulty) => deterministic across calls
        rngs: Dict[tuple, random.Random] = {}

        all_data = defaultdict(lambda: defaultdict(list))

        for grid_id, node_id, phase, dt, p_act, p_rea, v_mag, v_ang in measurements:
            anon_key = mapping[(grid_id, node_id, phase)]

            rng_key = (grid_id, anon_key)
            if rng_key not in rngs:
                seed = hashlib.sha256(f"{grid_id}:{anon_key}:{difficulty}".encode()).hexdigest()
                rngs[rng_key] = random.Random(seed)

            record = {
                "datetime": dt,
                "power_active": p_act,
                "power_reactive": p_rea,
                "voltage_magnitude": v_mag,
                "voltage_angle": v_ang,
            }

            # Apply perturbation only to measurement values (not datetime, not keys)
            record = pi.corrupt_measurement_record(record, rngs[rng_key], profile)

            all_data[grid_id][anon_key].append(record)

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
async def submit_phase_guesses(phase_guess: sc.PhaseGuessSubmission):
    """
    Endpoint to submit user guesses for the phases of anonymised measurement keys.
    The true phases are hidden. Guesses are stored in the database.

    Parameters:
        phase_guess (PhaseGuessSubmission): JSON with guess_id, grid_id and guesses.

    Returns:
        dict: Dictionary with submission status and submission, eg.::

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
        cursor.execute(
            'SELECT anonymised_key FROM "AnonymisedMapping" WHERE grid_id = %s',
            (phase_guess.grid_id,),
        )
        valid_keys = {row[0] for row in cursor.fetchall()}

        if not valid_keys:
            raise HTTPException(
                status_code=422,
                detail=f"No anonymised mapping found for grid '{phase_guess.grid_id}'. "
                       "Download phase data first to generate the mapping.",
            )

        invalid = set(phase_guess.guesses.keys()) - valid_keys
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown anonymised keys: {sorted(invalid)[:10]}. "
                       "Keys must match those returned by the phase-data endpoint.",
            )

        for anon_key, guessed_phase in phase_guess.guesses.items():
            cursor.execute(
                """
                INSERT INTO "UserGuesses" (guess_id, grid_id, anonymised_key, guessed_phase)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (guess_id, grid_id, anonymised_key)
                DO UPDATE SET
                    guessed_phase = EXCLUDED.guessed_phase,
                    timestamp = CURRENT_TIMESTAMP
                """,
                (phase_guess.guess_id, phase_guess.grid_id, anon_key, guessed_phase),
            )

        conn.commit()

        return {
            "status": "submitted",
            "accepted": len(phase_guess.guesses),
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
    Returns the guessing accuracy of a user for a given grid,
    without revealing the correct phases.

    Parameters:
        guess_id (str): The user making the guesses.
        grid_id (str): The grid for which the guesses were made.

    Returns:
        dict: Dictionary with the score and anciliary information
        of the submission guess, eg.::
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
        # Step 1: Get number of correct guesses
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM "UserGuesses" ug
            JOIN "AnonymisedMapping" am ON ug.anonymised_key = am.anonymised_key
            WHERE ug.guess_id = %s AND ug.grid_id = %s
              AND ug.guessed_phase = am.phase
            """,
            (guess_id, grid_id),
        )
        correct = cursor.fetchone()[0]

        # Step 2: Get total number of anonymised node-phase pairs in grid
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM "AnonymisedMapping"
            WHERE grid_id = %s
            """,
            (grid_id,),
        )
        total_nodes = cursor.fetchone()[0]

        accuracy = round(correct / total_nodes, 4) if total_nodes > 0 else 0.0

        return {
            "guess_id": guess_id,
            "grid_id": grid_id,
            "accuracy": accuracy,
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def phase_identification_ui(request: Request):
    """Main UI page for Phase Identification."""
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute("SELECT grid_id FROM grids ORDER BY grid_id")
        grids = [row[0] for row in cursor.fetchall()]
    except Exception:
        logger.warning("Failed to load grid list for Phase Identification UI", exc_info=True)
        grids = []
    finally:
        conn.close()

    return templates.TemplateResponse("benchmarks/phase_identification.html", {
        "request": request,
        "title": "Phase Identification",
        "active": "phase_mapping",
        "grids": grids,
    })
