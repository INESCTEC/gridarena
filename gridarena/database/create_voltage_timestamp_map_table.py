def create_voltage_timestamp_map_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "VoltageTimestampMapping" (
            grid_id TEXT NOT NULL,
            datetime TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            anonymised_key TEXT NOT NULL UNIQUE,
            CONSTRAINT voltagetimestampmapping_pk
                PRIMARY KEY (grid_id, datetime),
            CONSTRAINT voltagetimestampmapping_grid_fk
                FOREIGN KEY (grid_id)
                    REFERENCES grids(grid_id) ON DELETE CASCADE
        );
        """
    )