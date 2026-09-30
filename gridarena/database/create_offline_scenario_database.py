"""Creates the PostgreSQL tables for the Offline Scenario feature."""


def create_offline_scenario_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "OfflineScenario" (
            scenario_id TEXT PRIMARY KEY,
            source_dt_id TEXT NOT NULL,
            grid_id TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            grid_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            connection_changes JSONB NOT NULL DEFAULT '[]'::jsonb,
            power_limits JSONB NOT NULL DEFAULT '{}'::jsonb,
            powerflow_config JSONB NOT NULL DEFAULT '{}'::jsonb,
            simulation_status TEXT NOT NULL DEFAULT 'pending'
                CHECK (simulation_status IN ('pending', 'running', 'completed', 'failed', 'partially_completed')),
            total_timestamps INTEGER NOT NULL DEFAULT 0,
            completed_timestamps INTEGER NOT NULL DEFAULT 0,
            failed_timestamps INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMP WITHOUT TIME ZONE,
            error TEXT
        );
        """
    )


def create_offline_scenario_result_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "OfflineScenarioResult" (
            result_id BIGSERIAL PRIMARY KEY,
            scenario_id TEXT NOT NULL,
            "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            convergence_status TEXT NOT NULL DEFAULT 'unknown',
            node_voltages JSONB,
            execution_time_ms DOUBLE PRECISION,
            error TEXT,
            CONSTRAINT osr_scenario_fk
                FOREIGN KEY (scenario_id)
                REFERENCES "OfflineScenario"(scenario_id) ON DELETE CASCADE,
            CONSTRAINT osr_unique UNIQUE (scenario_id, "timestamp")
        );
        """
    )
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS osr_scenario_time_idx '
        'ON "OfflineScenarioResult"(scenario_id, "timestamp" ASC);'
    )


def create_offline_scenario_tables(cursor):
    create_offline_scenario_table(cursor)
    create_offline_scenario_result_table(cursor)
