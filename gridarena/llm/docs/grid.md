# Grid Agent

## Overview

The Grid Agent manages the electrical network model — the topology that describes how nodes (buses) are physically connected via cables and lines. A grid must be registered before any other operation: you cannot upload measurements, run power flow, or run benchmarks without a grid in the system.

A grid consists of:
- **Nodes**: physical locations or buses (the reference node is always called "PT")
- **Connections**: edges between nodes (cable segments)
- **Cables**: electrical parameters for each segment (impedance, nominal current ratings)

**Always use this agent first.** The full workflow is: register grid → upload historical data → run power flow or benchmark.

---

## Typical Workflow

1. Register a grid from a JSON file (Grid Agent)
2. Upload time-series measurements (Historical Agent)
3. Run power flow simulations (Powerflow Agent)
4. Analyze voltages, run benchmarks, or apply voltage control

---

## Functions

### Registering a grid

There is no tool for this — the assistant cannot upload or register files on the user's
behalf. To register a new grid, the user must upload it themselves, either through the
grid page in the web UI or by calling `POST /grid/` directly with the grid JSON file
(node definitions, connections, and cable parameters), optionally setting
`phase_detection`, `topology_detection`, `voltage_control`, and `state_estimation`. A grid
must be registered this way before uploading historical data or running any simulation or
benchmark.

---

### get_grid_data

Use this when you want to inspect what a grid looks like, list all nodes, check cable parameters, or view connections between nodes. Useful for debugging, exploration, or verifying a grid was registered correctly.

**Parameters:**
- `grid_id` (string, required): The ID of the grid to query
- `table` (string, required): One of `"Node"`, `"Connection"`, `"Cable"`, `"grids"`

**Returns:** Records from the selected table.

**How to interpret:**
- `Node` records: physical bus locations with coordinates (lat/lon). Node "PT" is always the reference node (transformer primary) at nominal voltage.
- `Connection` records: edges between nodes with cable length in meters. These define the physical layout of the network.
- `Cable` records: electrical impedance values per phase (R/S/T) and nominal current ratings. Impedance (real + imaginary) is used in power flow calculations.
- `grids` table: lists all registered grid IDs in the system.

**Example:**
```json
{
  "grid_id": "grid001",
  "table": "Node"
}
```

---

### delete_grid

Use this when you want to remove a grid entirely from the system. This is irreversible — it deletes the grid definition, all associated historical measurements, and all simulation results.

**Parameters:**
- `grid_id` (string, required): The ID of the grid to delete

**Returns:** Confirmation message.

**Notes:**
- Cannot be undone. All data tied to this grid_id is permanently removed.
- Use with caution in production environments.

**Example:**
```json
{
  "grid_id": "grid001"
}
```