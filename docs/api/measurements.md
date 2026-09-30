# Measurements

Endpoints for uploading, reading, and deleting node/grid-scoped
measurements — timestamped power/voltage readings tied to a specific
`(node_id, grid_id)`, optionally per-phase. This is distinct from the
[Historical](historical.md) router's standalone series, which aren't tied to
any grid or node — see
[Data Model › Measurements and historical data](../database-schema.md#measurements-and-historical-data).

**Base path:** `/measurements`

Also serves a browser UI at `/measurements/ui` and `/measurements/ui/{grid_id}`.

## Endpoints

### `POST /measurements/`

Uploads and inserts measurement data for a grid's nodes from a JSON file.
Each `(node_id, grid_id, datetime, phase)` combination is upserted — a
repeat upload for the same key overwrites the stored power/voltage values
rather than erroring or duplicating the row.

**Request**

| Name | Type | Description |
|---|---|---|
| `file` (multipart) | file, required | A JSON file matching the `MeasurementsData` schema (see below). |

Uploaded file content:

```json
{
  "grid_id": "grid001",
  "historical": [
    {
      "node_id": "N1",
      "measurements": [
        {
          "datetime": "2024-08-20T14:00:00",
          "phase": "R",
          "power_active": 3.2,
          "power_reactive": 0.6,
          "voltage_magnitude": 229.5,
          "voltage_angle": -0.4
        }
      ]
    }
  ]
}
```

`phase` is optional per reading (`"R"`, `"S"`, `"T"`, or omitted/`null` for
an aggregated row); `power_active`, `power_reactive`, `voltage_magnitude`,
and `voltage_angle` are required. The upload is subject to the shared
[200 MB upload cap](index.md#resource-safety-limits).

**Response** `200`

```json
{ "message": "Measurement data for grid 'grid001' inserted successfully." }
```

**Errors**

| Status | Cause |
|---|---|
| `413` | Uploaded file exceeds the [200 MB upload cap](index.md#resource-safety-limits). |
| `400` | Uploaded file is not valid JSON. |
| `422` | File content doesn't conform to the `MeasurementsData` schema. |
| `500` | Database error during insertion. |

---

### `DELETE /measurements/{grid_id}`

Deletes measurement records for a grid, optionally narrowed by node, phase,
and/or datetime range.

!!! warning "Destructive"
    With no filters supplied, this deletes **every** measurement row for the
    grid.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `grid_id` | string | The grid whose measurements to delete. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `start` | string (ISO datetime) | no | — | Delete only records at or after this datetime (inclusive). |
| `end` | string (ISO datetime) | no | — | Delete only records before this datetime (exclusive). |
| `node_id` | string | no | — | Restrict deletion to one node. |
| `phase` | `"R"` \| `"S"` \| `"T"` | no | — | Restrict deletion to one phase; omit to delete both aggregated and all-phase rows. |

**Response** `200`

```json
{ "message": "42 measurement(s) deleted for grid 'grid001'." }
```

**Errors**

| Status | Cause |
|---|---|
| `400` | `start` or `end` is not a valid ISO datetime. |
| `500` | Database error during deletion. |

---

### `GET /measurements/data/{grid_id}`

Retrieves measurement records for a grid, optionally filtered by node,
datetime range, and phase.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `grid_id` | string | The grid to retrieve measurements for. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `node_id` | string | no | — | Filter to one node. |
| `start` | string (ISO datetime) | no | — | Lower bound (inclusive). |
| `end` | string (ISO datetime) | no | — | Upper bound (exclusive). |
| `per_phase` | boolean | no | `true` | If `true`, returns rows with `phase` in `{R, S, T}`; if `false`, returns aggregated rows (`phase IS NULL`). |
| `phase` | `"R"` \| `"S"` \| `"T"` | no | — | When `per_phase=true`, filter to a single phase. Requires `per_phase=true` — combining it with `per_phase=false` is a `400`. |

**Response** `200`

```json
{
  "grid_id": "grid001",
  "node_id": null,
  "per_phase": true,
  "phase": null,
  "datetime_range": { "start": null, "end": null },
  "records": [
    {
      "node_id": "N1",
      "datetime": "2024-08-20T14:00:00",
      "phase": "R",
      "power_active": 3.2,
      "power_reactive": 0.6,
      "voltage_magnitude": 229.5,
      "voltage_angle": -0.4
    }
  ],
  "count": 1,
  "truncated": false
}
```

Results are capped at 50,000 rows — see the shared
[resource limits](index.md#resource-safety-limits). When the cap is hit,
`truncated` is `true` and a `truncation_hint` field is added:

```json
{ "truncation_hint": "Result capped at 50000 records; narrow with start/end." }
```

**Errors**

| Status | Cause |
|---|---|
| `400` | Invalid `start`/`end` datetime format, or `phase` given with `per_phase=false`. |
| `404` | No measurements match the given filters. |
| `500` | Database error while querying. |

---
