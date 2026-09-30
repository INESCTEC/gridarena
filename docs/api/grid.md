# Grid

Endpoints for registering, validating, reading, and deleting LV (low-voltage)
grids — a grid's nodes, cables, and connections, plus the per-benchmark
train/test usage flags recorded at registration time.

**Base path:** `/grid`

Also serves a browser UI at `/grid/ui` and `/grid/ui/{grid_id}`.

## Endpoints

### `POST /grid/validate`

Validates an uploaded grid JSON file without saving it: parses it against the
`Grid` schema, then checks internal references (duplicate IDs, connections
pointing at nodes/cables that don't exist). Returns the parsed grid and a
computed graph layout either way — the caller distinguishes success from
failure via the `valid` flag rather than an HTTP error, except for malformed
JSON or a schema mismatch.

**Request**

| Name | Type | Description |
|---|---|---|
| `file` (multipart) | file, required | A grid JSON file matching the `Grid` schema (see below). |

Uploaded file content:

```json
{
  "grid_id": "grid001",
  "nodes": [
    { "node_id": "PT", "coord_lat": 41.15, "coord_lon": -8.61, "coord_error": 0 },
    { "node_id": "N1", "coord_lat": 41.151, "coord_lon": -8.611 }
  ],
  "connections": [
    { "connection_id": "C1", "from_node_id": "PT", "to_node_id": "N1", "length": 120.0, "cable_id": "CBL1" }
  ],
  "cables": [
    {
      "cable_id": "CBL1",
      "r_imp_real": 0.32, "r_imp_imag": 0.08,
      "s_imp_real": 0.32, "s_imp_imag": 0.08,
      "t_imp_real": 0.32, "t_imp_imag": 0.08,
      "r_nom_curr": 200.0, "s_nom_curr": 200.0, "t_nom_curr": 200.0
    }
  ]
}
```

!!! note "Validation errors are not HTTP errors"
    Reference errors (e.g. a connection's `from_node_id` not present in
    `nodes`, duplicate `node_id`/`cable_id`/`connection_id`) are returned as
    `{"valid": false, "errors": [...]}` with a `200` status, not a `4xx`.
    Only invalid JSON or a schema-level mismatch (missing required field,
    wrong type) raises an HTTP error.

**Response** `200`

```json
{
  "valid": true,
  "grid": {
    "grid_id": "grid001",
    "nodes": [{ "node_id": "PT", "coord_lat": 41.15, "coord_lon": -8.61, "coord_error": 0 }],
    "connections": [{ "connection_id": "C1", "from_node_id": "PT", "to_node_id": "N1", "length": 120.0, "cable_id": "CBL1" }],
    "cables": [{ "cable_id": "CBL1", "r_imp_real": 0.32, "r_imp_imag": 0.08, "s_imp_real": 0.32, "s_imp_imag": 0.08, "t_imp_real": 0.32, "t_imp_imag": 0.08, "r_nom_curr": 200.0, "s_nom_curr": 200.0, "t_nom_curr": 200.0 }]
  },
  "graph": {
    "nodes": [{ "id": "PT", "x": -8.61, "y": 41.15, "type": "pt" }, { "id": "N1", "x": -8.611, "y": 41.151, "type": "normal" }],
    "edges": [{ "from": "PT", "to": "N1" }]
  }
}
```

Or, when reference validation fails:

```json
{
  "valid": false,
  "errors": ["Connection 'C1': from_node_id 'PT' not found in nodes."]
}
```

**Errors**

| Status | Cause |
|---|---|
| `400` | Uploaded file is not valid JSON. |
| `422` | File content doesn't conform to the `Grid` schema (e.g. missing `grid_id`, malformed node). |

---

### `POST /grid/`

Registers a new grid: uploads a grid JSON file together with eight
`YES`/`NO` usage flags (one train + one test flag per benchmark), validates
both the schema and internal references, and persists the grid, its nodes,
cables, connections, and `GridUsage` row.

**Request**

| Name | Type | Description |
|---|---|---|
| `file` (multipart) | file, optional | A grid JSON file matching the `Grid` schema (same shape as `/grid/validate`). Registration fails with `400` if omitted. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `phase_detection_test` | `"YES"` \| `"NO"` | yes | — | Include this grid in the Phase Identification benchmark's test set. |
| `phase_detection_train` | `"YES"` \| `"NO"` | yes | — | Include this grid in the Phase Identification benchmark's train set. |
| `topology_detection_test` | `"YES"` \| `"NO"` | yes | — | Include this grid in the Topology Discovery benchmark's test set. |
| `topology_detection_train` | `"YES"` \| `"NO"` | yes | — | Include this grid in the Topology Discovery benchmark's train set. |
| `voltage_control_test` | `"YES"` \| `"NO"` | yes | — | Include this grid in the Voltage Control benchmark's test set. |
| `voltage_control_train` | `"YES"` \| `"NO"` | yes | — | Include this grid in the Voltage Control benchmark's train set. |
| `state_estimation_test` | `"YES"` \| `"NO"` | yes | — | Include this grid in the State Estimation benchmark's test set. |
| `state_estimation_train` | `"YES"` \| `"NO"` | yes | — | Include this grid in the State Estimation benchmark's train set. |

The upload is subject to the shared [200 MB upload cap](index.md#resource-safety-limits).

**Response** `200`

```json
{ "message": "Grid 'grid001' registered successfully." }
```

**Errors**

| Status | Cause |
|---|---|
| `400` | No file was attached. |
| `413` | Uploaded file exceeds the [200 MB upload cap](index.md#resource-safety-limits). |
| `400` | Uploaded file is not valid JSON. |
| `422` | Reference validation failed (duplicate IDs, dangling `from_node_id`/`to_node_id`/`cable_id`) — response `detail` is `{"validation_errors": [...]}`. |
| `500` | Database error while inserting the grid (e.g. duplicate `grid_id`). |

---

### `DELETE /grid/{grid_id}`

Deletes a grid and, via `ON DELETE CASCADE`, every dependent row (`Node`,
`Cable`, `Connection`, `GridUsage`, measurements, power-flow results, and
benchmark data tied to it) — see
[Data Model › Grid topology](../database-schema.md#grid-topology).

!!! warning "Destructive and irreversible"
    This permanently removes the grid and all data derived from it across
    every router (measurements, power flow results, benchmark guesses).

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `grid_id` | string | Unique identifier of the grid to delete. |

**Response** `200`

```json
{ "message": "Grid 'grid001' and all associated data were deleted successfully." }
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No grid with this `grid_id` exists. |
| `500` | Database error during deletion. |

---

### `GET /grid/data/{grid_id}`

Retrieves all rows from one of a grid's tables (`Node`, `Cable`,
`Connection`, or `grids` itself).

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `grid_id` | string | Unique identifier of the grid whose data is being queried. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `table` | `"Node"` \| `"Cable"` \| `"Connection"` \| `"grids"` | yes | — | Which table to query. |

**Response** `200`

```json
{
  "table": "Node",
  "grid_id": "grid001",
  "records": [
    { "NodeId": "PT", "CoordLat": 41.15, "CoordLon": -8.61, "CoordError": 0, "grid_id": "grid001" }
  ]
}
```

!!! note
    `records` reflects the raw table column names (e.g. `NodeId`,
    `CoordLat`), not the `snake_case` names used in the `Grid` schema/request
    body — this endpoint does a plain `SELECT *` and returns it as-is.

**Errors**

| Status | Cause |
|---|---|
| `404` | No rows found in the requested table for this `grid_id`. |
| `500` | Database error while querying. |

---
