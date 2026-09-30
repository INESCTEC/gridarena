# Digital Twin

Endpoints for creating, configuring, running, and monitoring **Digital
Twins** — each one binds a registered LV grid to a live external data
source and runs a periodic fetch → map → publish → consume → power-flow →
compare loop. See [Architecture › Digital Twin](../architecture.md#digital-twin)
for the subsystem design (`runner.py`/`broker.py`/`connector.py`/
`field_mapper.py`/`comparison.py`) and
[Data Model › Digital Twin](../database-schema.md#digital-twin) for the
underlying tables.

**Base path:** `/digital-twins`

Also serves a browser UI at `/digital-twins/ui` (list), `/digital-twins/ui/new`
(creation wizard), and `/digital-twins/ui/{digital_twin_id}` (detail page).

!!! note "Credentials are never stored directly"
    A twin's `source_config.secret_ref` names an **environment variable** on
    the API server that holds the actual token/API key/basic credentials —
    the secret itself is never written to the database. `connector.py`
    resolves it at request time from `os.environ`.

## Endpoints

### `POST /digital-twins/`

Creates a new digital twin bound to a grid. The twin starts in the
`created` status; it does not begin fetching data until
[`POST /digital-twins/{digital_twin_id}/start`](#post-digital-twinsdigital_twin_idstart)
is called.

**Request body**

```json
{
  "grid_id": "grid001",
  "name": "Substation A feed",
  "description": "Live feed from the utility SCADA export",
  "update_interval_seconds": 60,
  "broker_type": "redis",
  "broker_topic": null,
  "source_config": {
    "source_type": "http",
    "url": "https://scada.example.com/api/latest",
    "method": "GET",
    "headers": {},
    "query_params": {},
    "auth_type": "bearer",
    "secret_ref": "SCADA_API_TOKEN",
    "secret_header": null,
    "timeout_seconds": 30,
    "retry_count": 3
  },
  "field_mapping": {
    "timestamp": "data.timestamp",
    "measurements": "data.readings",
    "node_id": "meter_id",
    "phase": "phase",
    "active_power": "p_kw",
    "reactive_power": "q_kvar",
    "voltage_magnitude": "v_volts",
    "voltage_angle": null
  },
  "node_assignments": null,
  "powerflow_config": { "phase": "R", "voltage_ref": 230.0 }
}
```

`update_interval_seconds` must be between 5 and 86400. `broker_type` is
currently always `"redis"`. `broker_topic` defaults to
`gridarena.digital_twin.<digital_twin_id>.measurements` when omitted.
Either `field_mapping` (one shared mapping for a single combined fetch) or
`node_assignments` (one fetch + mapping per node, each with its own
`update_interval_seconds`/`timeout_seconds`) is used depending on how the
twin is wired up; both are optional at creation time.

**Response** `200`

```json
{
  "digital_twin_id": "a1b2c3d4e5f6",
  "message": "Digital twin 'a1b2c3d4e5f6' created."
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | `grid_id` doesn't reference an existing grid. |
| `422` | Request body fails schema validation. |
| `500` | Database error while creating the twin. |

---

### `GET /digital-twins/`

Lists every digital twin, most recently created first.

**Response** `200`

```json
[
  {
    "digital_twin_id": "a1b2c3d4e5f6",
    "grid_id": "grid001",
    "name": "Substation A feed",
    "description": "Live feed from the utility SCADA export",
    "status": "running",
    "update_interval_seconds": 60,
    "broker_type": "redis",
    "broker_topic": "gridarena.digital_twin.a1b2c3d4e5f6.measurements",
    "source_config": { "source_type": "http", "url": "https://scada.example.com/api/latest" },
    "field_mapping": { "timestamp": "data.timestamp", "measurements": "data.readings" },
    "node_assignments": null,
    "powerflow_config": { "phase": "R", "voltage_ref": 230.0 },
    "created_at": "2026-08-20 09:00:00",
    "updated_at": "2026-08-27 10:15:00",
    "last_run_at": "2026-08-27 10:15:00",
    "last_error": null
  }
]
```

**Errors**

| Status | Cause |
|---|---|
| `500` | Database error while listing twins. |

---

### `GET /digital-twins/diagnose/{digital_twin_id}`

Runs a diagnostic sweep over a twin's stored data (raw `field_mapping` JSON
shape, presence of a `latest_batch` column/value, result/event row counts,
grid node count) — intended for troubleshooting stored-config drift, not
for regular client use.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to diagnose. |

**Response** `200`

```json
{
  "digital_twin_id": "a1b2c3d4e5f6",
  "checks": {
    "exists": true,
    "raw_field_mapping_type": "dict",
    "raw_field_mapping_keys": ["timestamp", "measurements", "node_id"],
    "has_node_assignments_key": false,
    "node_assignments_count": null,
    "node_assignments_sample": null,
    "latest_batch_column_exists": true,
    "latest_batch_has_data": true,
    "latest_batch_keys": ["grid_id", "timestamp", "measurements"],
    "latest_batch_measurements_count": 42,
    "latest_batch_sample": { "node_id": "N1", "phase": "R", "power_active": 3.2 },
    "results_count": 118,
    "events_count": 240,
    "parsed_node_assignments_count": 0,
    "parsed_field_mapping_keys": ["timestamp", "measurements", "node_id"],
    "status": "running",
    "grid_id": "grid001",
    "grid_node_count": 25
  }
}
```

!!! note
    A digital twin ID that doesn't exist does **not** raise `404` here —
    the response comes back `200` with `"checks": {"exists": false}`.

---

### `POST /digital-twins/validate-field-mapping`

Dry-runs a field mapping against a sample payload, without creating or
modifying any twin. Used by the creation wizard to let a user iterate on
their mapping before saving it.

**Request body**

```json
{
  "grid_id": "grid001",
  "source_sample": {
    "data": { "timestamp": "2026-08-27T10:00:00", "readings": [{ "meter_id": "N1", "phase": "R", "p_kw": 3.2, "q_kvar": 0.4, "v_volts": 229.8 }] }
  },
  "field_mapping": {
    "timestamp": "data.timestamp",
    "measurements": "data.readings",
    "node_id": "meter_id",
    "phase": "phase",
    "active_power": "p_kw",
    "reactive_power": "q_kvar",
    "voltage_magnitude": "v_volts",
    "voltage_angle": null
  }
}
```

**Response** `200`

```json
{
  "success": true,
  "mapped_payload": {
    "grid_id": "grid001",
    "timestamp": "2026-08-27T10:00:00",
    "measurements": [
      { "node_id": "N1", "phase": "R", "datetime": "2026-08-27T10:00:00", "power_active": 3.2, "power_reactive": 0.4, "voltage_magnitude": 229.8, "voltage_angle": 0.0 }
    ]
  },
  "errors": [],
  "warnings": [],
  "missing_fields": [],
  "invalid_nodes": [],
  "invalid_phases": [],
  "type_errors": [],
  "duplicate_measurements": []
}
```

!!! note "Unknown grid is a `success: false` result, not a `404`"
    Passing a `grid_id` that doesn't exist returns `200` with
    `{"success": false, "errors": ["Grid '<grid_id>' not found."]}` rather
    than an HTTP error, so the wizard can render the failure inline.

---

### `GET /digital-twins/grid-graph/{grid_id}`

Returns a grid's nodes, connections, and a NetworkX-derived 2D layout, for
the twin-creation wizard to plot as an interactive graph while the user
builds a field mapping / node assignment list.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `grid_id` | string | The grid to load. |

**Response** `200`

```json
{
  "grid_id": "grid001",
  "nodes": [
    { "node_id": "PT", "coord_lat": 41.15, "coord_lon": -8.61 },
    { "node_id": "N1", "coord_lat": 41.151, "coord_lon": -8.611 }
  ],
  "connections": [
    { "connection_id": "C1", "from_node_id": "PT", "to_node_id": "N1", "cable_id": "CBL1", "length": 120.0 }
  ],
  "graph": {
    "nodes": [
      { "id": "PT", "x": -8.61, "y": 41.15, "type": "pt" },
      { "id": "N1", "x": -8.611, "y": 41.151, "type": "normal" }
    ],
    "edges": [{ "source": "PT", "target": "N1" }]
  }
}
```

!!! note
    If every node has lat/lon coordinates, `graph.nodes` positions come
    directly from them (`x`/`y` = lon/lat); otherwise positions are computed
    with `networkx.spring_layout(seed=42)`, a deterministic force-directed
    layout.

**Errors**

| Status | Cause |
|---|---|
| `404` | `grid_id` doesn't reference an existing grid. |

---

### `GET /digital-twins/{digital_twin_id}`

Returns a single digital twin's full configuration and status.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to fetch. |

**Response** `200`

Same shape as one entry of [`GET /digital-twins/`](#get-digital-twins).

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |

---

### `PATCH /digital-twins/{digital_twin_id}`

Partially updates a digital twin's configuration. Only fields present in
the request body are changed; `source_config`, `field_mapping`, and
`powerflow_config`, when present, replace the stored value wholesale
(they are not merged field-by-field).

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to update. |

**Request body**

```json
{
  "name": "Substation A feed (renamed)",
  "update_interval_seconds": 120
}
```

All fields (`name`, `description`, `update_interval_seconds`,
`source_config`, `field_mapping`, `powerflow_config`) are optional.

**Response** `200`

```json
{ "message": "Digital twin updated." }
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |
| `400` | The twin's `status` is `running` — stop it before updating. |
| `500` | Database error while updating. |

---

### `DELETE /digital-twins/{digital_twin_id}`

Deletes a digital twin. If it's currently running, it's stopped first; its
Redis stream is deleted on a best-effort basis afterward (failures there
are swallowed, not surfaced to the caller).

!!! warning "Destructive and irreversible"
    Cascades to the twin's `DigitalTwinEvent` and `DigitalTwinResult` rows
    (see [Data Model › Digital Twin](../database-schema.md#digital-twin)).

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to delete. |

**Response** `200`

```json
{ "message": "Digital twin 'a1b2c3d4e5f6' deleted." }
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |
| `500` | Database error while deleting. |

---

### `POST /digital-twins/{digital_twin_id}/start`

Starts the twin's periodic background loop (an `asyncio` task, not a
separate process) at its configured `update_interval_seconds`.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to start. |

**Response** `200`

```json
{ "message": "Digital twin 'a1b2c3d4e5f6' started." }
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |
| `400` | The twin is already `running`. |

---

### `POST /digital-twins/{digital_twin_id}/stop`

Cancels the twin's background loop task, if any.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to stop. |

**Response** `200`

```json
{ "message": "Digital twin 'a1b2c3d4e5f6' stopped." }
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |

---

### `POST /digital-twins/{digital_twin_id}/clone-offline`

Clones a digital twin's grid snapshot (nodes, connections, cables) and
converged result history into a new, independent
[Offline Scenario](offline-scenarios.md) for what-if analysis (connection
edits, power-limit caps, replayed power flow) without touching the live
twin.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to clone from. |

**Request body** (optional)

```json
{ "name": "What-if: N1 outage", "description": "" }
```

`name` defaults to `"Scenario from <twin name or ID>"` when omitted; the
body itself may be omitted entirely.

**Response** `200`

```json
{
  "scenario_id": "f0e1d2c3b4a5",
  "message": "Offline scenario 'f0e1d2c3b4a5' cloned from digital twin 'a1b2c3d4e5f6' with 118 timestamps."
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |
| `500` | Failed to gather grid/result data to clone, or a database error while saving the new scenario. |

---

### `POST /digital-twins/{digital_twin_id}/tick`

Runs one iteration of the fetch → map → publish → power-flow → compare
loop synchronously and returns the resulting comparison metrics. Useful
for testing a twin's configuration without waiting for its next scheduled
tick (or without starting it at all).

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to tick. |

**Response** `200`

```json
{
  "message": "Tick completed.",
  "metrics": {
    "timestamp": "2026-08-27T10:15:00",
    "measurements_count": 24,
    "missing_measurements": 0,
    "invalid_measurements": 0,
    "convergence_status": "converged",
    "voltage_mae": 0.82,
    "voltage_rmse": 1.10,
    "max_voltage_error": 2.4,
    "active_power_error": 0.05,
    "reactive_power_error": 0.02,
    "execution_time_ms": 14.3,
    "powerflow_algorithm": "backward_forward_sweep"
  }
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |
| `500` | The tick failed (source fetch error, mapping failure, power-flow error, etc. — the response `detail` is generic; specifics are logged server-side). |

---

### `POST /digital-twins/{digital_twin_id}/test-source`

Calls the twin's configured `source_config` exactly as the runner would,
and returns the raw response — without mapping or publishing it. Used by
the UI to let a user verify connectivity/auth before saving a twin.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin whose source to test. |

**Response** `200`

```json
{
  "success": true,
  "status_code": 200,
  "raw_payload": { "data": { "timestamp": "2026-08-27T10:00:00", "readings": [] } },
  "error": null
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |

---

### `POST /digital-twins/{digital_twin_id}/probe`

Like `test-source`, but lets the caller merge in extra query parameters
for a one-off exploratory call (e.g. trying a different node/date filter),
and forces `retry_count=1` so a bad probe doesn't retry repeatedly.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to probe. |

**Request body** (optional)

```json
{ "query_params": { "meter_id": "N1" } }
```

**Response** `200`

```json
{
  "success": true,
  "status_code": 200,
  "url": "https://scada.example.com/api/latest",
  "query_params": { "meter_id": "N1" },
  "raw_payload": { "data": { "timestamp": "2026-08-27T10:00:00" } },
  "error": null
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |

---

### `POST /digital-twins/{digital_twin_id}/publish-sample`

Fetches one sample from the twin's source, maps it through its
`field_mapping`, and — if the mapping succeeds — stores it as the twin's
`latest_batch` and (if Redis is reachable) publishes it to the twin's
broker topic. Unlike `/tick`, this does **not** run a power flow or
persist a `DigitalTwinResult`.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to publish a sample for. |

**Response** `200`

```json
{
  "message": "Sample published.",
  "broker_message_id": "1735300000000-0",
  "measurements_count": 24,
  "mapping_warnings": [],
  "mapping_errors": []
}
```

If Redis isn't reachable, `broker_message_id` is `null` and `message` is
`"Sample mapped and stored successfully."` instead.

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |
| `502` | The source fetch itself failed (`detail` includes the connector's error message). |
| `422` | The fetched payload failed field mapping (`detail` is `{"mapping_errors": [...]}`). |

---

### `GET /digital-twins/{digital_twin_id}/latest-state`

Returns a twin's current status alongside its most recently stored
measurement batch and most recent comparison result, in one call — used
by the detail page's live-status panel.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to fetch state for. |

**Response** `200`

```json
{
  "digital_twin_id": "a1b2c3d4e5f6",
  "grid_id": "grid001",
  "status": "running",
  "last_run_at": "2026-08-27 10:15:00",
  "latest_measurements": {
    "grid_id": "grid001",
    "timestamp": "2026-08-27T10:15:00",
    "measurements": [{ "node_id": "N1", "phase": "R", "datetime": "2026-08-27T10:15:00", "power_active": 3.2, "power_reactive": 0.4, "voltage_magnitude": 229.8, "voltage_angle": 0.0 }]
  },
  "latest_result": {
    "result_id": 118,
    "digital_twin_id": "a1b2c3d4e5f6",
    "timestamp": "2026-08-27T10:15:00",
    "convergence_status": "converged",
    "voltage_mae": 0.82
  }
}
```

`latest_measurements` and `latest_result` are `null` if the twin hasn't
run yet, or if the stored batch failed to parse.

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |

---

### `GET /digital-twins/{digital_twin_id}/node-history/{node_id}`

Extracts one node's simulated-vs-observed voltage and power time series
across the twin's stored comparison results, for charting.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to read from. |
| `node_id` | string | The grid node to extract history for. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `limit` | integer | no | `500` | Max number of underlying results to scan (1-5000), oldest-first after reversal. |

**Response** `200`

```json
{
  "node_id": "N1",
  "digital_twin_id": "a1b2c3d4e5f6",
  "points": [
    {
      "timestamp": "2026-08-27T10:15:00",
      "simulated_voltage": 229.6,
      "true_voltage": 229.8,
      "power_active": 3.2,
      "power_reactive": 0.4
    }
  ]
}
```

Only results with `convergence_status == "converged"` and a `details`
entry for `node_id` contribute a point; others are silently skipped.

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |

---

### `GET /digital-twins/{digital_twin_id}/results`

Lists a twin's raw comparison results (`DigitalTwinResult` rows), newest
first.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to fetch results for. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `limit` | integer | no | `50` | Max rows to return (1-1000). |

**Response** `200`

```json
[
  {
    "result_id": 118,
    "digital_twin_id": "a1b2c3d4e5f6",
    "timestamp": "2026-08-27T10:15:00",
    "measurements_count": 24,
    "missing_measurements": 0,
    "invalid_measurements": 0,
    "convergence_status": "converged",
    "voltage_mae": 0.82,
    "voltage_rmse": 1.10,
    "max_voltage_error": 2.4,
    "active_power_error": 0.05,
    "reactive_power_error": 0.02,
    "execution_time_ms": 14.3,
    "powerflow_algorithm": "backward_forward_sweep",
    "details": null,
    "created_at": "2026-08-27 10:15:01"
  }
]
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |

---

### `GET /digital-twins/{digital_twin_id}/metrics`

Returns aggregate accuracy metrics computed over a twin's recent results,
plus the raw results they were computed from.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to summarize. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `limit` | integer | no | `100` | Max underlying results to aggregate over (1-1000). |

**Response** `200`

```json
{
  "total_runs": 100,
  "converged_runs": 96,
  "avg_voltage_mae": 0.79,
  "avg_voltage_rmse": 1.05,
  "latest_result": { "result_id": 118, "convergence_status": "converged", "voltage_mae": 0.82 },
  "results": []
}
```

If the twin has no results yet, the response is
`{"total_runs": 0, "results": []}` (no `converged_runs`/`avg_*` keys).

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |

---

### `GET /digital-twins/{digital_twin_id}/events`

Lists a twin's append-only event log (created/started/stopped/published/
tick-completed/error events), newest first.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `digital_twin_id` | string | The digital twin to fetch events for. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `limit` | integer | no | `50` | Max rows to return (1-500). |

**Response** `200`

```json
[
  {
    "event_id": 240,
    "digital_twin_id": "a1b2c3d4e5f6",
    "event_type": "tick_completed",
    "message": "PF converged, MAE=0.82",
    "details": { "convergence": "converged", "voltage_mae": 0.82 },
    "created_at": "2026-08-27 10:15:01"
  }
]
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No digital twin with this ID exists. |
