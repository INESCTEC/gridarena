# Topology Discovery Benchmark

## Overview

The Topology Discovery benchmark tests the ability to reconstruct the physical wiring of a low-voltage grid — which nodes are connected to which — using only smart-meter time-series data. The true connection list (topology) is hidden; the algorithm must infer it from voltage and power patterns.

The benchmark follows a four-step pipeline:

1. **Download training data** — measurements with true topology visible.
2. **Download test data** — measurements with topology hidden and grid IDs anonymised.
3. **Submit predictions** — a list of predicted edges as node-index pairs.
4. **Retrieve score** — edge-level accuracy against the hidden ground truth.

---

## Prerequisites

A grid must be registered with historical measurements and marked for topology detection in the `GridUsage` table (`topology_detection_train = 1` and/or `topology_detection_test = 1`).

---

## Step 1: Download Training Data

**Endpoint:** `GET /topology_discovery_benchmark/training-topology-data`

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `difficulty` | `clean`, `easy`, `medium`, `hard` | `clean` | Controls noise applied to measurements. |

### What is returned

The response includes measurements, a node-to-index mapping, and the true topology (as index pairs), for every grid marked `topology_detection_train = 1`.

```json
{
  "difficulty": "clean",
  "profile": { ... },
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
        }
      ]
    }
  },
  "node to corresponding index": {
    "grid_001": {
      "PT": 0,
      "NODE1": 1,
      "NODE2": 2,
      "NODE3": 3
    }
  },
  "topology (index)": {
    "grid_001": [
      [0, 1],
      [1, 2],
      [2, 3]
    ]
  },
  "conn_data": {
    "grid_001": [
      ["TypeLine00001", 1000.0],
      ["TypeLine00001", 800.0],
      ["TypeLine00001", 600.0]
    ]
  }
}
```

**Key points:**
- `"node to corresponding index"` maps each node ID to an integer index. The reference node `PT` is always index 0.
- `"topology (index)"` is the ground truth — a list of `[from_index, to_index]` pairs representing physical connections.
- `"conn_data"` provides `(cable_id, length_metres)` for each connection in the same order as the topology list.
- Measurements include the true `phase` label and real `node_id`.
- Noise is applied according to the difficulty profile (see Phase Identification tutorial for the noise table). The RNG is seeded with `SHA-256(grid_id:node_id:phase:difficulty)` for reproducibility.

---

## Step 2: Download Test Data

**Endpoint:** `GET /topology_discovery_benchmark/topology-data`

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `difficulty` | `clean`, `easy`, `medium`, `hard` | `clean` | Controls noise applied to measurements. |

### What is returned

The response contains measurements from grids marked `topology_detection_test = 1`. The real `grid_id` is replaced with a persistent anonymised UUID. The topology and connection data are not included — that is what you must predict.

```json
{
  "difficulty": "clean",
  "profile": { ... },
  "grids": {
    "b8c1d4e5-9f2a-4b3c-a1d2-7e8f9a0b1c2d": {
      "NODE1": [
        {
          "datetime": "2025-07-01T00:00:00",
          "power_active": 10.0,
          "power_reactive": 5.0,
          "voltage_magnitude": 230.0,
          "voltage_angle": 0.1,
          "phase": "R"
        }
      ],
      "NODE2": [ ... ]
    }
  }
}
```

**Key points:**
- The grid ID is anonymised (`b8c1d4e5-...` instead of `grid_001`). This mapping is persistent — the same grid always gets the same anonymised key.
- Node IDs and phase labels are **not** anonymised (unlike the phase benchmark). You see the real node names.
- The topology (connection list) is **not** returned — reconstructing it is the task.
- The same noise profile and deterministic seeding apply.

---

## Step 3: Submit Predictions

**Endpoint:** `POST /topology_discovery_benchmark/submit-results`

**Content-Type:** `application/json`

### Request body

