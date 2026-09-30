"""Creates the sql database tables for the mapping between grid and hash"""

def create_grid_anon_map_database(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "GridAnonymisedMapping" (
            grid_id TEXT PRIMARY KEY,
            anonymised_grid_key TEXT NOT NULL UNIQUE,
            CONSTRAINT fk_gridanon_grid
                FOREIGN KEY (grid_id)
                REFERENCES "Grid"(grid_id)
                ON UPDATE CASCADE
                ON DELETE CASCADE
        );
        """
    )