"""Powerflow Endpoint Helper Functions for Topology Data Retrieval"""

import numpy as np


def get_nodes_from_grid(grid_id, cursor):
    """
    Retrieves the list of unique node IDs associated with a specific grid.

    This function queries the database for all distinct node IDs associated with the provided
    `grid_id`. The node IDs are returned in a dictionary where the keys are the node IDs and
    the values are the corresponding indices. The node "PT" (if present) is moved to the beginning
    of the list.

    Parameters:
        grid_id (str): The unique identifier of the grid for which to retrieve node IDs.
        cursor (psycopg.Cursor): The database cursor used to execute the query.

    Raises:
        Exception: If no nodes are found for the given `grid_id`.

    Returns:
        dict: A dictionary where the keys are the node IDs and the values are the corresponding
              indices in the list, with "PT" moved to the beginning if it exists.

    Example:
        >>> cursor = db_connection.cursor()
        >>> get_nodes_from_grid("grid001", cursor)
        {'PT': 0, 'node1': 1, 'node2': 2, 'node3': 3}
    """

    cursor.execute('SELECT DISTINCT "NodeId" FROM "Node" WHERE grid_id = %s', (grid_id,))
    node_rows = cursor.fetchall()

    if not node_rows:
        raise Exception("No nodes found.")

    node_ids = [row[0] for row in node_rows]

    if "PT" in node_ids:
        node_ids.remove("PT")
        node_ids.insert(0, "PT")

    return {node_id: idx for idx, node_id in enumerate(node_ids)}


def get_grid_connections(cursor, grid_id, node_id_to_index):
    """
    Retrieves the list of connections for a given grid, along with their associated
    cable identifiers and lengths, and returns two data structures:

    1. A list of connections as [from_index, to_index], where indices correspond
       to node positions defined in node_id_to_index.
    2. A list of tuples (cable_id, length) for each connection, preserving order.

    Parameters:
        cursor (psycopg.Cursor): Active database cursor for executing queries.
        grid_id (str): Identifier of the grid to retrieve connections for.
        node_id_to_index (dict): Mapping from node IDs to index positions.

    Returns:
        tuple:
            - List[List[int, int]]: Connections as index pairs.
            - List[Tuple[str, float]]: Corresponding cable ID and connection length.

    Raises:
        Exception: If no connections are found for the given grid.

    Example:
        >>> get_grid_connections(cursor, "grid001", {'PT': 0, 'N1': 1, 'N2': 2})
        ([[0, 1], [1, 2]], [('CBL1', 100.0), ('CBL1', 120.0)])
    """

    cursor.execute(
        'SELECT "FromNodeId", "ToNodeId", "CableId", "Length" '
        'FROM "Connection" WHERE grid_id = %s',
        (grid_id,),
    )
    conn_rows = cursor.fetchall()

    if not conn_rows:
        raise Exception("No connections found.")

    connections = []
    conn_data = []

    for from_node, to_node, cable_id, length in conn_rows:
        fi = node_id_to_index[from_node]
        ti = node_id_to_index[to_node]
        connections.append([fi, ti])
        conn_data.append((cable_id, length))

    return connections, conn_data


def get_grid_admitances(cursor, conn_data):
    """
    Computes the admittances (Y = 1/Z) for each grid connection based on the
    associated cable's impedance and the physical length of the connection.

    Cable impedances are specified in ohm/km while connection lengths are stored
    in metres, so the length is converted to km before computing Z = (R + jX) * L.

    Parameters:
        cursor (psycopg.Cursor): Active database cursor for executing queries.
        conn_data (List[Tuple[str, float]]): A list of tuples, each containing:
            - cable_id (str): Identifier of the cable used in the connection.
            - length (float): Length of the connection segment in metres.

    Returns:
        np.ndarray: A NumPy array of shape (N, 1), where each element is a complex
                    admittance [1 / (Z × length)] corresponding to a connection.

    Raises:
        Exception: If no cable data is found for the provided cable IDs.
        Exception: If any connection has zero total impedance (Z × length = 0).

    Example:
        >>> # lengths in metres are converted to km before Y = 1 / (Z * L_km)
        >>> get_grid_admitances(cursor, [('CBL1', 100.0), ('CBL1', 120.0)])
        array([[12.5-1.25j],
               [10.4-1.04j]])
    """

    cable_ids = tuple(set(cid for cid, _ in conn_data))

    cursor.execute(
        f"""
        SELECT "CableId", "RImpReal", "RImpImag"
        FROM "Cable"
        WHERE "CableId" IN ({','.join(['%s'] * len(cable_ids))})
        """,
        cable_ids,
    )

    cable_rows = cursor.fetchall()
    if not cable_rows:
        raise Exception("Cable data not found.")

    cable_imp = {cid: complex(r, x) for cid, r, x in cable_rows}

    admittances = []
    for cid, L in conn_data:
        # R/X are in ohm/km; convert length from metres to km for a total Z in ohm.
        z = cable_imp[cid] * (L / 1000.0)
        if z == 0:
            raise Exception(f"Zero impedance for cable {cid}")
        admittances.append([1 / z])

    return np.array(admittances)
