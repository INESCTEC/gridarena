# Powerflow Agent

## Overview

The Powerflow Agent runs Newton-Raphson power flow simulations on a registered grid using historical measurements as power injections and the grid topology as the network constraint. It computes complex voltages (magnitude and angle) at every node for each timestamp, for a selected phase.

Use this agent to get voltage profiles under real or simulated load conditions, to detect voltage violations, or to understand how power flows through the network.

**Prerequisites:** The grid must be registered (Grid Agent) and historical data must be uploaded (Historical Agent) before running a power flow.

---

## Functions

### run_power_flow

Use this when you want to simulate the electrical state of the grid, compute voltages at all nodes, or check for voltage violations under a specific load profile. This triggers the simulation — it does not return results directly.

**Parameters:**
- `grid_id` (string, required): The grid to simulate
- `phase` (string, required): Which phase to simulate — `"R"`, `"S"`, or `"T"`
- `start_time` (string, optional): Start of the simulation window (ISO 8601, e.g. `"2025-07-01T00:00:00"`)
- `end_time` (string, optional): End of the simulation window (ISO 8601)

**Returns:** Confirmation that the simulation was triggered.

**Notes:**
- The simulation runs per timestamp within the time window
- If no time range is given, all available historical data is used
- Run this before calling `get_power_flow_results`

**Example:**
```json
{
  "grid_id": "grid001",
  "phase": "R",
  "start_time": "2025-07-01T00:00:00",
  "end_time": "2025-07-01T01:00:00"
}
```

---

### get_power_flow_results

Use this when you want to retrieve computed voltages after running a simulation, check if any node has an undervoltage or overvoltage violation, or analyse the voltage profile across the grid.

**Parameters:**
- `grid_id` (string, required): The grid whose results to retrieve
- `phase` (string, required): The phase to retrieve results for — `"R"`, `"S"`, or `"T"`

**Returns:** Per-node, per-timestamp voltage results.

**How to interpret:**
- `voltage.real` and `voltage.imag`: components of the complex voltage phasor at each node
- Voltage magnitude = sqrt(real² + imag²), expressed in volts
- Nominal voltage for a low-voltage grid is 230V (1.0 per unit)
- **Acceptable range:** 0.9 to 1.1 per unit (207V to 253V)
- Below 0.90 pu → undervoltage violation (typical cause: heavy load or EV charging)
- Above 1.1 pu → overvoltage violation (typical cause: solar PV generation exceeding local consumption)
- Node "PT" is the reference node and is always at nominal voltage (1.0 pu)
- Nodes far from the transformer (PT) tend to have more pronounced voltage deviations

**Example:**
```json
{
  "grid_id": "grid001",
  "phase": "R"
}
```