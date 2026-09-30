# GridArena

**GridArena** is a simulation and analytics API for
low-voltage (LV) electrical distribution grids. It lets users upload or define grid
topologies, execute power flow simulations under various operating conditions, and
access historical simulation results for further analysis or forecasting. The
platform also supports synthetic data generation, live digital twins, reinforcement
learning, and a suite of anonymised AI benchmarks (phase identification, topology
discovery, state estimation, and voltage control).

It is developed by INESC TEC (Centro de Produção de Energia e Sistemas — CPES) as
part of the **AI-EFFECT** project.

<p align="center">
  <img src="assets/aieffect-log.png" alt="AI-EFFECT logo" width="260">
</p>

## What gridarena does

- **Grid management** — register LV and MV grid topologies (nodes, cables,
  connections), inspect them, and connect LV grids to MV feeders.
- **Measurements & historical data** — upload node/grid-scoped time-series
  measurements, or standalone historical power/voltage series not tied to any grid.
- **Power flow simulation** — run backward/forward-sweep power flow for a
  registered grid and inspect voltage magnitude/angle results over time.
- **Synthetic data generation** — train diffusion models on real measurements to
  synthesize realistic node-level time series, or generate bulk power-flow training
  scenarios for an MV grid (gridfm-datakit–inspired).
- **Digital twins** — mirror a registered LV grid against a live external data
  source with a periodic fetch → map → publish → consume → power-flow → compare
  loop.
- **Reinforcement learning** — train and evaluate RL agents against grid
  environments.
- **AI benchmark suite** — download anonymised, difficulty-controlled data,
  submit predictions, and retrieve reproducible scores for four benchmark tasks:
  Phase Identification, Topology Discovery, State Estimation, and Voltage Control.
- **LLM chat assistant** — a retrieval-augmented chat interface over the platform's
  own documentation and data.

## Where to go next

<div class="grid cards" markdown>

- **[Getting Started](getting-started.md)**
  Install dependencies, configure the database, and run the app locally.

- **[Architecture](architecture.md)**
  How the FastAPI app, database layer, background workers, and UI fit together.

- **[Data Model](database-schema.md)**
  The core PostgreSQL tables behind grids, measurements, and benchmarks.

- **[API Reference](api/index.md)**
  Every router, endpoint, request/response shape, and error case.

</div>

## Project status

This is an active research/development platform, not yet a tagged stable release.
See the [Changelog](changelog.md) for what's changed, and
[Contributing](contributing.md) if you'd like to get involved.

## License

gridarena is released under the [MIT License](license.md).
