"""Creates the sql database tables for the node/grid-scoped measurement data"""


def create_historical_nodes_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "HistoricalNodes" (
            node_id TEXT NOT NULL,
            grid_id TEXT NOT NULL,
            CONSTRAINT historicalnodes_pk PRIMARY KEY (node_id, grid_id),
            CONSTRAINT historicalnodes_grid_fk
                FOREIGN KEY (grid_id) REFERENCES grids(grid_id) ON DELETE CASCADE
        );
        """
    )


def create_measurements_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "Measurements" (
            measurement_id BIGSERIAL PRIMARY KEY,
            node_id TEXT NOT NULL,
            grid_id TEXT NOT NULL,
            datetime TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            phase TEXT DEFAULT NULL,
            power_active DOUBLE PRECISION NOT NULL,
            power_reactive DOUBLE PRECISION NOT NULL,
            voltage_magnitude DOUBLE PRECISION NOT NULL,
            voltage_angle DOUBLE PRECISION NOT NULL,
            CONSTRAINT measurements_phase_chk CHECK (phase IN ('R','S','T') OR phase IS NULL),
            CONSTRAINT measurements_node_fk
                FOREIGN KEY (node_id, grid_id)
                REFERENCES "HistoricalNodes"(node_id, grid_id)
                ON DELETE CASCADE,
            CONSTRAINT measurements_unique UNIQUE (node_id, grid_id, datetime, phase)
        );
        """
    )
    # Helpful index for typical range scans
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS measurements_grid_time_idx '
        'ON "Measurements"(grid_id, datetime);'
    )


def create_measurements_tables(cursor):
    """
    Creates the tables required to store node/grid-scoped measurement data.

    This includes:
    - HistoricalNodes: Links each node to a grid.
    - Measurements: Stores timestamped electrical measurements for each node.

    Parameters:
        cursor (psycopg.Cursor): PostgreSQL cursor used to execute SQL commands.
    """

    create_historical_nodes_table(cursor)
    create_measurements_table(cursor)
