"""Functions to insert powerflow data on the databases"""


def insert_pf_data(node_id_to_index, volt_values, grid_id, phase, timestamp, cursor):

    q = """
        INSERT INTO "PowerFlowResults"
        (grid_id, node_id, phase, datetime, voltage_real, voltage_imag)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (grid_id, node_id, phase, datetime)
        DO UPDATE SET
            voltage_real = EXCLUDED.voltage_real,
            voltage_imag = EXCLUDED.voltage_imag
    """
    for node_id, idx in node_id_to_index.items():
        v = volt_values[idx]
        cursor.execute(
            q,
            (grid_id, node_id, phase, timestamp, v.real, v.imag),
        )
