# Reinforcement Learning

Endpoints for training reinforcement-learning voltage-control agents
(PPO, single- or multi-agent) against a grid's topology, downloading the
trained model, and running a one-step before/after evaluation. Training
runs as a background job — see
[Architecture › Background job subsystems](../architecture.md#background-job-subsystems)
for the shared `run_id` / `queued`→`running`→`completed`/`failed` /
`runs/<run_id>/` pattern also used by [Diffusion Models](diffusion.md) and
[PF Data Generation](pf-datagen.md).

**Base path:** `/rl`

Also serves a browser UI at `/rl/ui` and `/rl/ui/{run_id}`.

!!! note "`run_id` format is validated before touching the filesystem"
    Like [Diffusion Models](diffusion.md), `run_id`s are always
    server-generated as `uuid.uuid4().hex[:8]` (8 lowercase hex
    characters), and both `get_run()` and `get_run_dir()` in the run
    registry re-check that pattern before it's used to build a directory
    path — a malformed `run_id` behaves as "not found" rather than
    reaching the filesystem.

## Endpoints

### `POST /rl/train`

Starts a PPO training run for a grid's voltage-control environment.

**Request body**

```json
{
  "grid_id": "grid001",
  "agent_type": "single",
  "timesteps": 5000,
  "violation_threshold": 0.1,
  "reward_scale": 100.0,
  "p_min_kw": -20.0,
  "p_max_kw": 30.0,
  "volt_ref": 230.0,
  "admittance_scale": 1.0,
  "active_wrappers": ["ActionPenalty", "ObservationNoise"],
  "wrapper_config": {
    "action_penalty_weight": 0.5,
    "l1_penalty_weight": 10.0,
    "noise_level": 0.005,
    "power_balance_weight": 2.0,
    "unnecessary_act_weight": 1.0
  },
  "device": "cpu"
}
```

`agent_type` is `"single"` or `"multi"`. `timesteps` must be between 1,000
and 10,000,000. `active_wrappers` is a list drawn from `ActionPenalty`,
`L1ActionPenalty`, `ObservationNoise`, `PowerBalance`, `StablePenalty`;
`wrapper_config` supplies the weight/noise-level parameters for whichever
wrappers are active.

**Response** `200`

```json
{
  "run_id": "e5f6a7b8",
  "status": "queued",
  "message": "Training started for grid 'grid001' (single agent, 5000 timesteps)."
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | `grid_id` doesn't reference an existing grid. |
| `422` | Request body fails schema validation. |

---

### `GET /rl/runs`

Lists every RL training run, most recently created first.

**Response** `200`

```json
[
  {
    "run_id": "e5f6a7b8",
    "grid_id": "grid001",
    "agent_type": "single",
    "status": "completed",
    "created_at": "2026-08-27T09:00:00+00:00",
    "completed_at": "2026-08-27T09:20:00+00:00",
    "timesteps": 5000,
    "error": null,
    "metrics": { "mean_reward": 182.4 }
  }
]
```

---

### `GET /rl/runs/{run_id}`

Returns one training run's status.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `run_id` | string | The run to fetch. |

**Response** `200`

Same shape as one entry of [`GET /rl/runs`](#get-rlruns).

**Errors**

| Status | Cause |
|---|---|
| `404` | No run with this ID exists (including a malformed/never-issued `run_id`). |

---

### `GET /rl/runs/{run_id}/model`

Downloads a completed run's trained model as a zip file
(`application/zip`) — `ppo_grid.zip` for a `single`-agent run or
`ppo_multiagent.zip` for a `multi`-agent run.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `run_id` | string | The run to download the model for. |

**Response** `200`

Binary `application/zip` body.

**Errors**

| Status | Cause |
|---|---|
| `404` | Run doesn't exist or hasn't completed. |
| `404` | Neither `ppo_grid.zip` nor `ppo_multiagent.zip` exists in the run directory. |

---

### `POST /rl/evaluate/{run_id}`

Loads a completed run's trained model and runs one evaluation step,
returning a before/after comparison of node voltages and power for a
single simulated load scenario.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `run_id` | string | The completed run to evaluate. |

**Request body** (optional)

```json
{ "loads": [0.0, 3.2, 1.8, 4.5] }
```

`loads` is an optional list of per-node active power values (kW); if
provided, its length must equal the grid's node count, and index `0`
(the reference node) is forced to `0.0`. The body may be omitted entirely
to evaluate against the environment's default reset state.

**Response** `200`

```json
{
  "n_nodes": 4,
  "violations_before": 1,
  "violations_after": 0,
  "reward": 12.4,
  "nodes": [
    { "index": 0, "v_init_pu": 1.0, "v_final_pu": 1.0, "p_init_kw": 0.0, "p_final_kw": 0.0 },
    { "index": 1, "v_init_pu": 1.12, "v_final_pu": 1.03, "p_init_kw": 3.2, "p_final_kw": 1.8 }
  ]
}
```

**Errors**

| Status | Cause |
|---|---|
| `400` | Run doesn't exist or hasn't completed. |
| `500` | Evaluation failed — e.g. `loads` length doesn't match the grid's node count (response `detail` is generic; specifics are logged server-side). |
