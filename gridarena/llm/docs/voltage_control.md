# Voltage Agent

## Overview

The Voltage Agent provides the Voltage Control Benchmark. The goal is to propose corrective actions — adjustments to active power, reactive power, or voltage setpoints — that bring voltages back within acceptable limits when violations are detected.

**Voltage violation types:**
- **Overvoltage** (above 1.1 pu / 253V): typically caused by excess solar PV generation injecting power back into the grid
- **Undervoltage** (below 0.9 pu / 207V): typically caused by heavy loads such as EV charging or industrial demand

This is an optimisation problem: find the minimum corrective intervention that resolves all violations. The benchmark provides training scenarios with reference solutions, test scenarios where you must propose actions, and a scoring endpoint.

---

## Functions

### get_training_voltage_control_data

Use this when you want to develop or train a voltage control algorithm, understand what reference solutions look like, or study how specific violations are corrected in practice.

**Parameters:**
- `voltage_limit` (float, required): The voltage threshold (in volts) used to define a violation, e.g. `230.0`
- `scenario` (string, optional, default=`"Overvoltages"`): The type of violation to train on. Use `"Overvoltages"` for solar-driven high voltage, `"Undervoltages"` for load-driven low voltage.
- `difficulty` (string, optional, default=`"clean"`): Controls measurement noise level

**Returns:** Scenarios including voltage measurements, violation details, and reference corrective actions.

**How to interpret:**
- Each scenario shows a snapshot of the grid under stress with one or more nodes outside the acceptable voltage range
- Reference actions show what power adjustments were applied to resolve each violation
- Use these to train or validate your control strategy before running on test data

**Example:**
```json
{
  "voltage_limit": 230.0,
  "scenario": "Overvoltages",
  "difficulty": "clean"
}
```

---

### get_voltage_control_data

Use this when you want to get the actual test scenarios to run your control algorithm on. Reference solutions are hidden.

**Parameters:**
- `voltage_limit` (float, required): Same voltage limit used in training for consistency
- `scenario` (string, optional, default=`"Overvoltages"`): The violation type to test on
- `difficulty` (string, optional, default=`"clean"`): Use the same difficulty as training

**Returns:** Voltage snapshots with violations but without reference solutions. Node identifiers are anonymised.

**How to interpret:**
- Identify which nodes are in violation by comparing voltage magnitudes against the limit
- Propose corrective actions per node: adjust active power (curtail generation or shed load), reactive power, or voltage setpoints
- Preserve the anonymised node keys exactly when submitting — do not rename them

**Example:**
```json
{
  "voltage_limit": 230.0,
  "scenario": "Overvoltages",
  "difficulty": "clean"
}
```

---

### submit_voltage_control_guesses

Use this when you want to submit your proposed corrective actions and get them evaluated.

**Parameters:**
- `guess_id` (string, required): A unique identifier for this submission (e.g. `"run_001"`)
- `grid_id` (string, required): The grid the submission is for
- `guesses` (object, required): A mapping of anonymised scenario keys to arrays of corrective actions. Each action contains `node_id`, `phase`, `corrected_voltage`, `adjusted_power_active`, and `adjusted_power_reactive`.

**Returns:** Confirmation of submission.

**Notes:**
- Anonymised keys from the test data must be preserved exactly as returned — do not rename them
- All fields per action are required — partial actions are rejected
- Use the same `guess_id` when retrieving the score

**Example:**
```json
{
  "guess_id": "run_001",
  "grid_id": "grid001",
  "guesses": {
    "anon_key_1": [
      {
        "node_id": "N1",
        "phase": "R",
        "corrected_voltage": 230.0,
        "adjusted_power_active": 5.0,
        "adjusted_power_reactive": 1.2
      },
      {
        "node_id": "N3",
        "phase": "R",
        "corrected_voltage": 229.5,
        "adjusted_power_active": 3.0,
        "adjusted_power_reactive": 0.8
      }
    ],
    "anon_key_2": [
      {
        "node_id": "N5",
        "phase": "S",
        "corrected_voltage": 231.0,
        "adjusted_power_active": -2.0,
        "adjusted_power_reactive": 0.5
      }
    ]
  }
}
```

---

### get_voltage_control_score

Use this when you want to evaluate how well your corrective actions resolved the voltage violations.

**Parameters:**
- `guess_id` (string, required): The ID used when submitting actions
- `grid_id` (string, required): The grid the submission was for

**Returns:** Performance score.

**How to interpret:**
- Higher score = better performance
- The score rewards resolving all violations while minimising the magnitude of interventions — large curtailments or load shedding are penalised
- A perfect solution resolves every violation with the smallest possible power adjustment
- If your score is low despite resolving violations, check whether your interventions are proportional to the violation severity

**Example:**
```json
{
  "guess_id": "run_001",
  "grid_id": "grid001"
}
```