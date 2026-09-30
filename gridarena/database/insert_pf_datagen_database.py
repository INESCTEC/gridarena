"""Insert/query functions for the MV power-flow data-generation pipeline's
bulk scenario output (bus / branch / Y-bus / runtime record groups)."""


def insert_pf_datagen_batch(run_id, bus_rows, branch_rows, ybus_rows, runtime_rows, conn, cursor):
    """Batch-insert one chunk of scenario output rows and commit.

    Each *_rows list holds plain tuples matching the column order below
    (run_id is prepended here so callers don't have to repeat it per row).
    """
    if runtime_rows:
        cursor.executemany(
            """
            INSERT INTO "MVPFScenarioRuntime"
            (run_id, output_group_id, scenario_timestamp, topology_variant_idx, solve_time_ms, converged)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, output_group_id) DO NOTHING
            """,
            [(run_id, *row) for row in runtime_rows],
        )
    if bus_rows:
        cursor.executemany(
            """
            INSERT INTO "MVPFScenarioBus"
            (run_id, output_group_id, scenario_timestamp, topology_variant_idx, node_id, pd, qd, vm, va, bus_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, output_group_id, node_id) DO NOTHING
            """,
            [(run_id, *row) for row in bus_rows],
        )
    if branch_rows:
        cursor.executemany(
            """
            INSERT INTO "MVPFScenarioBranch"
            (run_id, output_group_id, scenario_timestamp, topology_variant_idx, connection_id,
             from_node, to_node, pf, qf, r_ohm_total, x_ohm_total, in_service, thermal_rating_a, thermal_violation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, output_group_id, connection_id) DO NOTHING
            """,
            [(run_id, *row) for row in branch_rows],
        )
    if ybus_rows:
        cursor.executemany(
            """
            INSERT INTO "MVPFScenarioYbus"
            (run_id, output_group_id, scenario_timestamp, topology_variant_idx, i_node, j_node, g, b)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, output_group_id, i_node, j_node) DO NOTHING
            """,
            [(run_id, *row) for row in ybus_rows],
        )
    conn.commit()


_RESULT_TABLES = {
    "bus": ('"MVPFScenarioBus"',
            ["output_group_id", "scenario_timestamp", "topology_variant_idx", "node_id",
             "pd", "qd", "vm", "va", "bus_type"]),
    "branch": ('"MVPFScenarioBranch"',
               ["output_group_id", "scenario_timestamp", "topology_variant_idx", "connection_id",
                "from_node", "to_node", "pf", "qf", "r_ohm_total", "x_ohm_total",
                "in_service", "thermal_rating_a", "thermal_violation"]),
    "ybus": ('"MVPFScenarioYbus"',
             ["output_group_id", "scenario_timestamp", "topology_variant_idx", "i_node", "j_node", "g", "b"]),
    "runtime": ('"MVPFScenarioRuntime"',
                ["output_group_id", "scenario_timestamp", "topology_variant_idx", "solve_time_ms", "converged"]),
}


def get_pf_datagen_results(run_id, table, cursor, limit=500, offset=0):
    """Paginated rows for one output record group. Raises on an unknown table name."""
    if table not in _RESULT_TABLES:
        raise Exception(f"Unknown table '{table}'. Expected one of {sorted(_RESULT_TABLES)}.")
    table_name, columns = _RESULT_TABLES[table]
    cols_sql = ", ".join(columns)
    cursor.execute(
        f"SELECT {cols_sql} FROM {table_name} WHERE run_id = %s "
        "ORDER BY scenario_timestamp, topology_variant_idx LIMIT %s OFFSET %s",
        (run_id, limit, offset),
    )
    rows = cursor.fetchall()
    return [dict(zip(columns, r)) for r in rows], columns


def get_pf_datagen_all_rows(run_id, table, cursor):
    """Unpaginated rows for one output record group, for CSV export."""
    if table not in _RESULT_TABLES:
        raise Exception(f"Unknown table '{table}'. Expected one of {sorted(_RESULT_TABLES)}.")
    table_name, columns = _RESULT_TABLES[table]
    cols_sql = ", ".join(columns)
    cursor.execute(
        f"SELECT {cols_sql} FROM {table_name} WHERE run_id = %s "
        "ORDER BY scenario_timestamp, topology_variant_idx",
        (run_id,),
    )
    return cursor.fetchall(), columns


def get_pf_datagen_summary(run_id, cursor):
    """Convergence and thermal-violation counts for a run, for the detail page."""
    cursor.execute(
        'SELECT COUNT(*), COUNT(*) FILTER (WHERE converged) FROM "MVPFScenarioRuntime" WHERE run_id = %s',
        (run_id,),
    )
    total, converged = cursor.fetchone()
    cursor.execute(
        'SELECT COUNT(*) FROM "MVPFScenarioBranch" WHERE run_id = %s AND thermal_violation',
        (run_id,),
    )
    violations = cursor.fetchone()[0]
    return {
        "total_output_groups": total or 0,
        "converged": converged or 0,
        "thermal_violations": violations or 0,
    }
