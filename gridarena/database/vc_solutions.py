def create_voltage_control_solutions(cursor):
    """
    Creates tables used by the voltage-control subservice:
      - VoltageControlSolutions: stores user-submitted solutions for a grid snapshot (grid_id + datetime).
      - index on (grid_id, datetime) for fast lookups.
    """

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "VoltageControlSolutions" (
            solution_id BIGSERIAL PRIMARY KEY,
            grid_id TEXT NOT NULL,
            datetime TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            node_id TEXT NOT NULL,
            phase TEXT CHECK (phase IN ('R','S','T')) DEFAULT NULL,
            corrected_voltage DOUBLE PRECISION NOT NULL,
            adjusted_power_active DOUBLE PRECISION,
            adjusted_power_reactive DOUBLE PRECISION,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT vcs_grid_fk
                FOREIGN KEY (grid_id)
                    REFERENCES grids(grid_id) ON DELETE CASCADE,
            CONSTRAINT vcs_node_fk
                FOREIGN KEY (node_id, grid_id)
                    REFERENCES "HistoricalNodes"(node_id, grid_id)
                    ON DELETE CASCADE
        );
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vcs_grid_datetime
        ON "VoltageControlSolutions" (grid_id, datetime);
        """
    )
