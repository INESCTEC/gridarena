"""Creates the sql database tables for historical databases.

A "database" here is a named collection of standalone historical series
("historicals") that all share the exact same timeline -- see
"HistoricalTimestamp" below, which every "HistoricalRecords" row must
reference. Unlike Measurements (node/grid-scoped, see
create_measurements_database.py), none of this is tied to any registered
grid or node.
"""


def create_historical_database_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "HistoricalDatabase" (
            database_id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT
        );
        """
    )


def create_historical_timestamp_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "HistoricalTimestamp" (
            database_id TEXT NOT NULL
                REFERENCES "HistoricalDatabase"(database_id) ON DELETE CASCADE,
            datetime TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            PRIMARY KEY (database_id, datetime)
        );
        """
    )


def create_historical_series_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "HistoricalSeries" (
            database_id TEXT NOT NULL
                REFERENCES "HistoricalDatabase"(database_id) ON DELETE CASCADE,
            series_id TEXT NOT NULL,
            grid_level TEXT NOT NULL
                CONSTRAINT historical_series_grid_level_chk CHECK (grid_level IN ('MV','LV','Feeder')),
            name TEXT,
            description TEXT,
            PRIMARY KEY (database_id, series_id)
        );
        """
    )
    # The table may already exist from before "Feeder" was added as a valid
    # grid_level -- CREATE TABLE IF NOT EXISTS won't touch its old CHECK
    # constraint, so widen it explicitly (idempotent: no-op once migrated).
    cursor.execute(
        """
        DO $$
        DECLARE
            con record;
        BEGIN
            FOR con IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = '"HistoricalSeries"'::regclass
                  AND contype = 'c'
                  AND conname <> 'historical_series_grid_level_chk'
                  AND pg_get_constraintdef(oid) LIKE '%grid_level%'
            LOOP
                EXECUTE format('ALTER TABLE "HistoricalSeries" DROP CONSTRAINT %I', con.conname);
            END LOOP;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'historical_series_grid_level_chk'
            ) THEN
                ALTER TABLE "HistoricalSeries"
                    ADD CONSTRAINT historical_series_grid_level_chk
                    CHECK (grid_level IN ('MV','LV','Feeder'));
            END IF;
        END $$;
        """
    )


def create_historical_records_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "HistoricalRecords" (
            record_id BIGSERIAL PRIMARY KEY,
            database_id TEXT NOT NULL,
            series_id TEXT NOT NULL,
            datetime TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            phase TEXT DEFAULT NULL,
            power_active DOUBLE PRECISION,
            power_reactive DOUBLE PRECISION,
            voltage_magnitude DOUBLE PRECISION,
            voltage_angle DOUBLE PRECISION,
            CONSTRAINT historical_records_phase_chk CHECK (phase IN ('R','S','T') OR phase IS NULL),
            CONSTRAINT historical_records_has_value
                CHECK (power_active IS NOT NULL OR voltage_magnitude IS NOT NULL),
            CONSTRAINT historical_records_series_fk
                FOREIGN KEY (database_id, series_id)
                REFERENCES "HistoricalSeries"(database_id, series_id)
                ON DELETE CASCADE,
            CONSTRAINT historical_records_timestamp_fk
                FOREIGN KEY (database_id, datetime)
                REFERENCES "HistoricalTimestamp"(database_id, datetime)
                ON DELETE CASCADE,
            CONSTRAINT historical_records_unique UNIQUE (database_id, series_id, datetime, phase)
        );
        """
    )
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS historical_records_series_time_idx '
        'ON "HistoricalRecords"(database_id, series_id, datetime);'
    )
    # The table may already exist from before this FK had ON DELETE CASCADE --
    # CREATE TABLE IF NOT EXISTS won't touch it, so widen it explicitly here
    # (idempotent: no-op once migrated). Without this, deleting a database
    # with any records fails with a foreign key violation (HistoricalRecords
    # still references the HistoricalTimestamp rows being cascade-deleted).
    cursor.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'historical_records_timestamp_fk'
                  AND conrelid = '"HistoricalRecords"'::regclass
                  AND confdeltype <> 'c'
            ) THEN
                ALTER TABLE "HistoricalRecords" DROP CONSTRAINT historical_records_timestamp_fk;
                ALTER TABLE "HistoricalRecords"
                    ADD CONSTRAINT historical_records_timestamp_fk
                    FOREIGN KEY (database_id, datetime)
                    REFERENCES "HistoricalTimestamp"(database_id, datetime)
                    ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )


def create_historical_data_tables(cursor):
    """
    Creates the tables required to store historical databases.

    This includes:
    - HistoricalDatabase: Registers each database (its name/description).
    - HistoricalTimestamp: The shared timeline every series in the database must use.
    - HistoricalSeries: Registers each series ("historical") within a database.
    - HistoricalRecords: Stores the power/voltage values for each series.

    Parameters:
        cursor (psycopg.Cursor): PostgreSQL cursor used to execute SQL commands.
    """

    create_historical_database_table(cursor)
    create_historical_timestamp_table(cursor)
    create_historical_series_table(cursor)
    create_historical_records_table(cursor)
