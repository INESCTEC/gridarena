"""Creates the sql database tables for the powerflow results data"""


def create_pf_database(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "PowerFlowResults" (
            grid_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            datetime TEXT NOT NULL,
            voltage_real DOUBLE PRECISION NOT NULL,
            voltage_imag DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (grid_id, node_id, phase, datetime),
            FOREIGN KEY (grid_id) REFERENCES grids(grid_id) ON DELETE CASCADE,
            FOREIGN KEY (node_id, grid_id)
                REFERENCES "Node"("NodeId", grid_id) ON DELETE CASCADE
        );
        """
    )
