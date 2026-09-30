"""Insert and query functions for Medium Voltage grid data."""

from .exceptions import NotFoundError


def insert_mv_grid_data(mv_grid, conn, cursor):
    """Insert a full MV grid (header, nodes, cables, connections, connection points, transformers)."""
    _insert_mv_grid_entry(mv_grid, cursor)
    _insert_mv_nodes(mv_grid, cursor)
    _insert_mv_cables(mv_grid, cursor)
    _insert_mv_connections(mv_grid, cursor)
    _insert_mv_connection_points(mv_grid, cursor)
    _insert_mv_transformers(mv_grid, cursor)
    conn.commit()


def _insert_mv_grid_entry(mv_grid, cursor):
    cursor.execute(
        'INSERT INTO "MVGrid" (mv_grid_id, name, description, nominal_voltage_kv, region) '
        "VALUES (%s, %s, %s, %s, %s)",
        (mv_grid.mv_grid_id, mv_grid.name, mv_grid.description,
         mv_grid.nominal_voltage_kv, mv_grid.region),
    )


def _insert_mv_nodes(mv_grid, cursor):
    q = (
        'INSERT INTO "MVNode" ("NodeId", mv_grid_id, "CoordLat", "CoordLon", "NodeType") '
        "VALUES (%s, %s, %s, %s, %s)"
    )
    for node in mv_grid.nodes:
        cursor.execute(q, (node.node_id, mv_grid.mv_grid_id,
                           node.coord_lat, node.coord_lon, node.node_type))


def _insert_mv_cables(mv_grid, cursor):
    if not mv_grid.cables:
        return
    q = (
        'INSERT INTO "MVCable" ("CableId", mv_grid_id, "ImpReal", "ImpImag", "NomCurr") '
        "VALUES (%s, %s, %s, %s, %s)"
    )
    for cable in mv_grid.cables:
        cursor.execute(q, (cable.cable_id, mv_grid.mv_grid_id,
                           cable.imp_real, cable.imp_imag, cable.nom_curr))


def _insert_mv_connections(mv_grid, cursor):
    if not mv_grid.connections:
        return
    q = (
        'INSERT INTO "MVConnection" ("ConnectionId", mv_grid_id, "FromNodeId", "ToNodeId", "CableId", "Length") '
        "VALUES (%s, %s, %s, %s, %s, %s)"
    )
    for conn in mv_grid.connections:
        cursor.execute(q, (conn.connection_id, mv_grid.mv_grid_id,
                           conn.from_node_id, conn.to_node_id, conn.cable_id, conn.length))


def _insert_mv_connection_points(mv_grid, cursor):
    if not mv_grid.connection_points:
        return
    q = (
        'INSERT INTO "MVConnectionPoint" ("ConnectionPointId", mv_grid_id, "NodeId", "Name") '
        "VALUES (%s, %s, %s, %s)"
    )
    for cp in mv_grid.connection_points:
        cursor.execute(q, (cp.connection_point_id, mv_grid.mv_grid_id,
                           cp.node_id, cp.name))


