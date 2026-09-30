# Topology Discovery Benchmark

This benchmark tests a participant's ability to infer a grid's electrical
topology (its edge list) from historical per-node power and voltage
measurements. The workflow is: download measurement data for test grids via
`GET /topology-data` (grid identity anonymised, topology withheld), submit a
guessed edge list via `POST /submit-results`, then check accuracy via
`GET /score`. `GET /training-topology-data` exposes the same kind of data for
training grids, with the real topology included.

**Base path:** `/topology_discovery_benchmark`

Also serves a browser UI at `/topology_discovery_benchmark/ui`.

## Endpoints

### `GET /topology_discovery_benchmark/training-topology-data`

Returns historical measurements plus the real topology for every grid marked
`GridUsage.topology_detection_train = 1`, keyed by real `grid_id`. Each
node's index in `"topology (index)"` and `"conn_data"` refers to its position
in `"node to corresponding index"` for that grid; node `PT` (the
transformer/root node), if present, is always index `0`.

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `difficulty` | string | no | `clean` | One of `clean`, `easy`, `medium`, `hard` — see [difficulty/noise profiles](index.md#difficulty-and-noise-profiles). |

**Response** `200`

```json
{
  "difficulty": "clean",
  "profile": {
    "pq_rel_sigma": 0.0,
    "v_mag_rel_sigma": 0.0,
    "v_ang_rel_sigma": 0.0,
    "outlier_prob": 0.0,
    "outlier_scale": 0.0
  },
  "grids": {
    "grid001": {
      "N1": [
        {
          "datetime": "2024-01-15T13:00:00",
          "power_active": 1.243,
          "power_reactive": 0.081,
          "voltage_magnitude": 229.7,
          "voltage_angle": -0.42,
          "phase": "R"
        }
      ]
    }
  },
  "node to corresponding index": {
    "grid001": { "PT": 0, "N1": 1, "N2": 2 }
  },
  "topology (index)": {
    "grid001": [[0, 1], [1, 2]]
  },
  "conn_data": {
    "grid001": [["CBL1", 100.0], ["CBL1", 120.0]]
  }
}
```

**Errors**

| Status | Cause |
|---|---|
| `500` | No measurements found for the training grids, or no nodes/connections found for one of them, or another database error — all surfaced as `500` because the underlying helpers raise a generic `Exception` rather than an `HTTPException`. |

---

### `GET /topology_discovery_benchmark/topology-data`

Returns historical measurements for every grid marked
`GridUsage.topology_detection_test = 1`, with the real `grid_id` replaced by
a persistent anonymised key — a random UUID4, generated the first time a
grid is seen and stored in a `GridAnonymisedMapping` table keyed on
`grid_id` — and **the topology itself deliberately withheld**; it's the
hidden target participants must infer from the measurement patterns. Unlike
the [anonymisation pattern](index.md#anonymisation-pattern) used elsewhere,
only the grid identity is hidden here: real `node_id` and `phase` values are
still exposed in every record.

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `difficulty` | string | no | `clean` | One of `clean`, `easy`, `medium`, `hard` — see [difficulty/noise profiles](index.md#difficulty-and-noise-profiles). |

**Response** `200`

```json
{
  "difficulty": "clean",
  "profile": {
    "pq_rel_sigma": 0.0,
    "v_mag_rel_sigma": 0.0,
    "v_ang_rel_sigma": 0.0,
    "outlier_prob": 0.0,
    "outlier_scale": 0.0
  },
  "grids": {
    "7c1e9e2a-6b0e-4a2f-9c3e-1f2a3b4c5d6e": {
      "N1": [
        {
          "datetime": "2024-01-15T13:00:00",
          "power_active": 1.243,
          "power_reactive": 0.081,
          "voltage_magnitude": 229.7,
          "voltage_angle": -0.42,
          "phase": "R"
        }
      ]
    }
  }
}
```

**Errors**

| Status | Cause |
|---|---|
| `500` | No measurements found for the test grids, or another database error. |

---

### `POST /topology_discovery_benchmark/submit-results`

Submits a guessed edge list for a grid, as a list of `[from_index, to_index]`
pairs using the same `PT`-first node-index ordering as the `"node to
corresponding index"` map above (and `gridarena.powerflow.get_grid_info
.get_nodes_from_grid`, used by the [Grid](grid.md) router). `grid_id` may be
either the real grid ID or the anonymised key returned by `GET
/topology-data` — it's resolved to the real grid ID (via
`GridAnonymisedMapping`) before being checked and stored. Resubmitting the
same `(guess_id, grid_id)` overwrites the previous guess.

**Request body**

```json
{
  "guess_id": "team-alpha",
  "grid_id": "7c1e9e2a-6b0e-4a2f-9c3e-1f2a3b4c5d6e",
  "guesses": [[0, 1], [1, 2]]
}
```

| Field | Type | Notes |
|---|---|---|
| `guess_id` | string | Caller-supplied participant identifier. |
| `grid_id` | string | Real grid ID or anonymised grid key. |
| `guesses` | array of `[int, int]` | Guessed edges as node-index pairs. At most 5000 entries. |

**Response** `200`

```json
{
  "status": "submitted",
  "accepted_edges": 2
}
```

**Errors**

| Status | Cause |
|---|---|
| `422` | `grid_id` (after resolving an anonymised key to a real one, if applicable) doesn't exist in `grids`. |
| `422` | Request body fails schema validation (e.g. more than 5000 edges). |
| `500` | Database error. |

---

### `GET /topology_discovery_benchmark/score`

Computes edge-overlap accuracy between a stored guess and the grid's true
connections: `correct` = guessed edges that are real, `incorrect_extra` =
guessed edges that aren't, `missed` = real edges not guessed, `accuracy` =
`correct / total_true_edges`. `grid_id` may be the real or anonymised ID; it
is **echoed back exactly as given** (not resolved) so a query using the
anonymised ID never leaks the real one.

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `guess_id` | string | yes | — | The participant identifier used when submitting. |
| `grid_id` | string | yes | — | Real or anonymised grid ID. |

**Response** `200`

```json
{
  "guess_id": "team-alpha",
  "grid_id": "7c1e9e2a-6b0e-4a2f-9c3e-1f2a3b4c5d6e",
  "total_true_edges": 2,
  "guessed_edges": 2,
  "correct": 2,
  "incorrect_extra": 0,
  "missed": 0,
  "accuracy": 1.0
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No stored guess (`TopologyUserGuesses` row) for that `(guess_id, grid_id)` pair. |
| `500` | Database error. |
