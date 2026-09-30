# Phase Agent

## Overview

The Phase Agent provides the Phase Identification Benchmark. The goal is to determine which phase (R, S, or T) each node in the grid belongs to, using only smart meter time-series data.

This is a classification problem: each node must be assigned to exactly one of three phases. The benchmark provides labelled training data (with known phases) and unlabelled test data (phases hidden). You submit predictions and receive an accuracy score.

**Typical use case:** An engineer or algorithm wants to identify the phase assignment of nodes in a grid where the wiring is poorly documented.

---

## Functions

### get_training_phase_data

Use this when you want to train or test a phase identification algorithm, get labelled examples of what phase each node belongs to, or understand what the input data looks like before attempting predictions.

**Parameters:**
- `difficulty` (string, optional, default=`"clean"`): Controls the noise level in the measurements. Use `"clean"` for noise-free data, `"noisy"` for realistic sensor noise.

**Returns:** Time-series measurements per node with known phase labels (R, S, or T) included.

**How to interpret:**
- Each record contains node measurements and the correct phase label
- Use this data to train a classifier or develop heuristics
- Nodes on the same phase tend to have correlated power and voltage patterns

**Example:**
```json
{
  "difficulty": "clean"
}
```

---

### get_phase_identification_data

Use this when you want to get the actual test data to run predictions on. Phase labels are hidden — you must predict them.

**Parameters:**
- `difficulty` (string, optional, default=`"clean"`): Same difficulty options as training data. Use the same difficulty level for a fair comparison.

**Returns:** Time-series measurements per node without phase labels.

**How to interpret:**
- Same structure as training data but without the phase label field
- Feed these measurements into your model and produce a guess for each node_id
- Submit predictions using `submit_phase_guesses`

**Example:**
```json
{
  "difficulty": "clean"
}
```

---

### submit_phase_guesses

Use this when you want to submit your predicted phase assignments and get them evaluated.

**Parameters:**
- `guess_id` (string, required): A unique identifier for this submission run (e.g. `"run_001"`)
- `grid_id` (string, required): The grid the predictions are for
- `guesses` (object, required): A mapping of node_id → predicted phase. Each value must be `"R"`, `"S"`, or `"T"`.

**Returns:** Confirmation of submission.

**Notes:**
- Every node in the test set must have a prediction — partial submissions are not valid
- Use the same `guess_id` when retrieving the score

**Example:**
```json
{
  "guess_id": "run_001",
  "grid_id": "grid001",
  "guesses": {
    "node_1": "R",
    "node_2": "S",
    "node_3": "T",
    "node_4": "R"
  }
}
```

---

### get_phase_score

Use this when you want to see how accurate your phase predictions were.

**Parameters:**
- `guess_id` (string, required): The ID used when submitting predictions
- `grid_id` (string, required): The grid the submission was for

**Returns:** Accuracy score for the submission.

**How to interpret:**
- Accuracy = number of correctly predicted nodes / total nodes
- Score of 1.0 means every node was assigned the correct phase
- Random guessing gives approximately 0.33 (one-in-three chance per node)
- A score below 0.33 suggests the predictions are worse than random — check your data preprocessing

**Example:**
```json
{
  "guess_id": "run_001",
  "grid_id": "grid001"
}
```