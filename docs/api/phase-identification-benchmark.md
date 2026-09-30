# Phase Identification Benchmark

This benchmark tests a participant's ability to infer which grid phase (`R`,
`S`, or `T`) each meter/node is connected to, from historical power and
voltage measurements. The workflow is: download anonymised per-node
measurement series via `GET /phase-data`, submit a guessed phase per
anonymised key via `POST /submit-results`, then check accuracy via
`GET /score`. `GET /training-phase-data` exposes the same kind of data for
training grids, with real node IDs and the true `phase` label included.

**Base path:** `/phase_identification_benchmark`

Also serves a browser UI at `/phase_identification_benchmark/ui`.

## Endpoints

### `GET /phase_identification_benchmark/training-phase-data`

Returns historical measurements for every grid marked for phase-detection
training (`GridUsage.phase_detection_train = 1`), keyed by real `grid_id` →
`node_id`. Each record includes the true `phase` label, since this data is
meant for training, not for scoring. Noise is applied per the requested
`difficulty` and is deterministic per `(grid_id, node_id, phase, difficulty)`.

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `difficulty` | string | no | `clean` | One of `clean`, `easy`, `medium`, `hard` — see [difficulty/noise profiles](index.md#difficulty-and-noise-profiles). |

**Response** `200`

```json
{
  "difficulty": "medium",
  "profile": {
    "pq_rel_sigma": 0.03,
    "v_mag_rel_sigma": 0.005,
    "v_ang_rel_sigma": 0.06,
    "outlier_prob": 0.008,
    "outlier_scale": 12.0
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
  }
}
```

**Errors**

| Status | Cause |
|---|---|
| `500` | No grid is marked `phase_detection_train = 1`, or no measurements exist for the training grids, or another database error. Both "no data" cases raise a generic `Exception` internally that the router wraps as `500` rather than `404`. |

---

### `GET /phase_identification_benchmark/phase-data`

Returns historical measurements for every grid marked for phase-detection
testing (`GridUsage.phase_detection_test = 1`), with each `(node_id, phase)`
pair replaced by a persistent anonymised key and the `phase` field removed
from every record, since it's the hidden label participants must guess — see
[anonymisation pattern](index.md#anonymisation-pattern). The first time a
given `(grid_id, node_id, phase)` is seen, a random UUID4 key is generated
and stored in `AnonymisedMapping`; the same key is returned on every later
call for that triple.

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
      "a312d3c8-d978-4a2a-91b6-9dc4b7d2e1b2": [
        {
          "datetime": "2024-01-15T13:00:00",
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
| `500` | No grid is marked `phase_detection_test = 1`, or no measurements exist for the test grids, or another database error (same "no data → 500" behavior as above). |

---

### `POST /phase_identification_benchmark/submit-results`

Submits guessed phases for anonymised keys returned by `GET /phase-data`.
Every key must already exist in `AnonymisedMapping` for the given `grid_id`.
Resubmitting the same `(guess_id, grid_id, anonymised_key)` overwrites the
previous guess (`ON CONFLICT ... DO UPDATE`), updating its `timestamp`.

**Request body**

```json
{
  "guess_id": "team-alpha",
  "grid_id": "grid001",
  "guesses": {
    "a312d3c8-d978-4a2a-91b6-9dc4b7d2e1b2": "R"
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `guess_id` | string | Caller-supplied identifier for the participant/submission — not an authenticated credential. |
| `grid_id` | string | Real grid ID. |
| `guesses` | object (`string` → `"R"｜"S"｜"T"`) | Anonymised key → guessed phase. At most 5000 entries. |

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
| `422` | No `AnonymisedMapping` rows exist yet for `grid_id` (download `/phase-data` first to generate them). |
| `422` | One or more submitted keys aren't present in `AnonymisedMapping` for that grid. |
| `422` | Request body fails schema validation (e.g. more than 5000 guesses, or a guess value other than `R`/`S`/`T`). |
| `500` | Database error. |

---

### `GET /phase_identification_benchmark/score`

Computes guessing accuracy for a `(guess_id, grid_id)` pair by joining
`UserGuesses` against `AnonymisedMapping` on the true `phase`, without
revealing which individual guesses were right or wrong.

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `guess_id` | string | yes | — | The participant identifier used when submitting. |
| `grid_id` | string | yes | — | Grid to score. |

**Response** `200`

```json
{
  "guess_id": "team-alpha",
  "grid_id": "grid001",
  "accuracy": 0.8571
}
```

!!! note
    `accuracy` is `0.0` when the grid has no `AnonymisedMapping` rows yet
    (division-by-zero is guarded against), not an error — check
    `AnonymisedMapping`/`UserGuesses` existence yourself if you need to tell
    "no data" apart from "0% correct".

**Errors**

| Status | Cause |
|---|---|
| `500` | Database error. |
