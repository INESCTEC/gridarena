def create_state_estimates_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS StateEstimates (
            user_id TEXT NOT NULL,
            estimation_id TEXT NOT NULL,
            grid_id TEXT NOT NULL,
            timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            node_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            voltage_magnitude DOUBLE PRECISION NOT NULL,
            voltage_angle DOUBLE PRECISION NOT NULL,
            CONSTRAINT stateestimates_pk
                PRIMARY KEY (user_id, estimation_id, grid_id, timestamp, node_id, phase),
            CONSTRAINT stateestimates_grid_fk
                FOREIGN KEY (grid_id)
                    REFERENCES grids(grid_id) ON DELETE CASCADE,
            CONSTRAINT stateestimates_node_fk
                FOREIGN KEY (node_id, grid_id)
                    REFERENCES "HistoricalNodes"(node_id, grid_id)
                    ON DELETE CASCADE
        );
        """
    )


def create_base_tables(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS GridMask (
            grid_id TEXT PRIMARY KEY,
            masked_id TEXT UNIQUE
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS NodeMask (
            grid_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            masked_node_id TEXT NOT NULL,
            CONSTRAINT nodemask_pk
                PRIMARY KEY (grid_id, node_id, phase),
            CONSTRAINT nodemask_unique_mask
                UNIQUE (grid_id, masked_node_id),
            CONSTRAINT nodemask_grid_fk
                FOREIGN KEY (grid_id)
                    REFERENCES grids(grid_id) ON DELETE CASCADE
        );
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS EstimationTasks (
            user_id TEXT NOT NULL,
            estimation_id TEXT NOT NULL,
            grid_id TEXT NOT NULL,
            timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            node_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            known INTEGER NOT NULL,
            CONSTRAINT estimationtasks_pk
                PRIMARY KEY (user_id, estimation_id, grid_id, node_id, phase, timestamp),
            CONSTRAINT estimationtasks_grid_fk
                FOREIGN KEY (grid_id)
                    REFERENCES grids(grid_id) ON DELETE CASCADE
        );
        """
    )
