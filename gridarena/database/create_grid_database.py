"""This script creates the PostgreSQL tables for registering a new grid and its associated tables (grids, Node, Cable, Connection, Lines)."""

from .exceptions import NotFoundError


def create_grids_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS grids(
            grid_id TEXT PRIMARY KEY
        );
        """
    )

def create_grid_usage_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS GridUsage (
            grid_id TEXT PRIMARY KEY,
            phase_detection_test INTEGER DEFAULT 0,
            phase_detection_train INTEGER DEFAULT 0,
            topology_detection_test INTEGER DEFAULT 0,
            topology_detection_train INTEGER DEFAULT 0,
            voltage_control_test INTEGER DEFAULT 0,
            voltage_control_train INTEGER DEFAULT 0,
            state_estimation_test INTEGER DEFAULT 0,
            state_estimation_train INTEGER DEFAULT 0,
            CONSTRAINT grid_usage_fk FOREIGN KEY (grid_id)
                REFERENCES grids(grid_id) ON DELETE CASCADE
        );
        """
    )

def create_node_table(cursor):
    # Composite PK (NodeId, grid_id) so that FKs from Connection can reference it properly
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "Node" (
            "NodeId" VARCHAR(20) NOT NULL,
            "CoordLat" DOUBLE PRECISION,
            "CoordLon" DOUBLE PRECISION,
            "CoordError" INTEGER DEFAULT 0,
            grid_id TEXT NOT NULL,
            CONSTRAINT node_pk PRIMARY KEY ("NodeId", grid_id),
            CONSTRAINT node_grid_fk FOREIGN KEY (grid_id)
                REFERENCES grids(grid_id) ON DELETE CASCADE
        );
        """
    )


def create_cable_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "Cable" (
            "CableId" VARCHAR(20) NOT NULL,
            "RImpReal" DOUBLE PRECISION,
            "RImpImag" DOUBLE PRECISION,
            "SImpReal" DOUBLE PRECISION,
            "SImpImag" DOUBLE PRECISION,
            "TImpReal" DOUBLE PRECISION,
            "TImpImag" DOUBLE PRECISION,
            "RNomCurr" DOUBLE PRECISION,
            "SNomCurr" DOUBLE PRECISION,
            "TNomCurr" DOUBLE PRECISION,
            grid_id TEXT NOT NULL,
            CONSTRAINT cable_pk PRIMARY KEY ("CableId", grid_id),
            CONSTRAINT cable_grid_fk FOREIGN KEY (grid_id)
                REFERENCES grids(grid_id) ON DELETE CASCADE
        );
        """
    )


def create_connection_table(cursor):
    # Composite FKs to Node and Cable ensure referential integrity per-grid.
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "Connection" (
            "ConnectionId" VARCHAR(20) NOT NULL,
            "CableId" VARCHAR(20),
            "Length" INTEGER,
            "FromNodeId" VARCHAR(20),
            "ToNodeId" VARCHAR(20),
            grid_id TEXT NOT NULL,
            CONSTRAINT connection_pk PRIMARY KEY ("ConnectionId", grid_id),
            CONSTRAINT connection_grid_fk FOREIGN KEY (grid_id)
                REFERENCES grids(grid_id) ON DELETE CASCADE,
            CONSTRAINT connection_fromnode_fk FOREIGN KEY ("FromNodeId", grid_id)
                REFERENCES "Node"("NodeId", grid_id) ON DELETE CASCADE,
            CONSTRAINT connection_tonode_fk FOREIGN KEY ("ToNodeId", grid_id)
                REFERENCES "Node"("NodeId", grid_id) ON DELETE CASCADE,
            CONSTRAINT connection_cable_fk FOREIGN KEY ("CableId", grid_id)
                REFERENCES "Cable"("CableId", grid_id) ON DELETE CASCADE
        );
        """
    )


def create_grid_database(grid_id, conn, cursor):
    """
    Ensures required tables exist. In PostgreSQL, IF NOT EXISTS makes this idempotent.
    """
    try:
        create_grids_table(cursor)
        create_grid_usage_table(cursor)  
        create_node_table(cursor)
        create_cable_table(cursor)
        create_connection_table(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def delete_grid(grid_id: str, conn, cursor):
    """
    Deletes a grid. ON DELETE CASCADE takes care of dependent rows.
    Raises an Exception if the grid does not exist.
    """
    # Check existence
    cursor.execute("SELECT 1 FROM grids WHERE grid_id = %s", (grid_id,))
    if cursor.fetchone() is None:
        raise NotFoundError(f"Grid '{grid_id}' not found.")

    # Delete (cascades)
    cursor.execute("DELETE FROM grids WHERE grid_id = %s", (grid_id,))
    conn.commit()