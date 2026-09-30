"""Creates the sql database tables for the user phase guesses"""


def create_phase_guesses_database(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "UserGuesses" (
            user_id TEXT NOT NULL,
            grid_id TEXT NOT NULL,
            anonymised_key TEXT NOT NULL,
            guessed_phase TEXT NOT NULL,
            timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT userguesses_pk
                PRIMARY KEY (user_id, grid_id, anonymised_key),
            CONSTRAINT userguesses_grid_fk
                FOREIGN KEY (grid_id)
                    REFERENCES grids(grid_id) ON DELETE CASCADE,
            CONSTRAINT userguesses_anon_fk
                FOREIGN KEY (anonymised_key)
                    REFERENCES "AnonymisedMapping"(anonymised_key)
                    ON DELETE CASCADE,
            CONSTRAINT userguesses_phase_chk
                CHECK (guessed_phase IN ('R','S','T'))
        );
        """
    )
