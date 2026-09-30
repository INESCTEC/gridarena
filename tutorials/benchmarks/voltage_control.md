# Voltage Control Benchmark

## Overview

The Voltage Control benchmark tests the ability to propose corrective actions that bring node voltages back within acceptable limits when violations are detected. Given a snapshot of a grid with overvoltage or undervoltage conditions, the algorithm must suggest adjusted power injections and target voltages that resolve the violations with minimal intervention.

The acceptable voltage band is **230 V ± 5%** (207 V to 253 V). Anything outside this range is a violation.

The benchmark follows a four-step pipeline:

1. **Download training scenarios** — snapshots with measurements, reference solutions, and hardness metrics.
2. **Download test data** — snapshots with anonymised timestamps and hidden solutions.
3. **Submit corrective actions** — per-node voltage and power adjustments for each snapshot.
4. **Retrieve score** — a composite score combining voltage correction quality and effort efficiency.

---

## Prerequisites

A grid must be registered with historical measurements and marked for voltage control in the `GridUsage` table (`voltage_control_train = 1` and/or `voltage_control_test = 1`). Some nodes must have measurements with voltage magnitudes outside the ±5% band for snapshots to be selected.

---

## Step 1: Download Training Scenarios

**Endpoint:** `GET /voltage_control_benchmark/training-scenarios`

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `voltage_limit` | float | yes | — | Voltage threshold. Snapshots where at least one node crosses this threshold are included. |
| `Scenario` | `Overvoltages` or `Undervoltages` | yes | — | Whether to find snapshots with voltages above or below the limit. |
| `difficulty` | `clean`, `easy`, `medium`, `hard` | no | `clean` | Filters snapshots by hardness quantile (not noise — see below). |

### What is returned

The response contains measurement snapshots grouped by grid and timestamp, with reference solutions (if they exist in the database) and hardness metrics.

```json
{
  "difficulty": "clean",
  "difficulty_profile": {
    "method": "none",
    "t1": 0.0,
    "t2": 0.0,
    "preference": "solutions_only",
    "preferred_population": 5
  },
  "scenario": "Overvoltages",
  "voltage_limit": 240.0,
  "grids": {
    "grid_001": {
      "2025-07-01T00:00:00": {
        "measurements": [
          {
            "node_id": "PT",
            "phase": "R",
            "datetime": "2025-07-01T00:00:00",
            "power_active": 0.0,
            "power_reactive": 0.0,
            "voltage_magnitude": 230.0,
            "voltage_angle": 0.0
          },
          {
            "node_id": "NODE1",
            "phase": "R",
            "datetime": "2025-07-01T00:00:00",
            "power_active": 10.0,
            "power_reactive": 5.0,
            "voltage_magnitude": 245.0,
            "voltage_angle": 0.1
          }
        ],
        "solutions": [
          {
            "node_id": "NODE1",
            "phase": "R",
            "corrected_voltage": 229.5,
            "adjusted_power_active": 8.0,
            "adjusted_power_reactive": 4.0,
            "created_at": "2025-07-01T12:00:00"
          }
        ],
        "metrics": {
          "n_nodes": 2,
          "n_violations": 1,
          "violation_rate": 0.5,
          "sum_deviation_volts": 15.0,
          "max_deviation_volts": 15.0,
          "severity_norm": 0.032609,
          "effort_norm": 0.2,
          "residual_violations": 0,
          "residual_rate": 0.0,
          "grid_complexity_norm": 0.45,
          "hardness_score": 0.1297
        }
      }
    }
  }
}
```

**Key points:**
- `measurements` is a full snapshot — every node at that timestamp, including nodes that are not in violation.
- `solutions` contains reference optimal corrections (if they exist in the `VoltageControlSolutions` table). Not every snapshot has solutions.
- `metrics` describes the hardness of the scenario. The `hardness_score` is used for difficulty filtering.

### Difficulty filtering

Unlike the phase/topology benchmarks where difficulty controls noise, here difficulty filters **which snapshots** are returned based on hardness:

