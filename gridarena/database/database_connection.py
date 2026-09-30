"""Initialize the connection with the database"""

import os
import threading
from typing import Optional, Tuple

import psycopg
from psycopg_pool import ConnectionPool


def _dsn() -> str:
    """
    Returns the PostgreSQL DSN from env. Supports both GRID_DB_DSN and DATABASE_URL.
    """
    dsn = os.getenv("GRID_DB_DSN") or os.getenv("DATABASE_URL")
    if not dsn:
        raise ValueError("GRID_DB_DSN (or DATABASE_URL) environment variable is not set")
    return dsn


class _PooledConnection(psycopg.Connection):
    """A Connection whose close() returns it to the pool instead of tearing
    down the socket -- lets every existing `conn.close()` call site keep
    working unchanged while the connection is actually reused underneath.

    Relies on `_pool` being set by psycopg_pool itself on every connection
    it dispenses via getconn() (used internally by its own putconn() checks)
    -- do not assign to it ourselves, that collides with the pool's own
    bookkeeping and makes putconn() reject the connection.
    """

    def close(self) -> None:
        pool = getattr(self, "_pool", None)
        if pool is not None:
            pool.putconn(self)
        else:
            super().close()


_pool: Optional[ConnectionPool] = None
_pool_lock = threading.Lock()


def _reset_connection(conn: psycopg.Connection) -> None:
    """Runs when a connection is returned to the pool -- rolls back any
    transaction a caller left open on an error path that skipped an explicit
    rollback, so every checked-out connection starts clean. No-op if idle."""
    conn.rollback()


def _get_pool() -> ConnectionPool:
    """Lazily creates a connection pool local to the current OS process.

    Each spawned subprocess (pf_datagen/rl/diffusion background jobs run via
    ProcessPoolExecutor) gets its own pool the first time it calls
    get_db_connection() -- a pool created in the main API process can't be
    shared across a spawn boundary.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(
                    conninfo=_dsn(),
                    connection_class=_PooledConnection,
                    min_size=int(os.getenv("DB_POOL_MIN_SIZE", "2")),
                    max_size=int(os.getenv("DB_POOL_MAX_SIZE", "10")),
                    kwargs={"autocommit": False},
                    reset=_reset_connection,
                    open=True,
                )
    return _pool


def close_pool() -> None:
    """Closes the process-local pool, if one was created. Call on app shutdown."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def get_db_connection() -> Tuple[psycopg.Connection, psycopg.Cursor]:
    """
    Check out a pooled PostgreSQL connection (psycopg3) and a cursor.

    Returns:
        (conn, cursor)
    """
    pool = _get_pool()
    conn = pool.getconn()
    cursor = conn.cursor()
    return conn, cursor
