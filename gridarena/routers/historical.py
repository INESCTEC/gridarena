"""Historical Router with endpoints to register, access and delete historical
databases -- named collections of standalone power/voltage series ("historicals")
that all share one timeline. See gridarena/schemas/historical_data.py.
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

import gridarena.database as db
from gridarena.schemas import HistoricalDatabaseUpload

from ._upload_guard import ensure_upload_size_ok

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

# Safety cap for unbounded list queries (e.g. no start/end filter given) --
# prevents a single request from serializing the entire HistoricalRecords
# table (41.8M+ rows in the real dataset).
MAX_RECORDS_PER_REQUEST = 50_000


@router.post("/")
async def upload_historical_database(file: UploadFile = File(...)):
    """
    Uploads and inserts a historical database -- a shared timeline plus any
    number of series ("historicals") -- into the database from a JSON file.

    Parameters:
        file (UploadFile): A JSON file containing the database to be uploaded.

    Raises:
        HTTPException 400: If the file is not valid JSON.
        HTTPException 422: If the file does not conform to the HistoricalDatabaseUpload
            schema (including a value whose datetime isn't in the declared timestamps).
        HTTPException 500: If a database error occurs during the insertion.

    Returns:
        dict: A success message with the database ID.
    """
    ensure_upload_size_ok(file)
    try:
        contents = await file.read()
        data = json.loads(contents.decode("utf-8"))
        database_upload = HistoricalDatabaseUpload(**data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format.")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    conn, cursor = db.get_db_connection()

    try:
        db.create_historical_data_tables(cursor)
        db.insert_historical_data(database_upload, conn, cursor)
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()

    _invalidate_historical_cache()

    n_series = len(database_upload.historicals)
    return {
        "message": f"Historical database '{database_upload.database_id}' "
                   f"inserted successfully ({n_series} series)."
    }


@router.delete("/{database_id}")
async def delete_historical_database(database_id: str):
    """
    Deletes an entire historical database, including its timeline and every
    series/record within it (via ON DELETE CASCADE).

    Parameters:
        database_id (str): The database to delete.

    Raises:
        HTTPException 500: If a database error occurs.

    Returns:
        dict: A message indicating whether a database was deleted.
    """
    conn, cursor = db.get_db_connection()

    try:
        cursor.execute('DELETE FROM "HistoricalDatabase" WHERE database_id = %s', (database_id,))
        deleted_count = cursor.rowcount
        conn.commit()

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()

    _invalidate_historical_cache(database_id)

    return {"message": f"{deleted_count} database(s) deleted for '{database_id}'."}


@router.delete("/{database_id}/{series_id}")
async def delete_historical_series_records(
    database_id: str,
    series_id: str,
    start: Optional[str] = Query(None, description="Start datetime ISO (inclusive)"),
    end: Optional[str] = Query(None, description="End datetime ISO (exclusive)"),
    phase: Optional[Literal["R", "S", "T"]] = Query(
        None, description="Optional phase filter; omit to delete aggregated + all phases"
    ),
):
    """
    Deletes records for one series within a database. The series and
    database registrations are left in place even if this empties its records.

    Parameters:
        database_id (str): The database the series belongs to.
        series_id (str): The series to delete records from.
        start (str, optional): ISO start datetime (inclusive).
        end (str, optional): ISO end datetime (exclusive).
        phase (str, optional): Filter by phase (R/S/T).

    Raises:
        HTTPException 400: If an invalid datetime format is provided.
        HTTPException 500: If a database error occurs.

    Returns:
        dict: A message indicating how many records were deleted.
    """
    try:
        start_dt = datetime.fromisoformat(start) if start else None
        end_dt = datetime.fromisoformat(end) if end else None

    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid datetime format. Use ISO format (e.g. 2025-07-31T00:00:00)",
        )

    conn, cursor = db.get_db_connection()

    try:
        query = 'DELETE FROM "HistoricalRecords" WHERE database_id = %s AND series_id = %s'
        params: list[object] = [database_id, series_id]

        if phase is not None:
            query += " AND phase = %s"
            params.append(phase)
        if start_dt:
            query += " AND datetime >= %s"
            params.append(start_dt)
        if end_dt:
            query += " AND datetime < %s"
            params.append(end_dt)

        cursor.execute(query, tuple(params))
        deleted_count = cursor.rowcount
        conn.commit()

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()

    _invalidate_historical_cache(database_id)

    return {"message": f"{deleted_count} record(s) deleted for series '{series_id}' in database '{database_id}'."}


@router.get("/data/{database_id}/{series_id}")
async def get_historical_series_data(
    database_id: str,
    series_id: str,
    start: Optional[str] = Query(None, description="Start datetime (inclusive, ISO format)"),
    end: Optional[str] = Query(None, description="End datetime (exclusive, ISO format)"),
    phase: Optional[Literal["R", "S", "T"]] = Query(None, description="Optional single phase filter"),
):
    """
    Retrieves records for one series within a database.

    Parameters:
        database_id (str): The database the series belongs to.
        series_id (str): The series to retrieve records for.
        start / end (str, optional): ISO datetime range.
        phase (str, optional): Single phase filter.

    Raises:
        HTTPException 400/404/500 as appropriate.

    Returns:
        dict: Series data with records and count.
    """
    try:
        start_dt = datetime.fromisoformat(start) if start else None
        end_dt = datetime.fromisoformat(end) if end else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format. Use ISO format.")

    conn, cursor = db.get_db_connection()

    try:
        cursor.execute(
            'SELECT series_id, grid_level, name, description FROM "HistoricalSeries" '
            "WHERE database_id = %s AND series_id = %s",
            (database_id, series_id),
        )
        series_row = cursor.fetchone()
        if series_row is None:
            raise HTTPException(
                status_code=404, detail=f"Series '{series_id}' not found in database '{database_id}'."
            )

        sql = """
            SELECT datetime, phase, power_active, power_reactive, voltage_magnitude, voltage_angle
            FROM "HistoricalRecords"
            WHERE database_id = %s AND series_id = %s
        """
        params: list[object] = [database_id, series_id]

        if start_dt:
            sql += " AND datetime >= %s"
            params.append(start_dt)
        if end_dt:
            sql += " AND datetime < %s"
            params.append(end_dt)
        if phase:
            sql += " AND phase = %s"
            params.append(phase)

        sql += " ORDER BY datetime ASC LIMIT %s"
        params.append(MAX_RECORDS_PER_REQUEST + 1)

        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()

        truncated = len(rows) > MAX_RECORDS_PER_REQUEST
        if truncated:
            rows = rows[:MAX_RECORDS_PER_REQUEST]

        columns = ["datetime", "phase", "power_active", "power_reactive", "voltage_magnitude", "voltage_angle"]
        data = [dict(zip(columns, row)) for row in rows]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()

    return {
        "database_id": database_id,
        "series_id": series_row[0],
        "grid_level": series_row[1],
        "name": series_row[2],
        "description": series_row[3],
        "datetime_range": {"start": start, "end": end},
        "records": data,
        "count": len(data),
        "truncated": truncated,
        **({"truncation_hint": f"Result capped at {MAX_RECORDS_PER_REQUEST} records; narrow with start/end."} if truncated else {}),
    }


def _classify_grid_level(n_mv: int, n_lv: int, n_feeder: int) -> str:
    """Which single grid_level a database's series share, for consumers
    (like PF Data Generation) that require homogeneity. "Mixed" if more
    than one level is present, "Empty" if the database has no series."""
    present = [level for level, n in (("MV", n_mv), ("LV", n_lv), ("Feeder", n_feeder)) if n > 0]
    if len(present) == 1:
        return present[0]
    return "Mixed" if present else "Empty"


def _fetch_database_summaries(cursor) -> list[dict]:
    cursor.execute(
        """
        SELECT d.database_id, d.name,
               COALESCE(sc.n_series, 0) AS n_series,
               COALESCE(sc.n_mv, 0) AS n_mv,
               COALESCE(sc.n_lv, 0) AS n_lv,
               COALESCE(sc.n_feeder, 0) AS n_feeder,
               COALESCE(rc.n_records, 0) AS n_records,
               tr.first_ts, tr.last_ts
        FROM "HistoricalDatabase" d
        LEFT JOIN (
            SELECT database_id, COUNT(*) AS n_series,
                   COUNT(*) FILTER (WHERE grid_level = 'MV') AS n_mv,
                   COUNT(*) FILTER (WHERE grid_level = 'LV') AS n_lv,
                   COUNT(*) FILTER (WHERE grid_level = 'Feeder') AS n_feeder
            FROM "HistoricalSeries"
            GROUP BY database_id
        ) sc ON sc.database_id = d.database_id
        LEFT JOIN (
            SELECT database_id, COUNT(*) AS n_records
            FROM "HistoricalRecords"
            GROUP BY database_id
        ) rc ON rc.database_id = d.database_id
        LEFT JOIN (
            SELECT database_id, MIN(datetime) AS first_ts, MAX(datetime) AS last_ts
            FROM "HistoricalTimestamp"
            GROUP BY database_id
        ) tr ON tr.database_id = d.database_id
        ORDER BY d.database_id COLLATE "C" ASC
        """
    )
    return [{
        "database_id": r[0],
        "name": r[1],
        "n_series": r[2],
        "n_mv": r[3],
        "n_lv": r[4],
        "n_feeder": r[5],
        "n_records": r[6],
        "first_ts": str(r[7])[:16] if r[7] else None,
        "last_ts": str(r[8])[:16] if r[8] else None,
    } for r in cursor.fetchall()]


# ---------- Aggregate-query cache ----------
#
# _fetch_database_summaries() and the per-database series summary below both
# aggregate over "HistoricalRecords", which can be tens of millions of rows
# (e.g. the feeder_measurements import this session is 41.8M rows / 20GB) --
# EXPLAIN ANALYZE showed ~30-40s for either query, almost entirely disk I/O
# from a Seq Scan that no index avoids (nearly every row has to be touched
# regardless). Cached here with a TTL, invalidated eagerly by every write
# endpoint below so the common in-app case never waits on the TTL; the TTL
# itself is a safety net for out-of-band changes (e.g. a bulk COPY script
# run directly against Postgres, outside this process).
#
# historical_ui_root/historical_ui_database are plain `def`s, which FastAPI
# runs in a thread pool -- concurrent requests can genuinely race on this
# shared state, so the locks below are load-bearing, not defensive filler.

_CACHE_TTL_SECONDS = 300

_summary_cache: dict = {"value": None, "expires_at": 0.0}
_summary_cache_lock = threading.Lock()

_series_summary_cache: dict[str, dict] = {}
_series_summary_cache_lock = threading.Lock()


def _invalidate_historical_cache(database_id: Optional[str] = None) -> None:
    """Called after any upload/delete so the next read recomputes instead of
    serving a stale snapshot. Always clears the list-level cache; also drops
    `database_id`'s per-database cache entry if one changed/was deleted."""
    with _summary_cache_lock:
        _summary_cache["value"] = None
        _summary_cache["expires_at"] = 0.0
    if database_id is not None:
        with _series_summary_cache_lock:
            _series_summary_cache.pop(database_id, None)


def _fetch_database_summaries_cached(cursor) -> list[dict]:
    now = time.monotonic()
    with _summary_cache_lock:
        if _summary_cache["value"] is not None and now < _summary_cache["expires_at"]:
            return _summary_cache["value"]
    value = _fetch_database_summaries(cursor)
    with _summary_cache_lock:
        _summary_cache["value"] = value
        _summary_cache["expires_at"] = now + _CACHE_TTL_SECONDS
    return value


def _fetch_series_summary(database_id: str, cursor) -> list[dict]:
    cursor.execute(
        """
        SELECT s.series_id, s.grid_level, s.name,
               COUNT(r.record_id) AS n_records,
               COUNT(r.power_active) AS n_power,
               COUNT(r.voltage_magnitude) AS n_voltage
        FROM "HistoricalSeries" s
        LEFT JOIN "HistoricalRecords" r
            ON r.database_id = s.database_id AND r.series_id = s.series_id
        WHERE s.database_id = %s
        GROUP BY s.series_id, s.grid_level, s.name
        ORDER BY s.series_id COLLATE "C" ASC
        """,
        (database_id,),
    )
    return [{
        "series_id": r[0],
        "grid_level": r[1],
        "name": r[2],
        "n_records": r[3],
        "has_power": r[4] > 0,
        "has_voltage": r[5] > 0,
    } for r in cursor.fetchall()]


def _fetch_series_summary_cached(database_id: str, cursor) -> list[dict]:
    now = time.monotonic()
    with _series_summary_cache_lock:
        entry = _series_summary_cache.get(database_id)
        if entry is not None and now < entry["expires_at"]:
            return entry["value"]
    value = _fetch_series_summary(database_id, cursor)
    with _series_summary_cache_lock:
        _series_summary_cache[database_id] = {"value": value, "expires_at": now + _CACHE_TTL_SECONDS}
    return value


# ---------- JSON: DATABASES SUMMARY (for the PF Data Generation source picker) ----------


@router.get("/databases")
async def list_historical_databases():
    """All historical databases with their detected grid_level ("MV"/"LV"/
    "Feeder"/"Mixed"/"Empty"), for populating a data-source picker elsewhere
    in the app (e.g. PF Data Generation)."""
    conn, cursor = db.get_db_connection()
    try:
        items = _fetch_database_summaries_cached(cursor)
    except Exception:
        items = []
    finally:
        conn.close()

    for item in items:
        item["grid_level"] = _classify_grid_level(item["n_mv"], item["n_lv"], item["n_feeder"])

    return items


# ---------- UI: ROOT (list of databases) ----------


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def historical_ui_root(request: Request) -> HTMLResponse:
    conn, cursor = db.get_db_connection()
    try:
        items = _fetch_database_summaries_cached(cursor)
    except Exception:
        items = []
    finally:
        conn.close()

    total_records = sum(d["n_records"] for d in items)
    total_series = sum(d["n_series"] for d in items)

    return templates.TemplateResponse("historical/list.html", {
        "request": request,
        "title": "Historical",
        "active": "historical",
        "items": items,
        "total_records": total_records,
        "total_series": total_series,
    })


# ---------- UI: DATABASE DETAIL (list of series within it) ----------


@router.get("/ui/{database_id}", response_class=HTMLResponse, include_in_schema=False)
def historical_ui_database(request: Request, database_id: str) -> HTMLResponse:
    conn, cursor = db.get_db_connection()
    try:
        cursor.execute(
            'SELECT database_id, name, description FROM "HistoricalDatabase" WHERE database_id = %s',
            (database_id,),
        )
        database_row = cursor.fetchone()
        if database_row is None:
            raise HTTPException(status_code=404, detail=f"Database '{database_id}' not found.")

        series_items = _fetch_series_summary_cached(database_id, cursor)

        cursor.execute(
            'SELECT MIN(datetime), MAX(datetime), COUNT(*) FROM "HistoricalTimestamp" WHERE database_id = %s',
            (database_id,),
        )
        first_ts, last_ts, n_timestamps = cursor.fetchone()
    except HTTPException:
        raise
    finally:
        conn.close()

    return templates.TemplateResponse("historical/database.html", {
        "request": request,
        "title": f"Historical: {database_id}",
        "active": "historical",
        "database_id": database_row[0],
        "name": database_row[1],
        "description": database_row[2],
        "series_items": series_items,
        "n_timestamps": n_timestamps or 0,
        "first_ts": str(first_ts)[:16] if first_ts else None,
        "last_ts": str(last_ts)[:16] if last_ts else None,
    })


# ---------- UI: SERIES DETAIL ----------


@router.get("/ui/{database_id}/{series_id}", response_class=HTMLResponse, include_in_schema=False)
def historical_ui_series(
    request: Request,
    database_id: str,
    series_id: str,
    start: str | None = Query(None),
    end: str | None = Query(None),
    phase: list[str] | None = Query(None),
) -> HTMLResponse:
    """Dashboard view for a single series within a database."""
    conn, cursor = db.get_db_connection()

    try:
        cursor.execute(
            'SELECT series_id, grid_level, name, description FROM "HistoricalSeries" '
            "WHERE database_id = %s AND series_id = %s",
            (database_id, series_id),
        )
        series_row = cursor.fetchone()
        if series_row is None:
            raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found in database '{database_id}'.")

        selected_phases = [p for p in (phase or []) if p in {"R", "S", "T"}]

        query = (
            "SELECT datetime, phase, power_active, power_reactive, voltage_magnitude, voltage_angle "
            'FROM "HistoricalRecords" WHERE database_id = %s AND series_id = %s'
        )
        params: list[object] = [database_id, series_id]

        if start:
            query += " AND datetime >= %s"
            params.append(start)
        if end:
            query += " AND datetime <= %s"
            params.append(end)
        if selected_phases:
            query += " AND phase = ANY(%s)"
            params.append(selected_phases)

        query += " ORDER BY datetime ASC, phase ASC LIMIT %s"
        params.append(MAX_RECORDS_PER_REQUEST)

        df = pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()

    grid_level = series_row[1]
    name = series_row[2]
    description = series_row[3]

    if df.empty:
        return templates.TemplateResponse("historical/detail.html", {
            "request": request,
            "title": f"Historical: {series_id}",
            "active": "historical",
            "database_id": database_id,
            "series_id": series_id,
            "grid_level": grid_level,
            "name": name,
            "description": description,
            "empty": True,
        })

    df["datetime"] = df["datetime"].astype(str)
    df["phase"] = df["phase"].fillna("N/A").astype(str)

    records = df.to_dict(orient="records")
    all_phases = sorted([p for p in df["phase"].unique().tolist() if p != "N/A"])
    has_power = df["power_active"].notna().any()
    has_voltage = df["voltage_magnitude"].notna().any()

    checked_r = not selected_phases or "R" in selected_phases
    checked_s = not selected_phases or "S" in selected_phases
    checked_t = not selected_phases or "T" in selected_phases

    return templates.TemplateResponse("historical/detail.html", {
        "request": request,
        "title": f"Historical: {series_id}",
        "active": "historical",
        "database_id": database_id,
        "series_id": series_id,
        "grid_level": grid_level,
        "name": name,
        "description": description,
        "empty": False,
        "start": start,
        "end": end,
        "checked_r": checked_r,
        "checked_s": checked_s,
        "checked_t": checked_t,
        "records": records,
        "all_phases": all_phases,
        "has_power": bool(has_power),
        "has_voltage": bool(has_voltage),
        "record_count": len(records),
    })
