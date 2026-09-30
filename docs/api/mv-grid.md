# MV Grid

Endpoints for registering, validating, reading, and deleting MV (medium-voltage)
grids, and for bridging a registered LV grid to an MV connection point via a
transformer.

**Base path:** `/mv_grid`

Also serves a browser UI at `/mv_grid/ui` and `/mv_grid/ui/{mv_grid_id}`.

## Endpoints

### `POST /mv_grid/validate`

Validates an uploaded MV grid JSON file without saving it: parses it against
the `MVGrid` schema, then checks internal references (connections pointing
at nodes/cables that don't exist, connection points pointing at nodes that
don't exist or duplicated, transformers pointing at connection points that
don't exist or whose `primary_voltage_kv` doesn't match the grid's
`nominal_voltage_kv`). Like `/grid/validate`, reference errors come back as
a `200` with `valid: false`, not an HTTP error.

**Request**

| Name | Type | Description |
|---|---|---|
| `file` (multipart) | file, required | An MV grid JSON file matching the `MVGrid` schema (see below). |

Uploaded file content:

```json
{
  "mv_grid_id": "mv001",
  "name": "Feeder 12",
  "nominal_voltage_kv": 20.0,
  "region": "North",
  "nodes": [
    { "node_id": "MVN1", "coord_lat": 41.15, "coord_lon": -8.61, "node_type": "substation" }
  ],
  "cables": [
    { "cable_id": "MVCBL1", "imp_real": 0.12, "imp_imag": 0.09, "nom_curr": 400.0 }
  ],
  "connections": [
    { "connection_id": "MVC1", "from_node_id": "MVN1", "to_node_id": "MVN2", "cable_id": "MVCBL1", "length": 500.0 }
  ],
  "connection_points": [
    { "connection_point_id": "CP1", "node_id": "MVN1", "name": "Substation A" }
  ],
  "transformers": [
    {
      "transformer_id": "TR1", "connection_point_id": "CP1", "lv_grid_id": "grid001",
      "rated_power_kva": 400.0, "primary_voltage_kv": 20.0, "secondary_voltage_v": 230.0
    }
  ]
}
```

**Response** `200`

```json
{
  "valid": true,
  "mv_grid": {
    "mv_grid_id": "mv001",
    "name": "Feeder 12",
    "description": null,
    "nominal_voltage_kv": 20.0,
    "region": "North",
    "nodes": [{ "node_id": "MVN1", "coord_lat": 41.15, "coord_lon": -8.61, "node_type": "substation" }],
    "cables": [{ "cable_id": "MVCBL1", "imp_real": 0.12, "imp_imag": 0.09, "nom_curr": 400.0 }],
    "connections": [{ "connection_id": "MVC1", "from_node_id": "MVN1", "to_node_id": "MVN2", "cable_id": "MVCBL1", "length": 500.0 }],
    "connection_points": [{ "connection_point_id": "CP1", "node_id": "MVN1", "name": "Substation A" }],
    "transformers": [{ "transformer_id": "TR1", "connection_point_id": "CP1", "lv_grid_id": "grid001", "rated_power_kva": 400.0, "primary_voltage_kv": 20.0, "secondary_voltage_v": 230.0, "imp_real": null, "imp_imag": null, "name": null, "status": "active" }]
  },
  "graph": {
    "nodes": [{ "id": "MVN1", "x": -8.61, "y": 41.15, "type": "connection_point", "connection_point_id": "CP1", "connected_lv": ["grid001"] }],
    "edges": [{ "from": "MVN1", "to": "MVN2" }]
  }
}
```

**Errors**

| Status | Cause |
|---|---|
| `400` | Uploaded file is not valid JSON. |
| `422` | File content doesn't conform to the `MVGrid` schema. |

---

### `POST /mv_grid/`

Registers a new MV grid: uploads an MV grid JSON file (same shape as
`/mv_grid/validate`), validates schema and internal references, and
persists the grid, its nodes, cables, connections, connection points, and
transformers.

**Request**

| Name | Type | Description |
|---|---|---|
| `file` (multipart) | file, required | An MV grid JSON file matching the `MVGrid` schema. |