```json
{
  "guess_id": "alice_v1",
  "grid_id": "b8c1d4e5-9f2a-4b3c-a1d2-7e8f9a0b1c2d",
  "guesses": [
    [0, 1],
    [1, 2],
    [2, 3]
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `guess_id` | string | yes | Identifies this submission. Different values keep separate attempts. |
| `grid_id` | string | yes | The grid ID — can be the anonymised key or the real grid ID. |
| `guesses` | array of `[int, int]` | yes | Predicted edges as pairs of node indices. Indices correspond to the mapping from `"node to corresponding index"` in the training data. |

### Grid ID resolution

The endpoint accepts either the anonymised grid key or the real grid ID. If an anonymised key is provided, it is resolved to the real grid ID via the `GridAnonymisedMapping` table before storage.

### Validation

- The grid must exist in the `grids` table (HTTP 422 if not).
- Resubmitting with the same `(guess_id, grid_id)` overwrites the previous guess entirely.

### Response

```json
{
  "status": "submitted",
  "accepted_edges": 3
}
```

### What the user uploads via the UI

The prediction **file** needs only the `guesses` array (the list of edge pairs):

```json
{
  "guesses": [
    [0, 1],
    [1, 2],
    [2, 3]
  ]
}
```

The `guess_id` and `grid_id` are taken from the form fields and added by the JavaScript.

---

## Step 4: Retrieve Score

**Endpoint:** `GET /topology_discovery_benchmark/score`

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `guess_id` | string | yes | The submission identifier. |
| `grid_id` | string | yes | The grid ID (anonymised or real). |

### Response

```json
{
  "guess_id": "alice_v1",
  "grid_id": "b8c1d4e5-...",
  "total_true_edges": 3,
  "guessed_edges": 3,
  "correct": 2,
  "incorrect_extra": 1,
  "missed": 1,
  "accuracy": 0.6667
}
```

### How scoring works

Edges are compared as unordered pairs. Each edge `[u, v]` is normalised to `(min(u,v), max(u,v))` before comparison.

| Metric | Definition |
|--------|------------|
| `correct` | Edges present in both the guess and the ground truth. |
| `incorrect_extra` | Edges in the guess that do not exist in the ground truth. |
| `missed` | Edges in the ground truth that were not guessed. |
| `accuracy` | `correct / total_true_edges` |

Extra edges are reported but do not penalise the accuracy score directly — accuracy only measures recall. However, the `incorrect_extra` count lets you evaluate precision separately.

---

## Database Logic

### Tables involved

#### `GridUsage`

| Column | Type | Description |
|--------|------|-------------|
| `grid_id` | TEXT PK | References the main `grids` table. |
| `topology_detection_train` | INTEGER | `1` if this grid provides training data. |
| `topology_detection_test` | INTEGER | `1` if this grid provides test data. |

#### `Measurements`

Same table as the phase benchmark. Supplies the time-series data for both training and testing.

#### `Node`

Stores node definitions per grid.

| Column | Type |
|--------|------|
| `NodeId` | TEXT |
| `grid_id` | TEXT |
| `coord_lat` | FLOAT |
| `coord_lon` | FLOAT |

#### `Connection`

Stores the true wiring (ground truth for scoring).

| Column | Type |
|--------|------|
| `ConnectionId` | TEXT |
| `grid_id` | TEXT |
| `FromNodeId` | TEXT |
| `ToNodeId` | TEXT |
| `CableId` | TEXT |
| `Length` | FLOAT |

#### `GridAnonymisedMapping`

Maps real grid IDs to anonymised UUIDs. Created on-demand when test data is first downloaded.

| Column | Type | Constraint |
|--------|------|------------|
| `grid_id` | TEXT | PK |
| `anonymised_grid_key` | TEXT | UNIQUE, NOT NULL |

#### `TopologyUserGuesses`

Stores submitted topology predictions.

| Column | Type | Constraint |
|--------|------|------------|
| `user_id` | TEXT | PK (composite) — this is the `guess_id` from the API |
| `grid_id` | TEXT | PK (composite), FK → `grids` |
| `guessed_topology` | TEXT | JSON string of `[[from, to], ...]` |
| `timestamp` | TIMESTAMP | Auto-set on insert/update |

### Data flow

```
GET /training-topology-data
  → SELECT FROM Measurements WHERE grid_id IN (GridUsage.topology_detection_train = 1)
  → SELECT FROM Node, Connection for node-to-index mapping and edge list
  → Apply seeded noise to measurements
  → Return measurements + topology + conn_data (everything visible)

GET /topology-data
  → SELECT FROM Measurements WHERE grid_id IN (GridUsage.topology_detection_test = 1)
  → CREATE/LOAD GridAnonymisedMapping UUIDs for each grid_id
  → Apply seeded noise to measurements
  → Return measurements under anonymised grid IDs (topology hidden)

POST /submit-results
  → Resolve anonymised grid_id to real grid_id via GridAnonymisedMapping
  → Validate grid exists
  → UPSERT guessed_topology as JSON into TopologyUserGuesses

GET /score
  → Resolve anonymised grid_id if needed
  → SELECT guessed_topology FROM TopologyUserGuesses
  → SELECT true edges FROM Connection (via Node index mapping)
  → Compare edge sets: correct, extra, missed
  → Return accuracy = correct / total_true_edges
```

### Node index assignment

Node indices are built by querying all nodes for a grid from the `Node` table. The reference node `PT` is always assigned index 0. Remaining nodes keep their query order. The same index assignment is used in training (visible to the user) and scoring (used to interpret the submitted edge list).
