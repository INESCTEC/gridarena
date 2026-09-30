"""Functions related to the insertion of data in database"""


def insert_grid_data(grid, conn, cursor, usage_data):
    insert_grid_entry(grid.grid_id, cursor)
    insert_nodes(grid, cursor)
    insert_cables(grid, cursor)
    insert_connections(grid, cursor)
    insert_grid_usage(grid.grid_id, usage_data, cursor)
    conn.commit()


def insert_grid_entry(grid_id, cursor):
    cursor.execute("INSERT INTO grids (grid_id) VALUES (%s)", (grid_id,))


def insert_nodes(grid, cursor):
    q = (
        'INSERT INTO "Node" ("NodeId", "CoordLat", "CoordLon", "CoordError", grid_id) '
        "VALUES (%s, %s, %s, %s, %s)"
    )
    for node in grid.nodes:
        cursor.execute(
            q,
            (
                node.node_id,
                node.coord_lat if node.coord_lat is not None else None,
                node.coord_lon if node.coord_lon is not None else None,
                node.coord_error if node.coord_error is not None else 0,
                grid.grid_id,
            ),
        )


def insert_cables(grid, cursor):
    if not grid.cables:
        return
    q = (
        'INSERT INTO "Cable" ('
        ' "CableId","RImpReal","RImpImag","SImpReal","SImpImag",'
        ' "TImpReal","TImpImag","RNomCurr","SNomCurr","TNomCurr", grid_id'
        ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    )
    for cable in grid.cables:
        cursor.execute(
            q,
            (
                cable.cable_id,
                cable.r_imp_real,
                cable.r_imp_imag,
                cable.s_imp_real,
                cable.s_imp_imag,
                cable.t_imp_real,
                cable.t_imp_imag,
                cable.r_nom_curr,
                cable.s_nom_curr,
                cable.t_nom_curr,
                grid.grid_id,
            ),
        )


def insert_connections(grid, cursor):
    if not grid.connections:
        return
    q = (
        'INSERT INTO "Connection" ('
        ' "ConnectionId","FromNodeId","ToNodeId","Length","CableId", grid_id'
        ") VALUES (%s,%s,%s,%s,%s,%s)"
    )
    for conn in grid.connections:
        cursor.execute(
            q,
            (
                conn.connection_id,
                conn.from_node_id,
                conn.to_node_id,
                conn.length,
                conn.cable_id,
                grid.grid_id,
            ),
        )

def insert_grid_usage(grid_id: str, usage_data: dict, cursor):
    """
    Insert or update the grid usage data (whether the grid is used for test or train).
    
    :param grid_id: The unique identifier of the grid
    :param usage_data: A dictionary containing the usage information (test/train for each problem)
    :param cursor: The database cursor
    """
    cursor.execute("""
        INSERT INTO GridUsage (grid_id, phase_detection_test, phase_detection_train, 
                               topology_detection_test, topology_detection_train, 
                               voltage_control_test, voltage_control_train, 
                               state_estimation_test, state_estimation_train)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (grid_id) DO UPDATE
        SET phase_detection_test = EXCLUDED.phase_detection_test,
            phase_detection_train = EXCLUDED.phase_detection_train,
            topology_detection_test = EXCLUDED.topology_detection_test,
            topology_detection_train = EXCLUDED.topology_detection_train,
            voltage_control_test = EXCLUDED.voltage_control_test,
            voltage_control_train = EXCLUDED.voltage_control_train,
            state_estimation_test = EXCLUDED.state_estimation_test,
            state_estimation_train = EXCLUDED.state_estimation_train;
    """, (
        grid_id,
        usage_data.get('phase_detection_test', 0),
        usage_data.get('phase_detection_train', 0),
        usage_data.get('topology_detection_test', 0),
        usage_data.get('topology_detection_train', 0),
        usage_data.get('voltage_control_test', 0),
        usage_data.get('voltage_control_train', 0),
        usage_data.get('state_estimation_test', 0),
        usage_data.get('state_estimation_train', 0),
    ))
