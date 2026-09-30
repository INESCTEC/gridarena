"""Creates the sql database tables for the MV power-flow data-generation
pipeline's scenario output (bus / branch / Y-bus / runtime record groups).

Run metadata (config, status, progress) lives in run_config.json files under
gridarena/pf_datagen/runs/{run_id}/ -- same convention as the diffusion and RL
background jobs -- so these tables only hold the bulk per-scenario output,
keyed by an opaque run_id with no foreign key back to any run-metadata table.
"""


def create_mv_pf_bus_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "MVPFScenarioBus" (
            run_id TEXT NOT NULL,
            output_group_id TEXT NOT NULL,
            scenario_timestamp TEXT NOT NULL,
            topology_variant_idx INTEGER NOT NULL,
            node_id TEXT NOT NULL,
            pd DOUBLE PRECISION,
            qd DOUBLE PRECISION,
            vm DOUBLE PRECISION,
            va DOUBLE PRECISION,
            bus_type TEXT,
            PRIMARY KEY (run_id, output_group_id, node_id)
        );
        """
    )
    cursor.execute('CREATE INDEX IF NOT EXISTS mvpf_bus_run_idx ON "MVPFScenarioBus"(run_id);')


def create_mv_pf_branch_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "MVPFScenarioBranch" (
            run_id TEXT NOT NULL,
            output_group_id TEXT NOT NULL,
            scenario_timestamp TEXT NOT NULL,
            topology_variant_idx INTEGER NOT NULL,
            connection_id TEXT NOT NULL,
            from_node TEXT,
            to_node TEXT,
            pf DOUBLE PRECISION,
            qf DOUBLE PRECISION,
            r_ohm_total DOUBLE PRECISION,
            x_ohm_total DOUBLE PRECISION,
            in_service BOOLEAN,
            thermal_rating_a DOUBLE PRECISION,
            thermal_violation BOOLEAN,
            PRIMARY KEY (run_id, output_group_id, connection_id)
        );
        """
    )
    cursor.execute('CREATE INDEX IF NOT EXISTS mvpf_branch_run_idx ON "MVPFScenarioBranch"(run_id);')


def create_mv_pf_ybus_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "MVPFScenarioYbus" (
            run_id TEXT NOT NULL,
            output_group_id TEXT NOT NULL,
            scenario_timestamp TEXT NOT NULL,
            topology_variant_idx INTEGER NOT NULL,
            i_node TEXT NOT NULL,
            j_node TEXT NOT NULL,
            g DOUBLE PRECISION,
            b DOUBLE PRECISION,
            PRIMARY KEY (run_id, output_group_id, i_node, j_node)
        );
        """
    )
    cursor.execute('CREATE INDEX IF NOT EXISTS mvpf_ybus_run_idx ON "MVPFScenarioYbus"(run_id);')


def create_mv_pf_runtime_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "MVPFScenarioRuntime" (
            run_id TEXT NOT NULL,
            output_group_id TEXT NOT NULL,
            scenario_timestamp TEXT NOT NULL,
            topology_variant_idx INTEGER NOT NULL,
            solve_time_ms DOUBLE PRECISION,
            converged BOOLEAN NOT NULL,
            PRIMARY KEY (run_id, output_group_id)
        );
        """
    )
    cursor.execute('CREATE INDEX IF NOT EXISTS mvpf_runtime_run_idx ON "MVPFScenarioRuntime"(run_id);')


def create_pf_datagen_database(conn, cursor):
    """Ensures all PF data-generation output tables exist. Idempotent via IF NOT EXISTS."""
    try:
        create_mv_pf_bus_table(cursor)
        create_mv_pf_branch_table(cursor)
        create_mv_pf_ybus_table(cursor)
        create_mv_pf_runtime_table(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
