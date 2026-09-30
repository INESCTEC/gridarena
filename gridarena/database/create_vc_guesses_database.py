"""Creates the sql database tables for the user voltage control guesses"""


def create_vc_guesses_database(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "VCUserGuesses" (
            user_id TEXT NOT NULL,
            grid_id TEXT NOT NULL,
            anonymised_key TEXT NOT NULL,
            guessed_voltages TEXT NOT NULL,
            guessed_loads TEXT NOT NULL,
            timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT vcuserguesses_pk
                PRIMARY KEY (user_id, grid_id, anonymised_key),
            CONSTRAINT vcuserguesses_grid_fk
                FOREIGN KEY (grid_id)
                    REFERENCES grids(grid_id) ON DELETE CASCADE,
            CONSTRAINT vcuserguesses_anon_fk
                FOREIGN KEY (anonymised_key)
                    REFERENCES "VoltageTimestampMapping"(anonymised_key)
                    ON DELETE CASCADE
        );
        """
    )

