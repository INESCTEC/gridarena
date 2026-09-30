# Diffusion Models

Endpoints for training diffusion-based generative models on a grid's
historical power data, auditing their privacy properties (membership
inference + canary memorisation), searching for the best number of
training epochs, and generating synthetic daily power snapshots from a
trained model. Training, privacy checks, and epoch search all run as
background jobs — see
[Architecture › Background job subsystems](../architecture.md#background-job-subsystems)
for the shared `run_id` / `queued`→`running`→`completed`/`failed` /
`runs/<run_id>/` pattern also used by [RL](rl.md) and
[PF Data Generation](pf-datagen.md).

**Base path:** `/diffusion`

Also serves a browser UI at `/diffusion/ui` and `/diffusion/ui/{run_id}`.

!!! note "`run_id` format is validated before touching the filesystem"
    `run_id`s are always server-generated as `uuid.uuid4().hex[:8]` (8 lowercase
    hex characters). Every lookup that turns a `run_id` into a directory path
    (`get_run`, `get_run_dir`) re-checks it against that pattern first, as
    defense-in-depth against path traversal — a malformed `run_id` behaves as
    "not found" rather than reaching the filesystem. The one exception is
    `GET /diffusion/runs/{run_id}/figure/{name}`, which builds its path via
    `get_run_dir()` directly without first calling `get_run()`; the regex
    check still runs (inside `get_run_dir`), but on a mismatch it raises an
    unhandled `ValueError`, surfacing as a generic `500` instead of a clean
    `404`.

## Endpoints

### `POST /diffusion/train`

Starts a diffusion model training job for one or more grids' historical
power data.

**Request body**

```json
{
  "grid_ids": ["grid001"],
  "phase": null,
  "start": null,
  "end": null,
  "p_min": null,
  "p_max": null,
  "architecture": "axial",
  "num_epochs": 75,
  "train_batch_size": 16,
  "learning_rate": 0.0001,
  "lr_warmup_steps": 500,
  "gradient_accumulation_steps": 1,
  "mixed_precision": "no",
  "power_subtract": "auto",
  "power_rescale": "auto",
  "device": "cpu",
  "dp_enabled": false,
  "dp_max_grad_norm": 1.0,
  "dp_noise_multiplier": 1.0,
  "dp_target_delta": 0.00001
}
```

`grid_ids` requires at least one entry. `architecture` selects the
node-mixing backbone: `axial` (attention, recommended), `deepsets`
(pooling, cheapest), `gnn` (graph message passing), or `unet2d` (legacy 2D
conv — requires an even, /8-divisible node count). `power_subtract` /
`power_rescale` accept either the literal string `"auto"` (computed from
the training data) or a fixed float. Setting `dp_enabled: true` trains
with DP-SGD using `dp_max_grad_norm` / `dp_noise_multiplier` /
`dp_target_delta`.

**Response** `200`

```json
{
  "run_id": "a1b2c3d4",
  "status": "queued",
  "message": "Diffusion training started for grids ['grid001'] (axial, 75 epochs)."
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | One of `grid_ids` doesn't reference an existing grid. |
| `422` | Request body fails schema validation (e.g. empty `grid_ids`, `num_epochs` out of `1`-`1000`). |

---

### `POST /diffusion/privacy-check`

Starts an empirical privacy audit: trains a model on a held-out split with
synthetic "canary" days injected, then measures membership-inference AUC
and canary memorisation. The audited model is diagnostic only and is
**not** the same artifact as a `/train` run — it must not be shipped.

**Request body**

All `DiffusionTrainRequest` fields (see `/train` above) plus:

```json
{
  "grid_ids": ["grid001"],
  "architecture": "axial",
  "val_frac": 0.2,
  "buffer_days": 7,
  "num_canaries": 5,
  "mi_num_timestep_samples": 20,
  "num_generated_samples": 128,
  "canary_inference_steps": 250
}
```

`val_frac` is the fraction of days held out as non-members; `buffer_days`
are discarded between the train/held-out split; `num_canaries` (1-50)
synthetic canary days are injected into training.

**Response** `200`

```json
{
  "run_id": "b2c3d4e5",
  "status": "queued",
  "message": "Privacy check started for grids ['grid001'] (axial)."
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | One of `grid_ids` doesn't reference an existing grid. |
| `422` | Request body fails schema validation. |

---

### `POST /diffusion/epoch-search`

Starts an epoch-selection sweep: trains once up to `max_epochs`, scores
the model against a held-out split at checkpoints every
`checkpoint_interval` epochs, and reports (and saves as the run's model)
the checkpoint with the best composite validation score.

**Request body**

All `DiffusionTrainRequest` fields (see `/train` above) plus:

```json
{
  "grid_ids": ["grid001"],
  "architecture": "axial",
  "max_epochs": 75,
  "checkpoint_interval": 10,
  "val_frac": 0.2,
  "buffer_days": 7,
  "sweep_inference_steps": 100
}
```

**Response** `200`

```json
{
  "run_id": "c3d4e5f6",
  "status": "queued",
  "message": "Epoch search started for grids ['grid001'] (axial, up to 75 epochs)."
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | One of `grid_ids` doesn't reference an existing grid. |
| `422` | Request body fails schema validation. |

---

### `GET /diffusion/runs`

Lists every diffusion job (train, privacy check, and epoch search runs
together), most recently created first.

**Response** `200`

```json
[
  {
    "run_id": "a1b2c3d4",
    "grid_ids": ["grid001"],
    "status": "completed",
    "created_at": "2026-08-27T09:00:00+00:00",
    "completed_at": "2026-08-27T09:42:00+00:00",
    "num_epochs": 75,
    "error": null,
    "metrics": { "final_loss": 0.031 },
    "dataset_size": 365,
    "job_type": "train",
    "architecture": "axial"
  }
]
```

`job_type` is `"train"`, `"privacy_check"`, or `"epoch_search"`. For
`epoch_search` runs, `num_epochs` reflects `max_epochs` rather than
`num_epochs`.

---

### `GET /diffusion/runs/{run_id}`

Returns one diffusion job's status.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `run_id` | string | The job's run ID. |

**Response** `200`

Same shape as one entry of [`GET /diffusion/runs`](#get-diffusionruns).

**Errors**

| Status | Cause |
|---|---|
| `404` | No run with this ID exists (including a malformed/never-issued `run_id`). |

---

### `GET /diffusion/runs/{run_id}/model`

Downloads a completed train/epoch-search run's trained model as a zip
file (`application/zip`). Not available for `privacy_check` runs.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `run_id` | string | The job's run ID. |

**Response** `200`

Binary `application/zip` body, filename `diffusion_model_<run_id>.zip`.

**Errors**

| Status | Cause |
|---|---|
| `404` | Run doesn't exist, hasn't completed, is a `privacy_check` run, or its model zip isn't on disk. |

---

### `GET /diffusion/runs/{run_id}/privacy-report`

Returns the full `privacy_report.json` written by a completed
`privacy_check` run.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `run_id` | string | The job's run ID. |

**Response** `200`

```json
{
  "architecture": "axial",
  "num_epochs": 75,
  "val_frac": 0.2,
  "buffer_days": 7,
  "num_train_days": 292,
  "num_val_days": 73,
  "num_canaries": 5,
  "warning": "This model's training set included synthetic canaries injected for this audit. It was NOT saved and must not be used as a production artifact — use a normal training run for the model you ship.",
  "membership_inference": {
    "method": "Loss-threshold attack: per-day denoising MSE averaged over a fixed grid of timesteps and a fixed noise seed. Attack score = -loss. AUC is P(a random member scores higher than a random non-member).",
    "mi_num_timestep_samples": 20,
    "auc": 0.53,
    "auc_ci_95": [0.47, 0.59],
    "pass_threshold": 0.55,
    "passed": true,
    "note": "With few held-out days the CI is wide — treat the interval as the result.",
    "member_loss_mean": 0.031,
    "nonmember_loss_mean": 0.033
  },
  "canary_memorisation": {
    "method": "For each canary and each natural held-out day, the nearest-neighbour Euclidean distance to a freshly generated batch is computed. A canary is flagged as memorised if its distance falls below the natural-day 5th percentile.",
    "num_generated_samples": 128,
    "canary_inference_steps": 250,
    "natural_nn_distance_p5": 1.42,
    "natural_nn_distance_mean": 2.10,
    "canary_nn_distances": [1.8, 2.3, 1.9, 2.5, 2.1],
    "canaries_below_p5": [false, false, false, false, false],
    "passed": true
  },
  "overall_passed": true,
  "figures": ["mi_loss_distributions.png", "canary_nn_distances.png"]
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No run with this ID exists. |
| `404` | `privacy_report.json` doesn't exist yet in the run directory (job hasn't completed, isn't a `privacy_check` job, or failed before writing it). |

---

### `GET /diffusion/runs/{run_id}/epoch-report`

Returns the full `epoch_search_report.json` written by a completed
`epoch_search` run.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `run_id` | string | The job's run ID. |

**Response** `200`

```json
{
  "architecture": "axial",
  "max_epochs_trained": 75,
  "checkpoint_interval": 10,
  "sweep_inference_steps": 100,
  "val_frac": 0.2,
  "buffer_days": 7,
  "num_train_days": 292,
  "num_val_days": 73,
  "methodology": "Each checkpoint's composite_score is the unweighted mean of its five validation metrics, each normalised by that metric's max across the sweep (lower is better). Sweep checkpoints use sweep_inference_steps for speed; the winner is re-scored at full inference steps and saved as the run's model.",
  "history": [
    { "epoch": 10, "train_loss": 0.09, "temporal_frobenius": 4.1, "spatial_frobenius": 3.2, "acf_mae": 0.08, "mean_mae": 0.11, "std_mae": 0.06, "composite_score": 0.83 },
    { "epoch": 20, "train_loss": 0.05, "temporal_frobenius": 3.0, "spatial_frobenius": 2.4, "acf_mae": 0.05, "mean_mae": 0.07, "std_mae": 0.04, "composite_score": 0.61 }
  ],
  "best_epoch": 70,
  "best_epoch_final_metrics": { "temporal_frobenius": 2.1, "spatial_frobenius": 1.8, "acf_mae": 0.03, "mean_mae": 0.04, "std_mae": 0.02 },
  "figures": ["metrics_vs_epoch.png"]
}
```

**Errors**

| Status | Cause |
|---|---|
| `404` | No run with this ID exists. |
| `404` | `epoch_search_report.json` doesn't exist yet in the run directory. |

---

### `GET /diffusion/runs/{run_id}/figure/{name}`

Downloads one of a run's report figures as a PNG image.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `run_id` | string | The job's run ID. |
| `name` | string | Figure filename — must be one of `mi_loss_distributions.png`, `canary_nn_distances.png`, `metrics_vs_epoch.png`. |

**Response** `200`

Binary `image/png` body.

**Errors**

| Status | Cause |
|---|---|
| `404` | `name` isn't one of the three whitelisted figure filenames. |
| `404` | The figure file doesn't exist in the run directory (report hasn't been generated for this job type). |
| `500` | (unhandled) `run_id` doesn't match the server-generated `[0-9a-f]{8}` format — this endpoint doesn't call `get_run()` first, so this case isn't caught into a clean `404`. |

---

### `POST /diffusion/generate/{run_id}`

Generates a single synthetic daily power snapshot from a completed
train/epoch-search run's model.

**Path parameters**

| Name | Type | Description |
|---|---|---|
| `run_id` | string | The job's run ID. |

**Request body** (optional)

```json
{ "num_inference_steps": 1000, "device": "cpu" }
```

`num_inference_steps` must be between 10 and 2000. The body may be omitted
entirely to use the defaults.

**Response** `200`

```json
{
  "architecture": "axial",
  "n_nodes": 25,
  "n_timesteps": 48,
  "snapshot": [[0.12, 0.15, "..."], ["..."]],
  "summary": { "mean": 0.14, "std": 0.05, "min": -0.02, "max": 0.41 }
}
```

`snapshot` is the full `(n_nodes, n_timesteps)` generated power matrix.

**Errors**

| Status | Cause |
|---|---|
| `400` | Run doesn't exist, hasn't completed, or is a `privacy_check` run (no generatable model). |
| `500` | Generation failed (response `detail` is generic; specifics are logged server-side). |
