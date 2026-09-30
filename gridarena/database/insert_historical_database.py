"""Functions to insert historical databases (many series sharing one timeline)."""


def insert_historical_data(database_upload, conn, cursor):
    """
    Inserts a historical database -- its shared timeline and every series
    ("historical") within it -- into HistoricalDatabase, HistoricalTimestamp,
    HistoricalSeries and HistoricalRecords.

    Re-uploading the same database_id refreshes its metadata, adds any new
    timestamps, and upserts each series' metadata and records.
    """
    try:
        database_id = database_upload.database_id

        cursor.execute(
            """
            INSERT INTO "HistoricalDatabase" (database_id, name, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (database_id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description
            """,
            (database_id, database_upload.name, database_upload.description),
        )

        cursor.executemany(
            """
            INSERT INTO "HistoricalTimestamp" (database_id, datetime)
            VALUES (%s, %s)
            ON CONFLICT (database_id, datetime) DO NOTHING
            """,
            [(database_id, ts) for ts in database_upload.timestamps],
        )

        series_q = (
            'INSERT INTO "HistoricalSeries" ('
            " database_id, series_id, grid_level, name, description"
            ") VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (database_id, series_id) DO UPDATE SET "
            " grid_level = EXCLUDED.grid_level, "
            " name = EXCLUDED.name, "
            " description = EXCLUDED.description"
        )

        records_q = (
            'INSERT INTO "HistoricalRecords" ('
            " database_id, series_id, datetime, phase, "
            " power_active, power_reactive, voltage_magnitude, voltage_angle"
            ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT ON CONSTRAINT historical_records_unique DO UPDATE SET "
            " power_active = EXCLUDED.power_active, "
            " power_reactive = EXCLUDED.power_reactive, "
            " voltage_magnitude = EXCLUDED.voltage_magnitude, "
            " voltage_angle = EXCLUDED.voltage_angle"
        )

        for historical in database_upload.historicals:
            series_id = historical.series_id
            cursor.execute(
                series_q,
                (database_id, series_id, historical.grid_level, historical.name, historical.description),
            )

            for v in historical.values:
                cursor.execute(
                    records_q,
                    (
                        database_id,
                        series_id,
                        v.datetime,
                        getattr(v, "phase", None),
                        v.power_active,
                        v.power_reactive,
                        v.voltage_magnitude,
                        v.voltage_angle,
                    ),
                )

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise Exception(f"Database error while inserting historical data: {e}")
