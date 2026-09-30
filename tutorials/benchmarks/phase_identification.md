# Phase Identification Benchmark

## Overview

The Phase Identification benchmark tests the ability to determine which electrical phase (R, S, or T) each node in a low-voltage grid belongs to, using only smart-meter time-series measurements. In a real distribution network, phase labels are often unknown or incorrectly recorded; this benchmark evaluates algorithms that can recover them from data alone.

The benchmark follows a four-step pipeline:

1. **Download training data** — labelled measurements with true phases visible.
2. **Download test data** — anonymised measurements with phases hidden.
3. **Submit predictions** — a mapping of anonymised keys to predicted phases.
4. **Retrieve score** — accuracy computed against the hidden ground truth.

---

## Prerequisites

Before using this benchmark, a grid must be registered with historical measurements uploaded, and the grid must be marked for phase detection in the `GridUsage` table (either `phase_detection_train = 1` or `phase_detection_test = 1`, or both).

---

## Step 1: Download Training Data

**Endpoint:** `GET /phase_identification_benchmark/training-phase-data`

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `difficulty` | `clean`, `easy`, `medium`, `hard` | `clean` | Controls the amount of noise applied to measurements. |

### What is returned

The response contains all measurements from grids marked for training (`phase_detection_train = 1`), organised by grid and node. The true phase label is included in every record.

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
    "grid_001": {
      "NODE1": [
        {
          "datetime": "2025-07-01T00:00:00",
          "power_active": 10.0,
          "power_reactive": 5.0,
          "voltage_magnitude": 230.0,
          "voltage_angle": 0.1,
          "phase": "R"
        },
        {
          "datetime": "2025-07-01T00:15:00",
          "power_active": 12.0,
          "power_reactive": 6.0,
          "voltage_magnitude": 231.0,
          "voltage_angle": 0.2,
          "phase": "R"
        }
      ],
      "NODE2": [
        {
          "datetime": "2025-07-01T00:00:00",
          "power_active": 9.0,
          "power_reactive": 4.5,
          "voltage_magnitude": 229.5,
          "voltage_angle": -2.0,
          "phase": "S"
        }
      ]
    }
  }
}
```

**Key points:**
- The `phase` field is visible — this is ground truth you can use for algorithm training.
- Each node appears with its real `node_id`.
- Measurement fields (`power_active`, `power_reactive`, `voltage_magnitude`, `voltage_angle`) may have Gaussian noise and occasional outliers applied, depending on the `difficulty` parameter.

### Noise profiles

| Difficulty | Power noise (relative) | Voltage magnitude noise | Voltage angle noise | Outlier probability |
|------------|------------------------|-------------------------|---------------------|---------------------|
| `clean` | 0% | 0% | 0% | 0% |
| `easy` | 1% | 0.2% | 2% | 0.2% |
| `medium` | 3% | 0.5% | 6% | 0.8% |
| `hard` | 7% | 1% | 15% | 2% |

Noise is deterministic: the same difficulty level produces the same corrupted values on every call, because each per-series RNG is seeded with `SHA-256(grid_id:node_id:phase:difficulty)`.

---

## Step 2: Download Test Data

**Endpoint:** `GET /phase_identification_benchmark/phase-data`

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `difficulty` | `clean`, `easy`, `medium`, `hard` | `clean` | Controls the amount of noise applied to measurements. |

### What is returned

The response contains measurements from grids marked for testing (`phase_detection_test = 1`). The real `node_id` and `phase` are replaced with persistent anonymised UUIDs. The `phase` field is removed entirely.

```json
{
  "difficulty": "clean",
  "profile": { ... },
  "grids": {
    "grid_001": {
      "a312d3c8-d978-4a2a-91b6-9dc4b7d2e1b2": [
        {
          "datetime": "2025-07-01T00:00:00",
          "power_active": 10.0,
          "power_reactive": 5.0,
          "voltage_magnitude": 230.0,
          "voltage_angle": 0.1
        }
      ],
      "f7e1b0c4-8a3d-4f2e-b5c1-2d9e8a7b6c5d": [
        {
          "datetime": "2025-07-01T00:00:00",
          "power_active": 9.0,
          "power_reactive": 4.5,
          "voltage_magnitude": 229.5,
          "voltage_angle": -2.0
        }
      ]
    }
  }
}
```

**Key points:**
- There is no `phase` field — this is what you must predict.
- Each unique combination of `(grid_id, node_id, phase)` is mapped to a persistent UUID. The same call returns the same UUIDs, so you can download the data multiple times.
- The same noise profile and deterministic seeding apply as in the training endpoint.

---

## Step 3: Submit Predictions

**Endpoint:** `POST /phase_identification_benchmark/submit-results`

**Content-Type:** `application/json`

### Request body

```json
{
  "guess_id": "alice_v1",
  "grid_id": "grid_001",
  "guesses": {
    "a312d3c8-d978-4a2a-91b6-9dc4b7d2e1b2": "R",
    "f7e1b0c4-8a3d-4f2e-b5c1-2d9e8a7b6c5d": "S"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `guess_id` | string | yes | Identifies this submission. Use different values (e.g. `alice_v1`, `alice_v2`) to keep multiple independent attempts. |
| `grid_id` | string | yes | The grid the guesses belong to. |
| `guesses` | object | yes | A mapping from anonymised keys (from step 2) to predicted phases. Each value must be `"R"`, `"S"`, or `"T"`. |

### Validation

- All submitted anonymised keys are validated against the `AnonymisedMapping` table. Unknown keys return HTTP 422.
- If no mapping exists for the grid (i.e. test data was never downloaded), the endpoint returns HTTP 422 with a message to download phase data first.
- Resubmitting with the same `(guess_id, grid_id, anonymised_key)` overwrites the previous prediction.

### Response

```json
{
  "status": "submitted",
  "accepted": 2
}
```

### What the user uploads via the UI

When using the web interface, the prediction **file** only needs to contain the inner `guesses` mapping:

```json
{
  "a312d3c8-...": "R",
  "f7e1b0c4-...": "S"
}
```

The `guess_id` and `grid_id` are taken from the "Submission ID" and "Grid ID" form fields and wrapped around the file content automatically by the JavaScript before sending.

---

## Step 4: Retrieve Score

**Endpoint:** `GET /phase_identification_benchmark/score`

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `guess_id` | string | yes | The submission identifier used when submitting. |
| `grid_id` | string | yes | The grid to score against. |

### Response

```json
{
  "guess_id": "alice_v1",
  "grid_id": "grid_001",
  "accuracy": 0.75
}
```

### How scoring works

Accuracy is computed as:

```
accuracy = correct / total_anonymised_keys_in_grid
```

- `correct` counts submissions where the guessed phase matches the true phase in the `AnonymisedMapping` table.
- `total_anonymised_keys_in_grid` is the total number of `(grid_id, node_id, phase)` tuples mapped for that grid — **not** the number of guesses submitted.

This means unguessed keys count as wrong. If you only submit guesses for half the nodes, your maximum achievable accuracy is 50%.

---

## Database Logic

### Tables involved

#### `GridUsage`

Controls which grids participate in which benchmarks.

| Column | Type | Description |
|--------|------|-------------|
| `grid_id` | TEXT PK | References the main `grids` table. |
| `phase_detection_train` | INTEGER | `1` if this grid provides training data. |
| `phase_detection_test` | INTEGER | `1` if this grid provides test data. |

#### `Measurements`

The source of all measurement data. Each row is one reading for one node at one timestamp.

| Column | Type |
|--------|------|
| `grid_id` | TEXT |
| `node_id` | TEXT |
| `phase` | TEXT (`R`, `S`, `T`) |
| `datetime` | TIMESTAMP |
| `power_active` | FLOAT |
| `power_reactive` | FLOAT |
| `voltage_magnitude` | FLOAT |
| `voltage_angle` | FLOAT |

#### `AnonymisedMapping`

Persistently maps each `(grid_id, node_id, phase)` tuple to a UUID. Created on-demand the first time test data is downloaded.

| Column | Type | Constraint |
|--------|------|------------|
| `grid_id` | TEXT | PK (composite) |
| `node_id` | TEXT | PK (composite) |
| `phase` | TEXT | PK (composite), CHECK IN (`R`, `S`, `T`) |
| `anonymised_key` | TEXT | UNIQUE |

#### `UserGuesses`

Stores submitted predictions.

| Column | Type | Constraint |
|--------|------|------------|
| `user_id` | TEXT | PK (composite) — this is the `guess_id` from the API |
| `grid_id` | TEXT | PK (composite) |
| `anonymised_key` | TEXT | PK (composite), FK → `AnonymisedMapping` |
| `guessed_phase` | TEXT | CHECK IN (`R`, `S`, `T`) |
| `timestamp` | TIMESTAMP | Auto-set on insert/update |

### Data flow

```
GET /training-phase-data
  → SELECT FROM Measurements WHERE grid_id IN (GridUsage.phase_detection_train = 1)
  → Apply seeded noise corruption
  → Return with real node_id and phase visible

GET /phase-data
  → SELECT FROM Measurements WHERE grid_id IN (GridUsage.phase_detection_test = 1)
  → CREATE/LOAD AnonymisedMapping UUIDs for each (grid_id, node_id, phase)
  → Apply seeded noise corruption
  → Return with anonymised keys, phase stripped

POST /submit-results
  → Validate anonymised keys exist in AnonymisedMapping
  → UPSERT into UserGuesses

GET /score
  → JOIN UserGuesses WITH AnonymisedMapping ON anonymised_key
  → COUNT WHERE guessed_phase = AnonymisedMapping.phase
  → Return correct / total
```
