"""Functions to insert node/grid-scoped measurement data on the databases"""


def insert_measurements_data(measurements_data, conn, cursor):
    """
    Inserts measurement data into HistoricalNodes and Measurements.
    - Supports multiple entries for the same node_id at the same datetime if 'phase' differs.
    - If m.phase is None, stores an aggregated row (phase=NULL).
    """
    try:
        grid_id = measurements_data.grid_id

        # Upsert HistoricalNodes rows
        for node_data in measurements_data.historical:
            node_id = node_data.node_id
            cursor.execute(
                """
                INSERT INTO "HistoricalNodes" (node_id, grid_id)
                VALUES (%s, %s)
                ON CONFLICT ON CONSTRAINT historicalnodes_pk DO NOTHING
                """,
                (node_id, grid_id),
            )

            # Measurements upsert per reading
            q = (
                'INSERT INTO "Measurements" ('
                " node_id, grid_id, datetime, phase, "
                " power_active, power_reactive, voltage_magnitude, voltage_angle"
                ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT ON CONSTRAINT measurements_unique DO UPDATE SET "
                " power_active = EXCLUDED.power_active, "
                " power_reactive = EXCLUDED.power_reactive, "
                " voltage_magnitude = EXCLUDED.voltage_magnitude, "
                " voltage_angle = EXCLUDED.voltage_angle"
            )

            for m in node_data.measurements:
                cursor.execute(
                    q,
                    (
                        node_id,
                        grid_id,
                        m.datetime,              # ISO string or datetime; psycopg handles both
                        getattr(m, "phase", None),
                        m.power_active,
                        m.power_reactive,
                        m.voltage_magnitude,
                        m.voltage_angle,
                    ),
                )

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise Exception(f"Database error while inserting measurement data: {e}")
