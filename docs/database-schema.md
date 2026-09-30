# Data Model

gridarena uses PostgreSQL. Every table is created idempotently at first use via
`CREATE TABLE IF NOT EXISTS` in `gridarena/database/create_*.py` — there is no
separate migration tool. This page summarizes the tables grouped by domain;
see the linked source file for exact column definitions.

Unless noted otherwise, deleting a `grids` row (`DELETE FROM grids WHERE
grid_id = ...`, e.g. via `DELETE /grid/{grid_id}`) cascades through every
table below that references it.

## Grid topology

Source: `gridarena/database/create_grid_database.py`

| Table | Key | Purpose |
|---|---|---|
| `grids` | `grid_id` (PK) | Catalog of registered LV grid IDs. Every other grid-scoped table has a `grid_id` foreign key back to this table, `ON DELETE CASCADE`. |
| `Node` | (`NodeId`, `grid_id`) | A grid's nodes, with optional lat/lon coordinates. |
| `Cable` | (`CableId`, `grid_id`) | Cable/conductor types (per-phase impedance and nominal current) available to a grid. |
| `Connection` | (`ConnectionId`, `grid_id`) | Edges between two `Node`s, referencing a `Cable` type and a length. |
| `GridUsage` | `grid_id` (PK) | Per-benchmark train/test flags for a grid (phase detection, topology detection, state estimation, voltage control). |

```text
grids ──┬──< Node ──┬──< Connection >── Cable
        │           └── (FromNodeId/ToNodeId reference Node)
        └──< GridUsage
```

## MV grids

Source: `gridarena/database/create_mv_database.py`

| Table | Key | Purpose |
|---|---|---|
| `MVGrid` | `mv_grid_id` (PK) | Catalog of registered MV grids (name, nominal voltage, region). |
| `MVNode` | (`NodeId`, `mv_grid_id`) | An MV grid's nodes. |
| `MVCable` | (`CableId`, `mv_grid_id`) | MV cable types. |
| `MVConnection` | (`ConnectionId`, `mv_grid_id`) | Edges between `MVNode`s. |
| `MVConnectionPoint` | (`ConnectionPointId`, `mv_grid_id`) | A point on the MV grid where an LV grid can be connected via a transformer. |
| `MVTransformer` | (`TransformerId`, `mv_grid_id`) | An MV/LV transformer at a connection point. `lv_grid_id` references `grids(grid_id)` **`ON DELETE SET NULL`** — deleting the downstream LV grid unlinks the transformer rather than deleting it. |

## Measurements and historical data

Two independent, differently-scoped systems:

**Node/grid-scoped measurements** — source: `create_measurements_database.py`

| Table | Key | Purpose |
|---|---|---|
| `HistoricalNodes` | (`node_id`, `grid_id`) | Links a node to a grid for measurement purposes. |
| `Measurements` | `measurement_id` (PK) | Timestamped power/voltage measurements for a `HistoricalNodes` entry, optionally per-phase. |

**Standalone historical series** (not tied to any grid or node) — source:
`create_historical_database.py`

| Table | Key | Purpose |
|---|---|---|
| `HistoricalDatabase` | `database_id` (PK) | A named collection of series sharing one timeline. |
| `HistoricalTimestamp` | (`database_id`, `datetime`) | The shared timeline every series in a database must use. |
| `HistoricalSeries` | (`database_id`, `series_id`) | A single series (`grid_level` ∈ `MV`/`LV`/`Feeder`). |
| `HistoricalRecords` | `record_id` (PK) | Power and/or voltage values for a series at a timestamp/phase. |

## Power flow

Source: `create_pf_database.py`

| Table | Key | Purpose |
|---|---|---|
| `PowerFlowResults` | (`grid_id`, `node_id`, `phase`, `datetime`) | Computed voltage (real/imaginary) per node/phase/timestamp for a grid. |

## Digital Twin

Source: `create_digital_twin_database.py`