| Difficulty | Snapshots returned |
|------------|-------------------|
| `clean` | All snapshots (no filtering). |
| `easy` | Hardness score ≤ 33rd percentile. |
| `medium` | Hardness score between 33rd and 66th percentile. |
| `hard` | Hardness score ≥ 66th percentile. |

The hardness score combines multiple factors:

**With reference solutions:**
```
hardness = 0.45 × severity + 0.35 × effort + 0.10 × residual_rate + 0.10 × grid_complexity
```

**Without reference solutions:**
```
hardness = 0.55 × severity + 0.30 × violation_rate + 0.15 × grid_complexity
```

Where:
- `severity` = total voltage deviation outside band / (nominal voltage × node count)
- `effort` = total |ΔP| / total |P| (relative power adjustment)
- `residual_rate` = fraction of nodes still in violation after the reference correction
- `grid_complexity` = log-based metric of node count and connection count, normalised to [0, 1)

The system prefers snapshots that have reference solutions. If some snapshots have solutions and others do not, only the ones with solutions are included in the difficulty filtering.

---

## Step 2: Download Test Data

**Endpoint:** `GET /voltage_control_benchmark/voltage-control-data`

**Query parameters:**

Same as the training endpoint.

### What is returned

The response has the same structure as training but with two differences:
1. Each `(grid_id, datetime)` pair is mapped to a persistent anonymised UUID key.
2. Reference solutions and metrics are **not** returned.

```json
{
  "difficulty": "clean",
  "difficulty_profile": { ... },
  "scenario": "Overvoltages",
  "voltage_limit": 240.0,
  "grids": {
    "grid_001": {
      "a1b2c3d4-e5f6-7890-abcd-ef1234567890": [
        {
          "node_id": "PT",
          "phase": "R",
          "power_active": 0.0,
          "power_reactive": 0.0,
          "voltage_magnitude": 230.0,
          "voltage_angle": 0.0
        },
        {
          "node_id": "NODE1",
          "phase": "R",
          "power_active": 10.0,
          "power_reactive": 5.0,
          "voltage_magnitude": 245.0,
          "voltage_angle": 0.1
        }
      ]
    }
  }
}
```

**Key points:**
- The anonymised key (`a1b2c3d4-...`) replaces the timestamp. This key is persistent — the same `(grid_id, datetime)` always maps to the same UUID.
- Node IDs, phases, and measurement values are **not** anonymised — only the timestamp is hidden.
- The `datetime` field is removed from individual measurement records (but present implicitly via the anonymised key).

---

## Step 3: Submit Corrective Actions

**Endpoint:** `POST /voltage_control_benchmark/submit-results`

**Content-Type:** `application/json`

### Request body

