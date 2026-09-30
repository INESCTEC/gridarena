"""Creates the sql database tables for the mapping between (node,phase) and hash"""


def create_anon_map_database(cursor):
    """
    Creates the PostgreSQL table that maps (grid_id, node_id, phase) to anonymised_key.

    This references the physical nodes table "Node" using a composite foreign key
    (node_id, grid_id) → "Node"("NodeId", grid_id).
    """
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "AnonymisedMapping" (
            grid_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            anonymised_key TEXT NOT NULL UNIQUE,
            CONSTRAINT anonymisedmapping_pk
                PRIMARY KEY (grid_id, node_id, phase),
            CONSTRAINT anonymisedmapping_grid_fk
                FOREIGN KEY (grid_id)
                    REFERENCES grids(grid_id) ON DELETE CASCADE,
            CONSTRAINT anonymisedmapping_node_fk
                FOREIGN KEY (node_id, grid_id)
                    REFERENCES "Node"("NodeId", grid_id) ON DELETE CASCADE,
            CONSTRAINT anonymisedmapping_phase_chk
                CHECK (phase IN ('R','S','T'))
        );
        """
    )
