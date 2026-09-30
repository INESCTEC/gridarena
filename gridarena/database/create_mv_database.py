"""Creates the database tables for Medium Voltage grids."""

from .exceptions import NotFoundError


def create_mv_grids_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "MVGrid" (
            mv_grid_id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            nominal_voltage_kv DOUBLE PRECISION NOT NULL,
            region TEXT
        );
        """
    )


def create_mv_node_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "MVNode" (
            "NodeId" VARCHAR(40) NOT NULL,
            mv_grid_id TEXT NOT NULL,
            "CoordLat" DOUBLE PRECISION,
            "CoordLon" DOUBLE PRECISION,
            "NodeType" VARCHAR(20),
            CONSTRAINT mv_node_pk PRIMARY KEY ("NodeId", mv_grid_id),
            CONSTRAINT mv_node_grid_fk FOREIGN KEY (mv_grid_id)
                REFERENCES "MVGrid"(mv_grid_id) ON DELETE CASCADE
        );
        """
    )


def create_mv_cable_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "MVCable" (
            "CableId" VARCHAR(40) NOT NULL,
            mv_grid_id TEXT NOT NULL,
            "ImpReal" DOUBLE PRECISION,
            "ImpImag" DOUBLE PRECISION,
            "NomCurr" DOUBLE PRECISION,
            CONSTRAINT mv_cable_pk PRIMARY KEY ("CableId", mv_grid_id),
            CONSTRAINT mv_cable_grid_fk FOREIGN KEY (mv_grid_id)
                REFERENCES "MVGrid"(mv_grid_id) ON DELETE CASCADE
        );
        """
    )


def create_mv_connection_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "MVConnection" (
            "ConnectionId" VARCHAR(40) NOT NULL,
            mv_grid_id TEXT NOT NULL,
            "FromNodeId" VARCHAR(40),
            "ToNodeId" VARCHAR(40),
            "CableId" VARCHAR(40),
            "Length" DOUBLE PRECISION,
            CONSTRAINT mv_connection_pk PRIMARY KEY ("ConnectionId", mv_grid_id),
            CONSTRAINT mv_connection_grid_fk FOREIGN KEY (mv_grid_id)
                REFERENCES "MVGrid"(mv_grid_id) ON DELETE CASCADE,
            CONSTRAINT mv_connection_from_fk FOREIGN KEY ("FromNodeId", mv_grid_id)
                REFERENCES "MVNode"("NodeId", mv_grid_id) ON DELETE CASCADE,
            CONSTRAINT mv_connection_to_fk FOREIGN KEY ("ToNodeId", mv_grid_id)
                REFERENCES "MVNode"("NodeId", mv_grid_id) ON DELETE CASCADE,
            CONSTRAINT mv_connection_cable_fk FOREIGN KEY ("CableId", mv_grid_id)
                REFERENCES "MVCable"("CableId", mv_grid_id) ON DELETE CASCADE
        );
        """
    )


def create_mv_connection_point_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "MVConnectionPoint" (
            "ConnectionPointId" VARCHAR(40) NOT NULL,
            mv_grid_id TEXT NOT NULL,
            "NodeId" VARCHAR(40) NOT NULL,
            "Name" TEXT,
            CONSTRAINT mv_cp_pk PRIMARY KEY ("ConnectionPointId", mv_grid_id),
            CONSTRAINT mv_cp_grid_fk FOREIGN KEY (mv_grid_id)
                REFERENCES "MVGrid"(mv_grid_id) ON DELETE CASCADE,
            CONSTRAINT mv_cp_node_fk FOREIGN KEY ("NodeId", mv_grid_id)
                REFERENCES "MVNode"("NodeId", mv_grid_id) ON DELETE CASCADE
        );
        """
    )


def create_mv_transformer_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "MVTransformer" (
            "TransformerId" VARCHAR(40) NOT NULL,
            mv_grid_id TEXT NOT NULL,
            "ConnectionPointId" VARCHAR(40) NOT NULL,
            lv_grid_id TEXT,
            "RatedPowerKVA" DOUBLE PRECISION NOT NULL,
            "PrimaryVoltageKV" DOUBLE PRECISION NOT NULL,
            "SecondaryVoltageV" DOUBLE PRECISION DEFAULT 230.0,
            "ImpReal" DOUBLE PRECISION,
            "ImpImag" DOUBLE PRECISION,
            "Name" TEXT,
            "Status" VARCHAR(20) DEFAULT 'active',
            CONSTRAINT mv_transformer_pk PRIMARY KEY ("TransformerId", mv_grid_id),
            CONSTRAINT mv_transformer_grid_fk FOREIGN KEY (mv_grid_id)
                REFERENCES "MVGrid"(mv_grid_id) ON DELETE CASCADE,
            CONSTRAINT mv_transformer_cp_fk FOREIGN KEY ("ConnectionPointId", mv_grid_id)
                REFERENCES "MVConnectionPoint"("ConnectionPointId", mv_grid_id) ON DELETE CASCADE,
            CONSTRAINT mv_transformer_lv_fk FOREIGN KEY (lv_grid_id)
                REFERENCES grids(grid_id) ON DELETE SET NULL,
            CONSTRAINT mv_transformer_unique_lv UNIQUE (mv_grid_id, "ConnectionPointId", lv_grid_id)
        );
        """
    )


def create_mv_database(conn, cursor):
    """Ensures all MV tables exist. Idempotent via IF NOT EXISTS."""
    try:
        create_mv_grids_table(cursor)
        create_mv_node_table(cursor)
        create_mv_cable_table(cursor)
        create_mv_connection_table(cursor)
        create_mv_connection_point_table(cursor)
        create_mv_transformer_table(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def delete_mv_grid(mv_grid_id: str, conn, cursor):
    cursor.execute('SELECT 1 FROM "MVGrid" WHERE mv_grid_id = %s', (mv_grid_id,))
    if cursor.fetchone() is None:
        raise NotFoundError(f"MV Grid '{mv_grid_id}' not found.")
    cursor.execute('DELETE FROM "MVGrid" WHERE mv_grid_id = %s', (mv_grid_id,))
    conn.commit()