def _insert_mv_transformers(mv_grid, cursor):
    if not mv_grid.transformers:
        return
    q = (
        'INSERT INTO "MVTransformer" '
        '("TransformerId", mv_grid_id, "ConnectionPointId", lv_grid_id, '
        '"RatedPowerKVA", "PrimaryVoltageKV", "SecondaryVoltageV", '
        '"ImpReal", "ImpImag", "Name", "Status") '
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    for t in mv_grid.transformers:
        cursor.execute(q, (
            t.transformer_id, mv_grid.mv_grid_id, t.connection_point_id,
            t.lv_grid_id, t.rated_power_kva, t.primary_voltage_kv,
            t.secondary_voltage_v, t.imp_real, t.imp_imag, t.name, t.status,
        ))


def connect_lv_to_mv(mv_grid_id, connection_point_id, lv_grid_id,
                      transformer_id, rated_power_kva, primary_voltage_kv,
                      secondary_voltage_v, imp_real, imp_imag, name, conn, cursor):
    """Connect an existing LV grid to an MV connection point via a new transformer."""
    cursor.execute(
        'SELECT 1 FROM "MVConnectionPoint" WHERE "ConnectionPointId" = %s AND mv_grid_id = %s',
        (connection_point_id, mv_grid_id),
    )
    if cursor.fetchone() is None:
        raise Exception(f"Connection point '{connection_point_id}' not found in MV grid '{mv_grid_id}'.")

    cursor.execute("SELECT 1 FROM grids WHERE grid_id = %s", (lv_grid_id,))
    if cursor.fetchone() is None:
        raise Exception(f"LV grid '{lv_grid_id}' not found.")

    cursor.execute(
        'SELECT 1 FROM "MVTransformer" WHERE mv_grid_id = %s AND "ConnectionPointId" = %s AND lv_grid_id = %s',
        (mv_grid_id, connection_point_id, lv_grid_id),
    )
    if cursor.fetchone() is not None:
        raise Exception(f"LV grid '{lv_grid_id}' is already connected to point '{connection_point_id}'.")

    cursor.execute(
        'INSERT INTO "MVTransformer" '
        '("TransformerId", mv_grid_id, "ConnectionPointId", lv_grid_id, '
        '"RatedPowerKVA", "PrimaryVoltageKV", "SecondaryVoltageV", '
        '"ImpReal", "ImpImag", "Name", "Status") '
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')",
        (transformer_id, mv_grid_id, connection_point_id, lv_grid_id,
         rated_power_kva, primary_voltage_kv, secondary_voltage_v,
         imp_real, imp_imag, name),
    )
    conn.commit()


def disconnect_lv_from_mv(mv_grid_id, connection_point_id, lv_grid_id, conn, cursor):
    """Remove the transformer bridge between an MV connection point and an LV grid."""
    cursor.execute(
        'DELETE FROM "MVTransformer" WHERE mv_grid_id = %s AND "ConnectionPointId" = %s AND lv_grid_id = %s',
        (mv_grid_id, connection_point_id, lv_grid_id),
    )
    if cursor.rowcount == 0:
        raise Exception(f"No connection found between point '{connection_point_id}' and LV grid '{lv_grid_id}'.")
    conn.commit()


def get_mv_grid_list(cursor):
    cursor.execute('SELECT mv_grid_id, name, nominal_voltage_kv, region FROM "MVGrid" ORDER BY mv_grid_id')
    return [{"mv_grid_id": r[0], "name": r[1], "nominal_voltage_kv": r[2], "region": r[3]}
            for r in cursor.fetchall()]


def get_mv_grid_detail(mv_grid_id, cursor):
    cursor.execute('SELECT mv_grid_id, name, description, nominal_voltage_kv, region FROM "MVGrid" WHERE mv_grid_id = %s', (mv_grid_id,))
    row = cursor.fetchone()
    if row is None:
        raise NotFoundError(f"MV Grid '{mv_grid_id}' not found.")
    grid = {"mv_grid_id": row[0], "name": row[1], "description": row[2], "nominal_voltage_kv": row[3], "region": row[4]}

    cursor.execute('SELECT "NodeId", "CoordLat", "CoordLon", "NodeType" FROM "MVNode" WHERE mv_grid_id = %s', (mv_grid_id,))
    grid["nodes"] = [{"node_id": r[0], "coord_lat": r[1], "coord_lon": r[2], "node_type": r[3]} for r in cursor.fetchall()]

    cursor.execute('SELECT "ConnectionId", "FromNodeId", "ToNodeId", "CableId", "Length" FROM "MVConnection" WHERE mv_grid_id = %s', (mv_grid_id,))
    grid["connections"] = [{"connection_id": r[0], "from_node_id": r[1], "to_node_id": r[2], "cable_id": r[3], "length": r[4]} for r in cursor.fetchall()]

    cursor.execute('SELECT "ConnectionPointId", "NodeId", "Name" FROM "MVConnectionPoint" WHERE mv_grid_id = %s', (mv_grid_id,))
    grid["connection_points"] = [{"connection_point_id": r[0], "node_id": r[1], "name": r[2]} for r in cursor.fetchall()]

    cursor.execute(
        'SELECT "TransformerId", "ConnectionPointId", lv_grid_id, "RatedPowerKVA", "PrimaryVoltageKV", '
        '"SecondaryVoltageV", "ImpReal", "ImpImag", "Name", "Status" '
        'FROM "MVTransformer" WHERE mv_grid_id = %s', (mv_grid_id,),
    )
    grid["transformers"] = [{
        "transformer_id": r[0], "connection_point_id": r[1], "lv_grid_id": r[2],
        "rated_power_kva": r[3], "primary_voltage_kv": r[4], "secondary_voltage_v": r[5],
        "imp_real": r[6], "imp_imag": r[7], "name": r[8], "status": r[9],
    } for r in cursor.fetchall()]

    return grid


def get_aggregated_pv(lv_grid_id, cursor, limit=500):
    """Return aggregated P/Q/V per timestamp for an LV grid from the Measurements table.

    Returns the average power_active, power_reactive and voltage_magnitude per
    timestamp across all nodes/phases, ordered by time -- a representative
    per-meter profile, used for the "View P/V" chart on the MV grid detail page.
    Not a total load figure: see get_summed_pv() for that (used by the PF
    data-generation pipeline).
    """
    query = """
        SELECT datetime,
               AVG(power_active) AS avg_power,
               AVG(power_reactive) AS avg_reactive,
               AVG(voltage_magnitude) AS avg_voltage
        FROM "Measurements"
        WHERE grid_id = %s AND phase IS NOT NULL
        GROUP BY datetime
        ORDER BY datetime ASC
    """
    params = [lv_grid_id]
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)

    cursor.execute(query, params)
    return [
        {"datetime": str(r[0]), "avg_power_active": r[1], "avg_power_reactive": r[2], "avg_voltage_magnitude": r[3]}
        for r in cursor.fetchall()
    ]


def get_summed_pv(lv_grid_id, cursor, limit=None):
    """Return total P/Q per timestamp for an LV grid from the Measurements table.

    Returns the sum of power_active and power_reactive per timestamp across
    all nodes/phases, ordered by time -- the LV grid's total real/reactive
    power draw at that instant, i.e. what the MV/LV transformer's secondary
    side actually carries (by power conservation). Used by the PF
    data-generation pipeline as the MV connection-point injection; unlike
    get_aggregated_pv(), this is not sensitive to how many points the LV
    grid happens to have metered. Pass limit=None to fetch the full history.
    """
    query = """
        SELECT datetime,
               SUM(power_active) AS total_power,
               SUM(power_reactive) AS total_reactive
        FROM "Measurements"
        WHERE grid_id = %s AND phase IS NOT NULL
        GROUP BY datetime
        ORDER BY datetime ASC
    """
    params = [lv_grid_id]
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)

    cursor.execute(query, params)
    return [
        {"datetime": str(r[0]), "total_power_active": r[1], "total_power_reactive": r[2]}
        for r in cursor.fetchall()
    ]
