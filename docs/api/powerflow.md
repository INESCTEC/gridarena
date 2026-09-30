# Power Flow

Endpoints to run gridarena's backward/forward-sweep power flow solver
(`gridarena/powerflow/powerflow_algorithm.py`) against a registered grid's
stored measurements, and to read back the persisted results. See
[Architecture](../architecture.md) for how this fits alongside the other
routers.

**Base path:** `/powerflow`

Also serves a browser UI at `/powerflow/ui` and `/powerflow/ui/{grid_id}`.

## Endpoints

### `POST /powerflow/{grid_id}/run`

Runs the power flow algorithm once per distinct measurement timestamp found
for the grid and phase (optionally narrowed to a time range), writing a
voltage result per node/phase/timestamp to `PowerFlowResults` — upserting on
`(grid_id, node_id, phase, datetime)`, so re-running overwrites prior
results rather than duplicating them.

For each timestamp, the solver needs: the grid's nodes (from `Node`), its
connections and their cable impedances (from `Connection`/`Cable`), the
complex power injection at each node for that timestamp/phase (from
`Measurements`), and a reference voltage at node `"PT"` for that
timestamp/phase (also from `Measurements`).

!!! warning "Synchronous and potentially slow"
    The solver runs once per matching timestamp, sequentially, inside the
    request — a large date range can mean a long-running request.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `grid_id` | string | The grid to run power flow for. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `phase` | `"R"` \| `"S"` \| `"T"` | yes | — | The phase to run power flow for. |
| `start_time` | string (ISO datetime) | no | — | Lower bound on measurement timestamps to include (inclusive). |
| `end_time` | string (ISO datetime) | no | — | Upper bound on measurement timestamps to include (inclusive). |

**Response** `200`

```json
{ "message": "Power flow has been run successfully." }
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No measurement timestamps found for `grid_id`/`phase` (and range, if given). |
| `500` | Any other failure — including the grid having no nodes, no connections, no cable data for a used `cable_id`, a connection with zero total impedance, or no `voltage_magnitude`/`voltage_angle` recorded for node `"PT"` at some timestamp. These all originate as plain `Exception`s from the power-flow data-loading helpers and are not distinguished from a database error; `detail` is `"Error: {message}"`. |

---

### `GET /powerflow/data/{grid_id}/results`

Retrieves previously computed power flow results for a grid and phase.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `grid_id` | string | The grid to retrieve results for. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `phase` | `"R"` \| `"S"` \| `"T"` | yes | — | The phase to retrieve results for. |

**Response** `200`

```json
{
  "grid_id": "grid001",
  "phase": "R",
  "results": [
    {
      "timestamp": "2024-08-20T14:00:00",
      "node_id": "N1",
      "voltage": { "real": 229.4, "imag": -1.2 }
    }
  ]
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No power flow results stored for `grid_id`/`phase`. |
| `500` | Database error while querying. |

---
