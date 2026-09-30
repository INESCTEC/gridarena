# Offline Scenarios

Endpoints for managing **Offline Scenarios** — replay-based (non-live)
what-if variants of a digital twin's grid, where a user can add/remove/
modify connections, cap node power limits, and re-run power flow over the
twin's historical result timestamps without touching the live twin. See
[Architecture › Digital Twin](../architecture.md#digital-twin) and
[Data Model › Offline Scenarios](../database-schema.md#offline-scenarios).

**Base path:** `/offline-scenarios`

Also serves a browser UI at `/offline-scenarios/ui` and
`/offline-scenarios/ui/{scenario_id}`.

!!! note "Scenarios are created from a digital twin, not from this router"
    There is no `POST /offline-scenarios/` — a scenario is always created
    by cloning an existing digital twin via
    [`POST /digital-twins/{digital_twin_id}/clone-offline`](digital-twin.md#post-digital-twinsdigital_twin_idclone-offline),
    which copies that twin's current grid snapshot and converged result
    history into a new, independent scenario.

!!! warning "Some `500` responses on this router include raw exception text"
    Unlike most routers, `DELETE /{scenario_id}`,
    `POST /{scenario_id}/changes/connections`, and
    `POST /{scenario_id}/changes/power-limits` catch unexpected exceptions
    with `HTTPException(status_code=500, detail=str(e))` — the response
    `detail` is the exception's own message rather than the generic
    message [described on the overview page](index.md#error-format).

## Endpoints

### `GET /offline-scenarios/`

Lists offline scenarios, most recently created first.

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `source_dt_id` | string | no | — | If given, only scenarios cloned from this digital twin. |

**Response** `200`

```json
[
  {
    "scenario_id": "f0e1d2c3b4a5",
    "source_dt_id": "a1b2c3d4e5f6",
    "grid_id": "grid001",
    "name": "What-if: N1 outage",
    "description": "",
    "grid_snapshot": { "nodes": [], "connections": [], "cables": [] },
    "connection_changes": [],
    "power_limits": {},
    "powerflow_config": { "phase": "R", "voltage_ref": 230.0 },
    "simulation_status": "pending",
    "total_timestamps": 118,
    "completed_timestamps": 0,
    "failed_timestamps": 0,
    "created_at": "2026-08-27 09:00:00",
    "updated_at": "2026-08-27 09:00:00",
    "completed_at": null,
    "error": null
  }
]
```

`simulation_status` is one of `pending`, `running`, `completed`, `failed`,
`partially_completed`.

---

### `GET /offline-scenarios/{scenario_id}`

Returns one scenario's full configuration and status.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `scenario_id` | string | The scenario to fetch. |

**Response** `200`

Same shape as one entry of [`GET /offline-scenarios/`](#get-offline-scenarios).

**Errors**

| Status | Cause |
|---|---|
| `404` | No scenario with this ID exists. |

---

### `DELETE /offline-scenarios/{scenario_id}`

Deletes a scenario and, via `ON DELETE CASCADE`, its stored
`OfflineScenarioResult` rows.

!!! warning "Destructive and irreversible"
    This permanently removes the scenario and every simulated timestamp
    computed for it. The source digital twin is unaffected.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `scenario_id` | string | The scenario to delete. |

**Response** `200`

```json
{ "message": "Scenario 'f0e1d2c3b4a5' deleted." }
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No scenario with this ID exists. |
| `500` | Database error while deleting (`detail` is the raw exception message). |

---

### `POST /offline-scenarios/{scenario_id}/changes/connections`

Applies a batch of connection edits (add/remove/disable/enable/update) to
the scenario's cloned grid snapshot. Every change is validated against
the snapshot's own nodes/cables/connections before any are applied.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `scenario_id` | string | The scenario to modify. |

**Request body**

```json
[
  { "action": "remove", "connection_id": "C1" },
  { "action": "add", "connection_id": "C_new", "from_node_id": "N1", "to_node_id": "N2", "cable_id": "CBL1", "length": 80.0 }
]
```

`action` is one of `add`, `remove`, `disable`, `enable`, `update`. For
`add`, `from_node_id`/`to_node_id` must reference existing nodes and
`cable_id` (if given) an existing cable. For the other actions,
`connection_id` must reference an existing connection.

**Response** `200`

```json
{ "message": "2 connection change(s) applied." }
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No scenario with this ID exists. |
| `400` | The scenario's `simulation_status` is `running`. |
| `422` | One or more changes failed validation — `detail` is `{"validation_errors": [...]}`. |
| `500` | Database error while saving (`detail` is the raw exception message). |

---

### `POST /offline-scenarios/{scenario_id}/changes/power-limits`

Sets per-node active power caps for the scenario. Nodes not included in
`power_limits` remain uncapped.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `scenario_id` | string | The scenario to modify. |

**Request body**

```json
{ "power_limits": { "N1": 5.0, "N2": 3.5 } }
```

Values are max power in kW; each must be a non-negative number and each
key must reference a node in the scenario's grid snapshot.

**Response** `200`

```json
{ "message": "Power limits set for 2 node(s)." }
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No scenario with this ID exists. |
| `400` | The scenario's `simulation_status` is `running`. |
| `422` | A node isn't in the grid, or a limit is negative/non-numeric — `detail` is `{"validation_errors": [...]}`. |
| `500` | Database error while saving (`detail` is the raw exception message). |

---

### `POST /offline-scenarios/{scenario_id}/run-powerflow-timeseries`

Starts (asynchronously, via `scenario_runner`) a power-flow simulation
over every timestamp in the scenario, using its current connection
changes and power limits.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `scenario_id` | string | The scenario to simulate. |

**Response** `200`

```json
{ "message": "Simulation started for scenario 'f0e1d2c3b4a5'.", "status": "running" }
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No scenario with this ID exists. |
| `400` | A simulation is already `running` for this scenario. |

---

### `GET /offline-scenarios/{scenario_id}/results`

Lists a scenario's per-timestamp simulation results, oldest first.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `scenario_id` | string | The scenario to fetch results for. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `limit` | integer | no | `500` | Max rows to return (1-5000). |

**Response** `200`

```json
[
  {
    "result_id": 501,
    "scenario_id": "f0e1d2c3b4a5",
    "timestamp": "2026-08-27T09:15:00",
    "convergence_status": "converged",
    "node_voltages": {
      "N1": { "simulated_voltage": 229.6, "power_active": 3.1, "power_reactive": 0.4 }
    },
    "execution_time_ms": 9.8,
    "error": null
  }
]
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No scenario with this ID exists. |

---

### `GET /offline-scenarios/{scenario_id}/voltage-timeseries`

Extracts the converged voltage/power time series from a scenario's
results, either for one node or for every node grouped per timestamp.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `scenario_id` | string | The scenario to read from. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `node_id` | string | no | — | If given, return only this node's series (fields inlined per timestamp). Otherwise return every node, grouped under `"nodes"` per timestamp. |

**Response** `200`

With `node_id`:

```json
[
  { "timestamp": "2026-08-27T09:15:00", "simulated_voltage": 229.6, "power_active": 3.1, "power_reactive": 0.4 }
]
```

Without `node_id`:

```json
[
  {
    "timestamp": "2026-08-27T09:15:00",
    "nodes": {
      "N1": { "simulated_voltage": 229.6, "power_active": 3.1, "power_reactive": 0.4 }
    }
  }
]
```

Only results with `convergence_status == "converged"` and non-empty
`node_voltages` contribute an entry.

**Errors**

| Status | Cause |
|---|---|
| `404` | No scenario with this ID exists. |

---

### `GET /offline-scenarios/{scenario_id}/violations`

Scans a scenario's converged results for per-node voltage deviations
beyond +/-10% of the scenario's configured `voltage_ref`.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `scenario_id` | string | The scenario to check. |

**Response** `200`

```json
[
  {
    "timestamp": "2026-08-27T09:15:00",
    "node_id": "N1",
    "simulated_voltage": 256.2,
    "deviation_pct": 11.4,
    "type": "overvoltage"
  }
]
```

`type` is `"overvoltage"` or `"undervoltage"`. `voltage_ref` used for the
comparison comes from the scenario's own `powerflow_config.voltage_ref`
(defaulting to `230.0` if unset), not a query parameter.

**Errors**

| Status | Cause |
|---|---|
| `404` | No scenario with this ID exists. |
