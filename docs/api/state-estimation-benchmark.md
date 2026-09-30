# State Estimation Benchmark

This benchmark asks a participant to estimate the voltage magnitude and
angle of "unknown" nodes at a specific grid snapshot, given the current
measurements of "known" nodes plus historical series for every node. All
grid and node identifiers are masked (`GridMask`/`NodeMask`). The workflow
is: request an estimation task via `GET /state-data`, submit voltage
estimates via `POST /submit-estimates`, then check score via
`GET /state-score`; `GET /training-state-data` exposes the same masked data
for training grids, with full historical series for every node and no
known/unknown split.

**Base path:** `/state_estimation_benchmark`

Also serves a browser UI at `/state_estimation_benchmark/ui`.

## Endpoints

### `GET /state_estimation_benchmark/training-state-data`

Returns every measurement for every grid marked
`GridUsage.state_estimation_train = 1`, grouped by masked grid ID → masked
node ID, with noise applied per `noise_difficulty`. Grid/node masks
(`GridMask`/`NodeMask`) are created on demand the first time a real
grid/node is seen and reused afterwards — see
[anonymisation pattern](index.md#anonymisation-pattern).

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `noise_difficulty` | string | no | `clean` | One of `clean`, `easy`, `medium`, `hard` — see [difficulty/noise profiles](index.md#difficulty-and-noise-profiles). |
| `observability` | string | no | `medium` | Accepted but unused by this endpoint — `observability` only affects the known/unknown split created by `GET /state-data`. |

**Response** `200`

```json
{
  "noise_difficulty": "clean",
  "noise_profile": {
    "pq_rel_sigma": 0.0,
    "v_mag_rel_sigma": 0.0,
    "v_ang_rel_sigma": 0.0,
    "outlier_prob": 0.0,
    "outlier_scale": 0.0
  },
  "grids": {
    "8f2a1c90b3": {
      "4e7b6a1c2d": [
        {
          "datetime": "2024-01-15T13:00:00",
          "phase": "R",
          "power_active": 1.243,
          "power_reactive": 0.081,
          "voltage_magnitude": 229.7,
          "voltage_angle": -0.42
        }
      ]
    }
  }
}
```

**Errors**

| Status | Cause |
|---|---|
| `500` | Database error. Unlike the other three benchmarks' "no data" endpoints, no grid marked for training doesn't raise an error here — the `grid_id = ANY(%s)` query with an empty list simply matches no rows, so the response is still `200` with `"grids": {}`. |

---

### `GET /state_estimation_benchmark/state-data`

Retrieves (or creates) an estimation task for `user_id`: a masked grid, a
target timestamp, and a known/unknown node split. Returns the known nodes'
measurements at that timestamp, the still-hidden list of unknown node IDs,
and historical measurement series (strictly before the target timestamp)
for every node — with progressively less recent history exposed for
*unknown* nodes as `observability` gets harder.

!!! note "Idempotent per user"
    If `user_id` already has an open estimation task — one created by a
    previous call to this endpoint that hasn't yet been submitted via
    `POST /submit-estimates` — that exact same task (same masked grid,
    timestamp, and known/unknown split) is returned again, instead of a new
    one being created. A new task is only created once no open task exists
    for that user (first call, or the previous task was already submitted).
    `noise_difficulty` is re-applied fresh on every call, even when
    returning an existing task; `observability` is only consulted when a
    *new* task is created, since it drives the known/unknown split that
    gets persisted to `EstimationTasks` and is then fixed for that task's
    lifetime.

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `user_id` | string | yes | — | Caller-supplied participant identifier; also the key used for the idempotency check above. |
| `noise_difficulty` | string | no | `clean` | See [difficulty/noise profiles](index.md#difficulty-and-noise-profiles). |
| `observability` | string | no | `medium` | One of `clean`, `easy`, `medium`, `hard`. Controls what fraction of nodes are made "unknown" and how many hours of history are withheld before the target timestamp for them. Only applied when a new task is created — see table below. |

**Observability profile** (`min_non_obs_frac`/`max_non_obs_frac` bound the
fraction of nodes made unknown; `unknown_history_hours` is how far back from
the target timestamp history is withheld for unknown nodes):

| `observability` | non-observable fraction | `unknown_history_hours` |
|---|---|---|
| `clean` | 0 | 0.0 |
| `easy` | `[0, 1/3)` | 1.0 |
| `medium` | `[1/3, 2/3)` | 6.0 |
| `hard` | `[2/3, ~1)` | 12.0 |

**Response** `200`

```json
{
  "Masked GridID": "8f2a1c90b3",
  "Estimation Task ID": "4c9d1e2a7b",
  "noise_difficulty": "clean",
  "noise_profile": {
    "pq_rel_sigma": 0.0,
    "v_mag_rel_sigma": 0.0,
    "v_ang_rel_sigma": 0.0,
    "outlier_prob": 0.0,
    "outlier_scale": 0.0
  },
  "observability": "medium",
  "observability_profile": {
    "min_non_obs_frac": 0.3333333333333333,
    "max_non_obs_frac": 0.6666666666666666,
    "unknown_history_hours": 6.0
  },
  "Current State": {
    "known_nodes": {
      "4e7b6a1c2d": {
        "power_active": 1.243,
        "power_reactive": 0.081,
        "voltage_magnitude": 229.7,
        "voltage_angle": -0.42
      }
    },
    "unknown_nodes": ["9a0b1c2d3e"]
  },
  "Measurement Data": {
    "4e7b6a1c2d": [
      {
        "datetime": "2024-01-15T12:45:00",
        "power_active": 1.201,
        "power_reactive": 0.077,
        "voltage_magnitude": 229.9,
        "voltage_angle": -0.39
      }
    ],
    "9a0b1c2d3e": [
      {
        "datetime": "2024-01-15T06:45:00",
        "power_active": 0.892,
        "power_reactive": 0.061,
        "voltage_magnitude": 230.4,
        "voltage_angle": -0.18
      }
    ]
  }
}
```

**Errors**

| Status | Cause |
|---|---|
| `500` | Database error, **including** the "no grid is currently marked `state_estimation_test = 1`" case: this handler raises an `HTTPException(404, ...)` internally when no eligible grid is found while creating a new task, but — unlike the other endpoints in this router — it has no `except HTTPException: raise` before its generic `except Exception`, so that `404` gets caught and re-wrapped as `500` with a `"Database error: ..."` detail. A client should treat any `500` here as potentially meaning "no grid available", not only a genuine database failure. |

---

### `POST /state_estimation_benchmark/submit-estimates`

Submits voltage magnitude/angle estimates for the masked nodes of one
estimation task. For each `masked_node_id`, the real `(node_id, phase)` is
resolved via `NodeMask` and the estimate is upserted into `StateEstimates`;
resubmitting the same `(user_id, estimation_id, grid_id, timestamp, node_id,
phase)` overwrites the previous value.

**Request body**

```json
{
  "user_id": "team-alpha",
  "estimation_id": "4c9d1e2a7b",
  "grid_id": "8f2a1c90b3",
  "timestamp": "2024-01-15T13:00:00",
  "estimates": [
    { "masked_node_id": "9a0b1c2d3e", "voltage_magnitude": 230.1, "voltage_angle": -0.15 }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `user_id` | string | Must match the `user_id` used to create the task via `GET /state-data`. |
| `estimation_id` | string | The `"Estimation Task ID"` returned by `GET /state-data`. |
| `grid_id` | string | The **masked** grid ID (`"Masked GridID"` from `GET /state-data`), not the real one. |
| `timestamp` | string | Timestamp associated with the estimate; stored as-is on the `StateEstimates` row. |
| `estimates` | array of `{masked_node_id, voltage_magnitude, voltage_angle}` | At most 5000 entries. |

**Response** `200`

```json
{
  "status": "submitted",
  "accepted": 1
}
```

**Errors**

| Status | Cause |
|---|---|
| `422` | `grid_id` isn't a known masked grid ID (download `/state-data` first). |
| `400` | The grid resolved from the mask exists but isn't marked for state-estimation training or testing. |
| `422` | `estimation_id` doesn't exist for `user_id` (download `/state-data` first to create a task). |
| `422` | One of the submitted `masked_node_id` values isn't in `NodeMask` for this grid. |
| `422` | Request body fails schema validation (e.g. more than 5000 estimates). |
| `500` | Database error. |

---

### `GET /state_estimation_benchmark/state-score`

Computes an error score for a submitted estimation task: mean squared error
of voltage magnitude plus the mean absolute value of `sin(angle_predicted -
angle_true)` (avoids angle wrap-around at ±180°), evaluated only over the
task's **unknown** nodes (`EstimationTasks.known = 0`), by joining
`StateEstimates` against `Measurements` via `EstimationTasks`. Lower is
better; `0` is a perfect match.

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `user_id` | string | yes | — | The participant identifier used when submitting estimates. |
| `estimation_id` | string | yes | — | The estimation task to score. |

**Response** `200`

```json
{
  "user_id": "team-alpha",
  "estimation_id": "4c9d1e2a7b",
  "score": 0.043821
}
```

!!! note
    If nothing has been submitted yet for `estimation_id`, or the task has
    no unknown nodes (e.g. it was created with `observability=clean`), the
    score is computed over empty arrays and comes back as `NaN` rather than
    an error.

**Errors**

| Status | Cause |
|---|---|
| `500` | Database error. |
