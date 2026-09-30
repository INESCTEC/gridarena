# PF Data Generation

Endpoints for bulk-generating MV power-flow scenarios (per-bus, per-branch,
Y-bus, and solve-runtime results) from a historical database's load
series, optionally with topology and admittance perturbations. Runs as a
background job — see
[Architecture › Background job subsystems](../architecture.md#background-job-subsystems)
for the shared `run_id` / `queued`→`running`→`completed`/`failed` /
`runs/<run_id>/` pattern also used by [RL](rl.md) and
[Diffusion Models](diffusion.md). Output rows land in the `MVPFScenario*`
tables — see [Data Model › PF Data Generation](../database-schema.md#pf-data-generation).

**Base path:** `/pf-datagen`

This router is JSON-API only — it has no `/ui` page of its own. The
feature is driven entirely from the MV grid detail page
(`/mv_grid/ui/{mv_grid_id}`), whose JavaScript calls these endpoints
directly.

!!! warning "`run_id` is not format-validated before use"
    Unlike [RL](rl.md) and [Diffusion Models](diffusion.md), whose run
    registries re-validate `run_id` against a `^[0-9a-f]{8}$` regex before
    building any filesystem path, `PFDataGenRunRegistry.get_run()` builds
    `RUNS_DIR / run_id / "run_config.json"` directly from the path
    parameter with no such check. In practice `run_id` only ever reaches
    the registry as a path segment matched by FastAPI's routing, but this
    router does not carry the same defense-in-depth the other two do.

## Endpoints

### `POST /pf-datagen/mv/{mv_grid_id}/run`

Starts a PF data-generation run for an MV grid: draws `scenario_count`
timesteps from a historical database as bus injections, optionally
perturbs topology/admittances, and solves power flow for each resulting
scenario.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `mv_grid_id` | string | The MV grid to generate scenarios for. |

**Request body**

```json
{
  "historical_database_id": "hist001",
  "reassignment_period_timesteps": 100,
  "scenario_count": 1000,
  "load_noise_sigma": 0.0,
  "topology_perturbation": { "type": "none", "k": 1, "n_variants": 10 },
  "admittance_perturbation": { "enabled": false, "sigma": 0.2 },
  "chunk_commit_size": 100,
  "seed": null
}
```

`historical_database_id` (see [Historical](historical.md)) must have all
series sharing one `grid_level`, which determines how injections are
assigned to MV connection points. `topology_perturbation.type` is one of
`none`, `n_minus_k` (enumerated combinations of up to `k` simultaneous
branch outages, capped by `perturbation.MAX_N_MINUS_K_COMBOS`), or
`random` (`n_variants` random topology draws). `seed` is a base RNG seed;
omit it for a fresh random seed (logged in the run's metrics).

**Response** `200`

```json
{
  "run_id": "d4e5f6a7",
  "status": "queued",
  "message": "PF data-generation run started for MV grid 'mv001'."
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | `mv_grid_id` doesn't reference an existing MV grid. |
| `422` | Request body fails schema validation (e.g. `scenario_count` out of `1`-`200000`). |

---

### `GET /pf-datagen/mv/{mv_grid_id}/runs`

Lists PF data-generation runs for one MV grid, most recently created
first.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `mv_grid_id` | string | The MV grid to list runs for. |

**Response** `200`

```json
[
  {
    "run_id": "d4e5f6a7",
    "mv_grid_id": "mv001",
    "status": "completed",
    "created_at": "2026-08-27T09:00:00+00:00",
    "completed_at": "2026-08-27T09:12:00+00:00",
    "error": null,
    "config": { "historical_database_id": "hist001", "scenario_count": 1000 },
    "total_scenarios": 1000,
    "completed_scenarios": 1000,
    "failed_scenarios": 0,
    "n_topology_variants": 1,
    "seed_used": 42,
    "metrics": null
  }
]
```

Returns an empty list, not `404`, for an `mv_grid_id` that doesn't exist.

---

### `GET /pf-datagen/runs`

Lists PF data-generation runs across every MV grid, most recently created
first — backs the "PF Data Generation" tab on the MV grids home page.

**Response** `200`

Same array shape as [`GET /pf-datagen/mv/{mv_grid_id}/runs`](#get-pf-datagenmvmv_grid_idruns),
unfiltered.

---

### `GET /pf-datagen/runs/{run_id}`

Returns one run's status. For a `completed` run, also includes a
`summary` of convergence and thermal-violation counts computed from the
stored result rows.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `run_id` | string | The run to fetch. |

**Response** `200`

```json
{
  "run_id": "d4e5f6a7",
  "mv_grid_id": "mv001",
  "status": "completed",
  "created_at": "2026-08-27T09:00:00+00:00",
  "completed_at": "2026-08-27T09:12:00+00:00",
  "error": null,
  "config": { "historical_database_id": "hist001", "scenario_count": 1000 },
  "total_scenarios": 1000,
  "completed_scenarios": 1000,
  "failed_scenarios": 0,
  "n_topology_variants": 1,
  "seed_used": 42,
  "metrics": null,
  "summary": {
    "total_output_groups": 1000,
    "converged": 987,
    "thermal_violations": 12
  }
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No run with this ID exists. |

---

### `GET /pf-datagen/runs/{run_id}/results`

Returns a page of raw result rows from one of the run's four output
tables.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `run_id` | string | The run to fetch results for. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `table` | `"bus"` \| `"branch"` \| `"ybus"` \| `"runtime"` | yes | — | Which output table to read. |
| `limit` | integer | no | `500` | Max rows to return (1-5000). |
| `offset` | integer | no | `0` | Row offset for pagination. |

**Response** `200`

```json
{
  "run_id": "d4e5f6a7",
  "table": "bus",
  "columns": ["scenario_id", "bus_id", "pd", "qd", "vm", "va", "bus_type"],
  "rows": [["s0001", "B1", 0.12, 0.03, 1.01, -0.4, "PQ"]]
}
```

`columns`/`rows` mirror the underlying `MVPFScenario*` table for the
requested `table` (see
[Data Model › PF Data Generation](../database-schema.md#pf-data-generation)).

**Errors**

| Status | Cause |
|---|---|
| `404` | No run with this ID exists. |
| `400` | The results query failed (response `detail` is generic; specifics are logged server-side). |

---

### `GET /pf-datagen/runs/{run_id}/export.csv`

Streams every row of one output table for a run as a CSV file download.
Unlike `/results`, this is not paginated — it returns the full table for
the run.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `run_id` | string | The run to export results for. |

**Query parameters**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `table` | `"bus"` \| `"branch"` \| `"ybus"` \| `"runtime"` | yes | — | Which output table to export. |

**Response** `200`

`text/csv` body with `Content-Disposition: attachment; filename="pf_datagen_<run_id>_<table>.csv"`.

**Errors**

| Status | Cause |
|---|---|
| `404` | No run with this ID exists. |
| `400` | The export query failed (response `detail` is generic; specifics are logged server-side). |
