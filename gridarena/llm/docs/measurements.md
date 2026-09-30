# Measurements Agent

## Overview

The Measurements Agent handles time-series measurement data: active power, reactive power, voltage magnitude, and voltage angle — recorded per node and per phase (R, S, or T) over time, for a specific registered grid.

This data is the **required input** for:
- Power flow simulations (Powerflow Agent)
- Phase identification benchmark (Phase Agent)
- State estimation benchmark (State Agent)
- Topology discovery benchmark (Topology Agent)

Use this agent after registering a grid and before running any simulation or benchmark. Without measurement data, the system has no readings to work with.

If you instead need a standalone power/voltage series that isn't tied to any specific grid or node, use the Historical Agent instead.

---

## Functions

### Uploading measurement data

There is no tool for this — the assistant cannot upload files on the user's behalf. To
inject sensor or smart meter data for a grid, the user must upload it themselves through
the measurements page in the web UI, or by calling `POST /measurements/` directly with a
JSON file containing node IDs, timestamps, phase labels, and measurement values. The grid
referenced in the file must already be registered via the Grid Agent.

---

### get_measurements_data

Use this when you want to retrieve voltage or power measurements from a grid, inspect what data exists for a specific node, filter measurements by time range or phase, or verify that uploaded data is correct.

**Parameters:**
- `grid_id` (string, required): The grid to query
- `node_id` (string, optional): Filter results to a specific node
- `start` (string, optional): Start of time range (ISO 8601 format, e.g. `"2025-07-01T00:00:00"`)
- `end` (string, optional): End of time range (ISO 8601 format)
- `per_phase` (boolean, optional, default=true): If true, returns separate records per phase
- `phase` (string, optional): Filter to a single phase — `"R"`, `"S"`, or `"T"`

**Returns:** Measurement records matching the filters.

**How to interpret:**
- `power_active`: real power in watts — positive means load consumption, negative means generation (e.g. solar panels injecting power)
- `power_reactive`: reactive power in VAR — indicates inductive or capacitive load behaviour
- `voltage_magnitude`: RMS voltage at the node, typically around 230V for a healthy low-voltage grid. Values below 218.5V (0.95 pu) indicate undervoltage; values above 241.5V (1.05 pu) indicate overvoltage.
- `voltage_angle`: phase angle in degrees, used in power flow equations to compute current direction and magnitude

**Example:**
```json
{
  "grid_id": "grid001",
  "node_id": "N2",
  "start": "2025-07-01T00:00:00",
  "end": "2025-07-01T01:00:00",
  "per_phase": true,
  "phase": "R"
}
```

---

### delete_measurements

Use this when you want to remove bad or corrupted sensor data, clear a specific time window of measurements, or delete data for a specific node or phase before re-uploading corrected data.

**Parameters:**
- `grid_id` (string, required): The grid whose data to delete
- `node_id` (string, optional): Limit deletion to a specific node
- `phase` (string, optional): Limit deletion to a specific phase (`"R"`, `"S"`, or `"T"`)
- `start` (string, optional): Start of time range to delete
- `end` (string, optional): End of time range to delete

**Returns:** Confirmation message.

**Notes:**
- Omitting optional filters deletes all measurements for the grid — use with caution
- This operation is irreversible

**Example:**
```json
{
  "grid_id": "grid001",
  "node_id": "N2",
  "phase": "R",
  "start": "2025-07-01T00:00:00",
  "end": "2025-07-01T01:00:00"
}
```
