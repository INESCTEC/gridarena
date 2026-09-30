# State Agent

## Overview

The State Agent provides the State Estimation Benchmark. The goal is to predict missing voltage values (magnitude and angle) at nodes that are not fully observed, using the measurements that are available and knowledge of how power flows through the network.

This is a regression problem grounded in power system physics: voltage at unobserved nodes is not random — it is constrained by Kirchhoff's laws and the grid topology. Good algorithms exploit this structure.

**Typical use case:** A grid operator has smart meters at some nodes but not all. State estimation fills in the missing voltage picture across the full network.

---

## Functions

### get_training_state_data

Use this when you want to develop or train a state estimation algorithm, access fully observable data where all node voltages are known, or understand what the input/output relationship looks like before attempting predictions.

**Parameters:**
- `noise_difficulty` (string, optional, default=`"clean"`): Controls measurement noise. `"clean"` provides ideal readings; `"noisy"` simulates realistic sensor noise.
- `observability` (string, optional, default=`"medium"`): Controls how many nodes have visible measurements. `"low"` means fewer observed nodes; `"high"` means most nodes are observed.

**Returns:** Full time-series measurements for all nodes including voltage magnitude and angle — no masking.

**How to interpret:**
- Use this to learn the relationship between observed nodes and unobserved nodes
- Voltage magnitude is typically around 230V; significant deviations indicate load stress or generation
- Voltage angle propagates through the network according to power injection and impedance

**Example:**
```json
{
  "noise_difficulty": "clean",
  "observability": "medium"
}
```

---

### get_state_estimation_input

Use this when you want to run your state estimation algorithm on the actual test case. Some node voltages are masked — you must predict them.

**Parameters:**
- `user_id` (string, required): Your user identifier
- `noise_difficulty` (string, optional, default=`"clean"`): Should match the difficulty used in training
- `observability` (string, optional, default=`"medium"`): Controls the fraction of nodes that are masked

**Returns:** Time-series measurements where some nodes have voltage values hidden. The response also contains an `estimation_id` used for submission.

**How to interpret:**
- Nodes with missing values are the ones you must estimate
- Use the observed nodes and your knowledge of grid topology to infer the missing voltages
- The `estimation_id` in the response must be included when submitting results

**Example:**
```json
{
  "user_id": "user_001",
  "noise_difficulty": "clean",
  "observability": "medium"
}
```

---

### submit_state_estimates

Use this when you want to submit your predicted voltage values for the masked nodes.

**Parameters:**
- `user_id` (string, required): Your user identifier
- `estimation_id` (string, required): The ID returned by `get_state_estimation_input`
- `grid_id` (string, required): The grid the estimation is for
- `timestamp` (string, required): The specific timestamp being estimated (ISO 8601)
- `estimates` (array, required): List of predictions, one per masked node, each containing `masked_node_id`, `voltage_magnitude`, and `voltage_angle`

**Returns:** Confirmation of submission.

**Notes:**
- Every masked node must have a prediction — partial submissions are rejected
- `voltage_magnitude` should be in volts (e.g. 229.5), not per unit
- `voltage_angle` should be in degrees

**Example:**
```json
{
  "user_id": "user_001",
  "estimation_id": "est_001",
  "grid_id": "grid001",
  "timestamp": "2025-07-01T12:00:00",
  "estimates": [
    {
      "masked_node_id": "node_3",
      "voltage_magnitude": 229.5,
      "voltage_angle": -5.2
    },
    {
      "masked_node_id": "node_7",
      "voltage_magnitude": 227.1,
      "voltage_angle": -6.8
    }
  ]
}
```

---

### get_state_estimation_score

Use this when you want to evaluate how accurate your voltage predictions were.

**Parameters:**
- `user_id` (string, required): Your user identifier
- `estimation_id` (string, required): The ID used when submitting predictions

**Returns:** Error score for the submission.

**How to interpret:**
- The score represents prediction error (e.g. Mean Absolute Error or RMSE) — **lower is better**
- A score near 0 means your estimates closely matched the true voltages
- High error on voltage angle typically indicates the algorithm is not accounting for power flow direction
- High error on voltage magnitude typically means the algorithm is not capturing load-driven voltage drops along the feeder

**Example:**
```json
{
  "user_id": "user_001",
  "estimation_id": "est_001"
}
```