| Table | Key | Purpose |
|---|---|---|
| `DigitalTwin` | `digital_twin_id` (PK) | A twin's configuration: source, field mapping, power-flow config, status, last run/error, and its most recent measurement batch. |
| `DigitalTwinEvent` | `event_id` (PK) | Append-only event log for a twin (e.g. fetch/publish/error events). |
| `DigitalTwinResult` | `result_id` (PK) | Per-run comparison metrics (voltage MAE/RMSE, power error, convergence status) between the twin's power flow and observed data. |

## Offline Scenarios

Source: `create_offline_scenario_database.py`

| Table | Key | Purpose |
|---|---|---|
| `OfflineScenario` | `scenario_id` (PK) | A replay-based (non-live) scenario derived from a digital twin (`source_dt_id`), with a modified grid snapshot / connection changes / power limits. |
| `OfflineScenarioResult` | `result_id` (PK) | Per-timestamp simulation result for a scenario. |

## PF Data Generation

Source: `create_pf_datagen_database.py`

Bulk power-flow scenario output tables, keyed by an opaque `run_id` with **no**
foreign key back to any run-metadata table — run configuration/status instead
lives in `run_config.json` under `gridarena/pf_datagen/runs/<run_id>/` (see
[Architecture › Background job subsystems](architecture.md#background-job-subsystems)).

| Table | Purpose |
|---|---|
| `MVPFScenarioBus` | Per-node results (`pd`, `qd`, `vm`, `va`, bus type) for one scenario. |
| `MVPFScenarioBranch` | Per-connection results (flows, impedance, thermal rating/violation) for one scenario. |
| `MVPFScenarioYbus` | Y-bus matrix entries for one scenario. |
| `MVPFScenarioRuntime` | Solve time and convergence status for one scenario. |

## Benchmarks

Each benchmark keeps its true labels hidden from participants behind an
anonymised-key mapping; guesses are matched against that mapping, never
against raw node IDs, to compute a score.

**Phase Identification** — `create_anon_mapping_database.py`,
`create_phase_guesses_database.py`

| Table | Key | Purpose |
|---|---|---|
| `AnonymisedMapping` | (`grid_id`, `node_id`, `phase`) | Maps a real `(node_id, phase)` pair to a persistent random `anonymised_key`. The true `phase` is the label being guessed. |
| `UserGuesses` | (`guess_id`, `grid_id`, `anonymised_key`) | A user's guessed phase for an anonymised key. |

**Topology Discovery** — `create_topology_guesses_database.py`

| Table | Key | Purpose |
|---|---|---|
| `TopologyUserGuesses` | (`user_id`, `grid_id`) | A user's guessed topology (edge list) for a grid, as a single submission. |

**State Estimation** — `create_se_database.py`

| Table | Key | Purpose |
|---|---|---|
| `GridMask` | `grid_id` (PK) | Maps a grid to an opaque `masked_id`. |
| `NodeMask` | (`grid_id`, `node_id`, `phase`) | Maps a real node/phase to an opaque `masked_node_id`. |
| `EstimationTasks` | (`user_id`, `estimation_id`, `grid_id`, `node_id`, `phase`, `timestamp`) | The known/unknown split for one estimation task, generated per user (see [State Estimation Benchmark](api/state-estimation-benchmark.md) for the idempotent-per-user contract). |
| `StateEstimates` | (`user_id`, `estimation_id`, `grid_id`, `timestamp`, `node_id`, `phase`) | A user's submitted voltage magnitude/angle estimate for a task. |

**Voltage Control** — `create_voltage_timestamp_map_table.py`,
`create_vc_guesses_database.py`, `vc_solutions.py`

| Table | Key | Purpose |
|---|---|---|
| `VoltageTimestampMapping` | (`grid_id`, `datetime`) | Maps a real `(grid_id, datetime)` snapshot to a persistent `anonymised_key`. |
| `VCUserGuesses` | (`user_id`, `grid_id`, `anonymised_key`) | A user's guessed voltages/loads for an anonymised snapshot. |
| `VoltageControlSolutions` | `solution_id` (PK) | Reference solutions (corrected voltage, adjusted P/Q) for a grid snapshot, used to score submissions. |

!!! note "Ordering matters"
    `VCUserGuesses` references `VoltageTimestampMapping` via foreign key, so
    the latter must be created first — `_ensure_benchmark_tables()` in
    `gridarena/app.py` creates them in that order.