The upload is subject to the shared [200 MB upload cap](index.md#resource-safety-limits).

**Response** `200`

```json
{ "message": "MV Grid 'mv001' registered successfully." }
```

**Errors**

| Status | Cause |
|---|---|
| `413` | Uploaded file exceeds the [200 MB upload cap](index.md#resource-safety-limits). |
| `400` | Uploaded file is not valid JSON. |
| `422` | Schema validation failed, or reference validation failed (response `detail` is `{"validation_errors": [...]}`). |
| `500` | Database error while inserting the MV grid (e.g. duplicate `mv_grid_id`). |

---

### `GET /mv_grid/list`

Lists all registered MV grids with summary fields.

**Response** `200`

```json
[
  { "mv_grid_id": "mv001", "name": "Feeder 12", "nominal_voltage_kv": 20.0, "region": "North" }
]
```

**Errors**

| Status | Cause |
|---|---|
| `500` | Database error while querying. |

---

### `GET /mv_grid/data/{mv_grid_id}`

Retrieves the full MV grid: header fields plus nodes, connections,
connection points, and transformers.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `mv_grid_id` | string | Unique identifier of the MV grid. |

**Response** `200`

```json
{
  "mv_grid_id": "mv001",
  "name": "Feeder 12",
  "description": null,
  "nominal_voltage_kv": 20.0,
  "region": "North",
  "nodes": [{ "node_id": "MVN1", "coord_lat": 41.15, "coord_lon": -8.61, "node_type": "substation" }],
  "connections": [{ "connection_id": "MVC1", "from_node_id": "MVN1", "to_node_id": "MVN2", "cable_id": "MVCBL1", "length": 500.0 }],
  "connection_points": [{ "connection_point_id": "CP1", "node_id": "MVN1", "name": "Substation A" }],
  "transformers": [{ "transformer_id": "TR1", "connection_point_id": "CP1", "lv_grid_id": "grid001", "rated_power_kva": 400.0, "primary_voltage_kv": 20.0, "secondary_voltage_v": 230.0, "imp_real": null, "imp_imag": null, "name": null, "status": "active" }]
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No MV grid with this `mv_grid_id` exists. |
| `500` | Database error while querying. |

---

### `DELETE /mv_grid/{mv_grid_id}`

Deletes an MV grid and its associated nodes, cables, connections,
connection points, and transformers.

!!! warning "Destructive and irreversible"
    Note that deleting an MV grid does **not** delete any LV grid connected
    to it — per [Data Model › MV grids](../database-schema.md#mv-grids),
    `MVTransformer.lv_grid_id` is `ON DELETE SET NULL` in the other
    direction (deleting the *LV* grid unlinks the transformer), and deleting
    the MV grid itself simply removes its own rows including that
    transformer.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `mv_grid_id` | string | Unique identifier of the MV grid to delete. |

**Response** `200`

```json
{ "message": "MV Grid 'mv001' and all associated data deleted." }
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No MV grid with this `mv_grid_id` exists. |
| `500` | Database error during deletion. |

---

### `GET /mv_grid/lv-grids`

Lists the `grid_id` of every registered LV grid, for populating a
"connect an LV grid" picker.

**Response** `200`

```json
[{ "grid_id": "grid001" }, { "grid_id": "grid002" }]
```

**Errors**

| Status | Cause |
|---|---|
| `500` | Database error while querying. |

---

### `POST /mv_grid/{mv_grid_id}/connect/{connection_point_id}`

Connects an existing LV grid to an MV connection point by creating a new
`MVTransformer` row bridging the two.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `mv_grid_id` | string | The MV grid owning the connection point. |
| `connection_point_id` | string | The connection point to attach the LV grid to. |

**Request body**

```json
{
  "lv_grid_id": "grid001",
  "transformer_id": null,
  "rated_power_kva": 400.0,
  "primary_voltage_kv": 20.0,
  "secondary_voltage_v": 230.0,
  "imp_real": null,
  "imp_imag": null,
  "name": null
}
```

Only `lv_grid_id` is required. Defaults applied server-side when omitted:
`transformer_id` → a generated `TR-<8 hex chars>`, `rated_power_kva` →
`400.0`, `primary_voltage_kv` → `20.0`, `secondary_voltage_v` → `230.0`.

**Response** `200`

```json
{ "message": "LV grid 'grid001' connected to point 'CP1' via transformer 'TR-a1b2c3d4'." }
```

**Errors**

| Status | Cause |
|---|---|
| `400` | `connection_point_id` not found in this MV grid; `lv_grid_id` not found; or the LV grid is already connected to this connection point. |
| `422` | Request body doesn't conform to `ConnectLVRequest` (e.g. missing `lv_grid_id`). |

!!! note
    All failure modes from the underlying connect operation surface as
    `400`, including a not-found MV connection point or LV grid — there is
    no `404` from this endpoint.

---

### `DELETE /mv_grid/{mv_grid_id}/disconnect/{connection_point_id}/{lv_grid_id}`

Removes the transformer bridge between an MV connection point and an LV
grid.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `mv_grid_id` | string | The MV grid owning the connection point. |
| `connection_point_id` | string | The connection point the LV grid is attached to. |
| `lv_grid_id` | string | The LV grid to disconnect. |

**Response** `200`

```json
{ "message": "LV grid 'grid001' disconnected from point 'CP1'." }
```

**Errors**

| Status | Cause |
|---|---|
| `400` | No matching transformer connects this connection point and LV grid. |

---

### `GET /mv_grid/{mv_grid_id}/pv/{lv_grid_id}`

Returns aggregated active-power/voltage pairs for a connected LV grid — the
average `power_active`, `power_reactive`, and `voltage_magnitude` per
timestamp across all of the LV grid's nodes and phases. Represents a
per-meter load profile at the MV/LV boundary (not a summed total).

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `mv_grid_id` | string | The MV grid the LV grid is connected to. |
| `lv_grid_id` | string | The connected LV grid to aggregate measurements for. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `limit` | integer (1-10000) | no | `500` | Maximum number of timestamps to return. |

**Response** `200`

```json
{
  "mv_grid_id": "mv001",
  "lv_grid_id": "grid001",
  "n_nodes": 42,
  "aggregation": "avg_per_timestamp_across_all_nodes",
  "count": 500,
  "pv_pairs": [
    { "datetime": "2024-08-20 14:00:00", "avg_power_active": 3.21, "avg_power_reactive": 0.55, "avg_voltage_magnitude": 229.8 }
  ]
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | `lv_grid_id` is not connected to `mv_grid_id` (no matching `MVTransformer` row), or no measurement data exists for the LV grid. |
| `500` | Database error while querying. |

---
