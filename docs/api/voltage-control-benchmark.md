# Voltage Control Benchmark

This benchmark asks a participant to correct voltage violations — over- or
under-voltage snapshots — by adjusting node voltages and loads. The workflow
is: download violation snapshots with hidden reference solutions via
`GET /voltage-control-data`, submit corrected voltages/loads per anonymised
snapshot key via `POST /submit-results`, then check score via `GET /score`.
`GET /training-scenarios` returns the same kind of snapshot data for training
grids, including the reference solutions and precomputed scoring metrics.

**Base path:** `/voltage_control_benchmark`

Also serves a browser UI at `/voltage_control_benchmark/ui`.

## Endpoints

### `GET /voltage_control_benchmark/training-scenarios`

Returns training snapshots — `(grid_id, datetime)` combinations with at
least one voltage violation, for grids marked
`GridUsage.voltage_control_train = 1` — together with their reference
`VoltageControlSolutions` (if any) and precomputed scoring metrics. Real
`grid_id`, `node_id`, and `datetime` are all exposed; nothing is hidden in
this endpoint, since it's training data.

`difficulty` here works differently from the other three benchmarks: it
doesn't corrupt values, it filters *which* snapshots come back. Each
snapshot gets a `hardness_score` — for snapshots with a reference solution,
`0.45 × severity_norm + 0.35 × effort_norm + 0.10 × residual_rate + 0.10 ×
grid_complexity_norm`; for snapshots without one, `0.55 × severity_norm +
0.30 × violation_rate + 0.15 × grid_complexity_norm`. Snapshots are then
bucketed by tercile of `hardness_score` among the candidate population:
`easy` = bottom 33%, `medium` = middle third, `hard` = top 33% (`clean` =
every matching snapshot, unfiltered). Snapshots that have a reference
solution are preferred as the population the terciles are computed over; if
none of the matching snapshots have one, all of them are used instead
(surfaced as `"preference": "no_solutions_found_fallback_all"`).

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `voltage_limit` | float | yes | — | Threshold voltage in volts. |
| `Scenario` | string | yes | — | `Overvoltages` (snapshots where `voltage_magnitude > voltage_limit`) or `Undervoltages` (`voltage_magnitude < voltage_limit`). |
| `difficulty` | string | no | `clean` | `clean`, `easy`, `medium`, or `hard` — hardness-tercile filter, see above. |

**Response** `200`

```json
{
  "difficulty": "hard",
  "difficulty_profile": {
    "method": "quantiles_33_66",
    "t1": 0.081,
    "t2": 0.203,
    "preference": "solutions_only",
    "preferred_population": 12
  },
  "scenario": "Overvoltages",
  "voltage_limit": 253.0,
  "grids": {
    "grid001": {
      "2024-01-15T13:00:00": {
        "measurements": [
          {
            "node_id": "N1",
            "phase": "R",
            "datetime": "2024-01-15T13:00:00",
            "power_active": 1.243,
            "power_reactive": 0.081,
            "voltage_magnitude": 255.4,
            "voltage_angle": -0.42
          }
        ],
        "solutions": [
          {
            "node_id": "N1",
            "phase": "R",
            "corrected_voltage": 231.8,
            "adjusted_power_active": 0.912,
            "adjusted_power_reactive": 0.075,
            "created_at": "2024-01-10T09:00:00"
          }
        ],
        "metrics": {
          "n_nodes": 1,
          "n_violations": 1,
          "violation_rate": 1.0,
          "sum_deviation_volts": 2.4,
          "max_deviation_volts": 2.4,
          "severity_norm": 0.0104,
          "effort_norm": 0.2664,
          "residual_violations": 0,
          "residual_rate": 0.0,
          "grid_complexity_norm": 0.42,
          "grid_complexity_profile": {
            "grid_n_nodes": 20,
            "grid_n_connections": 19,
            "grid_edge_density": 1.0,
            "grid_complexity_raw": 0.7,
            "grid_complexity_norm": 0.42
          },
          "hardness_score": 0.211
        }
      }
    }
  }
}
```

**Errors**

| Status | Cause |
|---|---|
| `500` | No snapshot found above/below `voltage_limit` for the training grids, or another database error — the "no snapshots" case raises a generic `Exception` internally that the router wraps as `500`. |

---

### `GET /voltage_control_benchmark/voltage-control-data`