```json
{
  "guess_id": "alice_v1",
  "grid_id": "grid_001",
  "guesses": {
    "a1b2c3d4-e5f6-7890-abcd-ef1234567890": [
      {
        "node_id": "NODE1",
        "phase": "R",
        "corrected_voltage": 229.5,
        "adjusted_power_active": 8.0,
        "adjusted_power_reactive": 4.0
      }
    ],
    "b2c3d4e5-f6a7-8901-bcde-f12345678901": [
      {
        "node_id": "NODE1",
        "phase": "R",
        "corrected_voltage": 231.0,
        "adjusted_power_active": 9.5
      },
      {
        "node_id": "NODE2",
        "phase": "S",
        "corrected_voltage": 228.0
      }
    ]
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `guess_id` | string | yes | Submission identifier. |
| `grid_id` | string | yes | The grid the corrections belong to. |
| `guesses` | object | yes | Maps anonymised snapshot keys to lists of per-node corrections. |

Each per-node correction has:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `node_id` | string | yes | The node to correct. |
| `phase` | `"R"`, `"S"`, `"T"`, or null | no | The phase. Must match the phase in the original measurement for the correction to be scored. |
| `corrected_voltage` | float | yes | The target voltage magnitude (V) after correction. |
| `adjusted_power_active` | float | no | The adjusted active power (kW). If omitted, original power is assumed unchanged. |
| `adjusted_power_reactive` | float | no | The adjusted reactive power (kVAR). If omitted, original is assumed unchanged. |

### Validation

- The grid must exist (HTTP 422 if not).
- All anonymised keys must exist in the `VoltageTimestampMapping` table (HTTP 422 for unknown keys).
- Resubmitting with the same `(guess_id, grid_id, anonymised_key)` overwrites the previous correction.

### Response

```json
{
  "status": "submitted",
  "accepted": 2
}
```

### What the user uploads via the UI

The prediction **file** only needs the `guesses` object:

```json
{
  "a1b2c3d4-...": [
    {
      "node_id": "NODE1",
      "phase": "R",
      "corrected_voltage": 229.5,
      "adjusted_power_active": 8.0
    }
  ]
}
```

The `guess_id` and `grid_id` are taken from the form fields.

---

## Step 4: Retrieve Score

**Endpoint:** `GET /voltage_control_benchmark/score`

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `guess_id` | string | yes | The submission identifier. |
| `grid_id` | string | yes | The grid to score. |

### Response

```json
{
  "guess_id": "alice_v1",
  "grid_id": "grid_001",
  "total_nodes": 4,
  "overall_score": 0.82,
  "per_timestamp": [
    {
      "anonymised_key": "a1b2c3d4-...",
      "datetime": "2025-07-01T00:00:00",
      "nodes_total": 2,
      "mode": "ref_voltage_then_effort",
      "reference_available": true,
      "reference_voltage_mae": 0.3,
      "reference_voltage_tol": 1.0,
      "voltage_factor": 1.0,
      "effort_norm": 0.12,
      "effort_factor": 0.556,
      "timestamp_score": 0.556,
      "average_node_score_diagnostic": 0.79,
      "reference_voltage_coverage": 1.0,
      "nodes": [
        {
          "node_id": "NODE1",
          "phase": "R",
          "measured_voltage": 245.0,
          "corrected_voltage": 229.5,
          "measured_power_active": 10.0,
          "corrected_power_active": 8.0,
          "voltage_score": 0.97,
          "power_penalty": 0.80,
          "bonus": 1.0,
          "node_score": 0.94,
          "reference_corrected_voltage": 229.5
        }
      ]
    }
  ]
}
```

### How scoring works

Scoring operates in one of two modes per timestamp, depending on whether reference solutions exist.

#### Mode 1: Reference-based scoring (when `VoltageControlSolutions` exist)

The system computes the mean absolute error (MAE) between the submitted corrected voltages and the reference optimal voltages:

```
voltage_MAE = mean(|submitted_voltage - reference_voltage|)   across matched nodes
```

**If voltage MAE ≤ 1.0 V (tolerance):**
```
timestamp_score = effort_factor
```
The voltage correction is considered successful — only effort efficiency matters.

**If voltage MAE > 1.0 V:**
```
voltage_factor = 1 / (1 + (MAE / 1.0)²)
timestamp_score = voltage_factor × effort_factor
```
A penalty is applied proportional to how far the submitted voltages are from optimal.

#### Mode 2: Outcome-only fallback (no reference solutions)

Each node is scored individually based on how much the violation improved:

```
voltage_score = (before_deviation - after_deviation) / (before_deviation + ε)    clamped to [-1, 1]
power_penalty = 1 - min(1, |ΔP| / |P_original|)
bonus = 1.0 if the node was in violation and is now within band, else 0.0

