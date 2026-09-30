# Topology Agent

## Overview

The Topology Agent provides the Topology Discovery Benchmark. The goal is to reconstruct the physical electrical connections (edges) between nodes using only smart meter time-series data — without access to the actual wiring diagram.

This is a graph reconstruction problem: given measurements at each node, infer which nodes are directly connected by a cable. The benchmark provides labelled training data (with known connections), unlabelled test data, and an accuracy scoring endpoint.

**Typical use case:** An engineer wants to verify or recover the network topology of a grid where wiring documentation is incomplete or unreliable.

---

## Functions

### get_training_topology_data

Use this when you want to train a topology discovery algorithm, see examples of what the correct connection graph looks like, or understand the relationship between measurements and physical connections.

**Parameters:**
- `difficulty` (string, optional, default=`"clean"`): Controls measurement noise. `"clean"` provides ideal data; `"noisy"` simulates realistic smart meter noise.

**Returns:** Time-series measurements per node along with the correct edge list (the true topology).

**How to interpret:**
- Each edge represents a physical cable between two nodes
- Nodes that are directly connected tend to have strongly correlated voltage and power patterns
- The reference node "PT" (transformer) is always connected to at least one other node

**Example:**
```json
{
  "difficulty": "clean"
}
```

---

### get_topology_discovery_data

Use this when you want the actual test data to run predictions on. The correct connections are hidden — you must infer the topology from the measurements alone.

**Parameters:**
- `difficulty` (string, optional, default=`"clean"`): Use the same difficulty as training for a valid comparison.

**Returns:** Time-series measurements per node without the true edge list.

**How to interpret:**
- Same structure as training data but without the topology labels
- Use your algorithm to infer which node pairs are connected
- Submit your predicted edge list using `submit_topology_guesses`

**Example:**
```json
{
  "difficulty": "noisy"
}
```

---

### submit_topology_guesses

Use this when you want to submit your predicted network connections and get them evaluated.

**Parameters:**
- `guess_id` (string, required): A unique identifier for this submission (e.g. `"run_001"`)
- `grid_id` (string, required): The grid the predictions are for
- `guesses` (array, required): A list of node-pair arrays representing predicted edges. Each element is a two-integer array `[node_a, node_b]`.

**Returns:** Confirmation of submission.

**Notes:**
- Each element of `guesses` is a two-element array `[node_a, node_b]` representing a predicted cable between those two nodes
- Use the same `guess_id` when retrieving the score
- Do not submit duplicate edges

**Example:**
```json
{
  "guess_id": "run_001",
  "grid_id": "grid001",
  "guesses": [
    [0, 1],
    [1, 2],
    [2, 3],
    [3, 4]
  ]
}
```

---

### get_topology_score

Use this when you want to evaluate how accurately your algorithm reconstructed the grid topology.

**Parameters:**
- `guess_id` (string, required): The ID used when submitting predictions
- `grid_id` (string, required): The grid the submission was for

**Returns:** Accuracy metrics for the submission.

**How to interpret:**
- `accuracy`: ratio of correctly predicted edges to total true edges. 1.0 is a perfect match.
- `missed`: edges that exist in the real grid but were not predicted — cables your model failed to detect
- `incorrect_extra`: edges you predicted that don't actually exist in the grid — phantom connections
- A good model maximises accuracy while minimising both missed and incorrect_extra counts

**Example:**
```json
{
  "guess_id": "run_001",
  "grid_id": "grid001"
}
```