Returns testing snapshots for grids marked
`GridUsage.voltage_control_test = 1`, filtered and bucketed by `difficulty`
the same way as `/training-scenarios` above, but with reference solutions
withheld and the `(grid_id, datetime)` pair replaced by a persistent
anonymised key — see [anonymisation pattern](index.md#anonymisation-pattern).
Real `node_id`/`phase` are still exposed; only the snapshot's timestamp
identity is hidden.

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `voltage_limit` | float | yes | — | Threshold voltage in volts. |
| `Scenario` | string | no | `Overvoltages` | `Overvoltages` or `Undervoltages`. |
| `difficulty` | string | no | `clean` | Hardness-tercile filter — see `/training-scenarios` above. |

**Response** `200`

```json
{
  "difficulty": "clean",
  "difficulty_profile": {
    "method": "none",
    "t1": 0.0,
    "t2": 0.0,
    "preference": "solutions_only",
    "preferred_population": 8
  },
  "scenario": "Overvoltages",
  "voltage_limit": 253.0,
  "grids": {
    "grid001": {
      "5b6c7d8e-9f0a-4b1c-8d2e-3f4a5b6c7d8e": [
        {
          "node_id": "N1",
          "phase": "R",
          "power_active": 1.243,
          "power_reactive": 0.081,
          "voltage_magnitude": 255.4,
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
| `500` | No snapshot found above/below `voltage_limit` for the test grids, or another database error. |

---

### `POST /voltage_control_benchmark/submit-results`

Submits corrected voltages and (optionally) adjusted active/reactive power
per node, for one or more anonymised snapshots returned by
`GET /voltage-control-data`. Resubmitting the same `(guess_id, grid_id,
anonymised_key)` overwrites the previous guess.

**Request body**

```json
{
  "guess_id": "team-alpha",
  "grid_id": "grid001",
  "guesses": {
    "5b6c7d8e-9f0a-4b1c-8d2e-3f4a5b6c7d8e": [
      {
        "node_id": "N1",
        "phase": "R",
        "corrected_voltage": 231.5,
        "adjusted_power_active": 0.912,
        "adjusted_power_reactive": 0.075
      }
    ]
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `guess_id` | string | Caller-supplied participant identifier. |
| `grid_id` | string | Real grid ID (not an anonymised key). |
| `guesses` | object (anonymised snapshot key → array of node solutions) | At most 5000 keys, each array capped at 5000 entries. |
| `guesses[key][].node_id` | string | Real node ID. |
| `guesses[key][].phase` | `"R"｜"S"｜"T"`, optional | |
| `guesses[key][].corrected_voltage` | float | Required. |
| `guesses[key][].adjusted_power_active` | float, optional | Treated as unchanged from the measured value at scoring time if omitted. |
| `guesses[key][].adjusted_power_reactive` | float, optional | |

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
| `422` | `grid_id` doesn't exist in `grids`. |
| `422` | One or more submitted anonymised keys aren't in `VoltageTimestampMapping` for that grid. |
| `422` | Request body fails schema validation (e.g. more than 5000 scenario keys or node solutions per key). |
| `500` | Database error. |

---

### `GET /voltage_control_benchmark/score`

Scores a participant's submitted corrections against the true measurements
and, where available, the reference `VoltageControlSolutions`, per snapshot,
then averages the per-snapshot scores weighted by node count into
`overall_score`. Only nodes/phases the participant actually submitted a
`corrected_voltage` for (matching the original measurement's `phase`) are
scored; nodes without a matching guess are skipped for that snapshot.

Two scoring modes, chosen per snapshot:

- **Reference solution available, with at least one matching node:** if the
  participant's corrected voltages are within `1.0` V (mean absolute error)
  of the reference solution's `corrected_voltage`, the score is purely an
  *effort* factor — `1 / (1 + effort_norm / 0.15)`, where `effort_norm` is
  total `|ΔP|` relative to total `|P|` across the scored nodes — so once you
  match the optimum, moving less load scores higher (`mode:
  "ref_voltage_then_effort"`). If the MAE exceeds `1.0` V, the effort factor
  is further multiplied by a voltage-miss penalty that decays as the MAE
  grows (`mode: "ref_voltage_miss_penalised"`).
- **No reference solution, or no overlapping node:** falls back to an
  outcome-only heuristic per node — `0.7 × max(voltage_score, 0) + 0.2 ×
  power_penalty + 0.1 × fixed-violation bonus`, averaged across nodes — then
  multiplied by the same effort factor (`mode: "outcome_only_fallback"`).

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `guess_id` | string | yes | — | The participant identifier used when submitting. |
| `grid_id` | string | yes | — | Real grid ID. |

**Response** `200`

```json
{
  "guess_id": "team-alpha",
  "grid_id": "grid001",
  "total_nodes": 1,
  "overall_score": 0.87,
  "per_timestamp": [
    {
      "anonymised_key": "5b6c7d8e-9f0a-4b1c-8d2e-3f4a5b6c7d8e",
      "datetime": "2024-01-15T13:00:00",
      "nodes_total": 1,
      "mode": "ref_voltage_then_effort",
      "reference_available": true,
      "reference_voltage_mae": 0.3,
      "reference_voltage_tol": 1.0,
      "voltage_factor": 1.0,
      "effort_norm": 0.266,
      "effort_factor": 0.87,
      "timestamp_score": 0.87,
      "average_node_score_diagnostic": 0.72,
      "nodes": [
        {
          "node_id": "N1",
          "phase": "R",
          "measured_voltage": 255.4,
          "corrected_voltage": 231.5,
          "measured_power_active": 1.243,
          "corrected_power_active": 0.912,
          "voltage_score": 1.0,
          "power_penalty": 0.734,
          "bonus": 1.0,
          "node_score": 0.847,
          "reference_corrected_voltage": 231.8
        }
      ],
      "reference_voltage_coverage": 1.0
    }
  ]
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No stored `VCUserGuesses` rows for `(guess_id, grid_id)`. |
| `500` | Database error. |