node_score = 0.7 × max(voltage_score, 0) + 0.2 × power_penalty + 0.1 × bonus
timestamp_score = mean(node_scores) × effort_factor
```

#### Effort factor (both modes)

The effort factor penalises large total power adjustments:

```
effort_norm = Σ|ΔP| / (Σ|P_original| + ε)
effort_factor = 1 / (1 + effort_norm / 0.15)
```

At 15% relative total adjustment, the effort factor is 0.5. At 0% adjustment, it is 1.0. This encourages minimal corrective action — a solution that fixes voltages with small power changes scores higher than one that uses brute-force large adjustments.

#### Overall score

```
overall_score = Σ(timestamp_score × nodes_in_timestamp) / total_nodes
```

This is a node-weighted average across all timestamps.

---

## Database Logic

### Tables involved

#### `GridUsage`

| Column | Type | Description |
|--------|------|-------------|
| `grid_id` | TEXT PK | References the main `grids` table. |
| `voltage_control_train` | INTEGER | `1` if this grid provides training snapshots. |
| `voltage_control_test` | INTEGER | `1` if this grid provides test snapshots. |

#### `Measurements`

The source of all snapshot data. The benchmark selects snapshots (distinct `grid_id, datetime` pairs) where at least one node has a voltage outside the specified threshold.

#### `VoltageControlSolutions`

Stores reference optimal solutions (pre-computed or uploaded separately). Not every snapshot has a solution.

| Column | Type | Constraint |
|--------|------|------------|
| `solution_id` | BIGSERIAL | PK |
| `grid_id` | TEXT | FK → `grids`, indexed with `datetime` |
| `datetime` | TIMESTAMP | |
| `node_id` | TEXT | FK → `HistoricalNodes` (composite with `grid_id`) |
| `phase` | TEXT | CHECK IN (`R`, `S`, `T`) |
| `corrected_voltage` | DOUBLE PRECISION | NOT NULL |
| `adjusted_power_active` | DOUBLE PRECISION | |
| `adjusted_power_reactive` | DOUBLE PRECISION | |
| `created_at` | TIMESTAMP | Auto-set |

An index on `(grid_id, datetime)` enables fast lookup of solutions per snapshot.

#### `VoltageTimestampMapping`

Maps each `(grid_id, datetime)` snapshot to a persistent anonymised UUID. Created on-demand when test data is first downloaded.

| Column | Type | Constraint |
|--------|------|------------|
| `grid_id` | TEXT | PK (composite), FK → `grids` |
| `datetime` | TIMESTAMP | PK (composite) |
| `anonymised_key` | TEXT | UNIQUE |

#### `VCUserGuesses`

Stores submitted corrective actions as JSON strings.

| Column | Type | Constraint |
|--------|------|------------|
| `user_id` | TEXT | PK (composite) — this is the `guess_id` from the API |
| `grid_id` | TEXT | PK (composite), FK → `grids` |
| `anonymised_key` | TEXT | PK (composite), FK → `VoltageTimestampMapping` |
| `guessed_voltages` | TEXT | JSON: `{"node_id": {"phase": "R", "corrected_voltage": 229.5}}` |
| `guessed_loads` | TEXT | JSON: `{"node_id": {"adjusted_power_active": 8.0, ...}}` |
| `timestamp` | TIMESTAMP | Auto-set on insert/update |

### Data flow

```
GET /training-scenarios
  → Find snapshots: SELECT DISTINCT (grid_id, datetime) FROM Measurements
    WHERE voltage_magnitude > limit (overvoltages) or < limit (undervoltages)
    AND grid_id IN (GridUsage.voltage_control_train = 1)
  → For each snapshot, fetch all measurements at that timestamp
  → For each snapshot, fetch reference solutions from VoltageControlSolutions
  → Compute hardness metrics per snapshot
  → Filter snapshots by difficulty quantile
  → Return measurements + solutions + metrics

GET /voltage-control-data
  → Same snapshot selection for test grids (voltage_control_test = 1)
  → Same hardness computation and difficulty filtering
  → CREATE/LOAD VoltageTimestampMapping UUIDs
  → Return measurements under anonymised keys (solutions hidden)

POST /submit-results
  → Validate grid exists
  → Validate all anonymised keys exist in VoltageTimestampMapping
  → UPSERT guessed_voltages and guessed_loads as JSON into VCUserGuesses

GET /score
  → JOIN VCUserGuesses WITH VoltageTimestampMapping to recover (grid_id, datetime)
  → For each timestamp:
    → Fetch original measurements from Measurements
    → Fetch reference solutions from VoltageControlSolutions (if any)
    → Compare submitted corrections against reference (or compute outcome-only score)
    → Apply effort penalty
  → Aggregate to overall_score
```

### Grid complexity metrics

The hardness computation also factors in grid topology complexity, queried from the `Node` and `Connection` tables:

```
complexity_raw = 0.60 × log(1 + n_nodes) + 0.40 × log(1 + n_connections)
complexity_norm = complexity_raw / (1 + complexity_raw)     ∈ [0, 1)
```

This is cached per grid within a single request to avoid redundant queries.
