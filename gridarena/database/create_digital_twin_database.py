"""Creates the PostgreSQL tables for the Digital Twin feature."""


def create_digital_twin_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "DigitalTwin" (
            digital_twin_id TEXT PRIMARY KEY,
            grid_id TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'created'
                CHECK (status IN ('created', 'running', 'stopped', 'failed')),
            update_interval_seconds INTEGER NOT NULL DEFAULT 60,
            broker_type TEXT NOT NULL DEFAULT 'redis',
            broker_topic TEXT NOT NULL DEFAULT '',
            source_config JSONB NOT NULL DEFAULT '{}'::jsonb,
            field_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
            powerflow_config JSONB NOT NULL DEFAULT '{}'::jsonb,
            latest_batch JSONB,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            last_run_at TIMESTAMP WITHOUT TIME ZONE,
            last_error TEXT,
            CONSTRAINT dt_grid_fk
                FOREIGN KEY (grid_id) REFERENCES grids(grid_id) ON DELETE CASCADE
        );
        """
    )
    cursor.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'DigitalTwin' AND column_name = 'latest_batch'
            ) THEN
                ALTER TABLE "DigitalTwin" ADD COLUMN latest_batch JSONB;
            END IF;
        END $$;
        """
    )


def create_digital_twin_event_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "DigitalTwinEvent" (
            event_id BIGSERIAL PRIMARY KEY,
            digital_twin_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            details JSONB,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT dte_dt_fk
                FOREIGN KEY (digital_twin_id)
                REFERENCES "DigitalTwin"(digital_twin_id) ON DELETE CASCADE
        );
        """
    )
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS dte_dt_time_idx '
        'ON "DigitalTwinEvent"(digital_twin_id, created_at DESC);'
    )


def create_digital_twin_result_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "DigitalTwinResult" (
            result_id BIGSERIAL PRIMARY KEY,
            digital_twin_id TEXT NOT NULL,
            "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            measurements_count INTEGER NOT NULL DEFAULT 0,
            missing_measurements INTEGER NOT NULL DEFAULT 0,
            invalid_measurements INTEGER NOT NULL DEFAULT 0,
            convergence_status TEXT NOT NULL DEFAULT 'unknown',
            voltage_mae DOUBLE PRECISION,
            voltage_rmse DOUBLE PRECISION,
            max_voltage_error DOUBLE PRECISION,
            active_power_error DOUBLE PRECISION,
            reactive_power_error DOUBLE PRECISION,
            execution_time_ms DOUBLE PRECISION,
            powerflow_algorithm TEXT NOT NULL DEFAULT 'backward_forward_sweep',
            details JSONB,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT dtr_dt_fk
                FOREIGN KEY (digital_twin_id)
                REFERENCES "DigitalTwin"(digital_twin_id) ON DELETE CASCADE
        );
        """
    )
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS dtr_dt_time_idx '
        'ON "DigitalTwinResult"(digital_twin_id, "timestamp" DESC);'
    )


def create_digital_twin_tables(cursor):
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS grids(grid_id TEXT PRIMARY KEY);"
    )
    create_digital_twin_table(cursor)
    create_digital_twin_event_table(cursor)
    create_digital_twin_result_table(cursor)
