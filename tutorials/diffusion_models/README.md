# Diffusion Model for Synthetic Power Data Generation

This document describes the diffusion model integrated into gridarena, its architecture, training pipeline, and the differential privacy mechanism that protects sensitive grid measurement data.

---

## 1. Purpose

The diffusion model generates **synthetic daily power snapshots** that are statistically similar to real historical grid measurements. Each snapshot is a matrix of shape `(n_nodes, n_daily_timesteps)` representing the active power at every node across one day.

Use cases:

- Augmenting small datasets for downstream tasks (state estimation, voltage control).
- Sharing realistic grid data without exposing actual measurements.
- Stress-testing algorithms against diverse load scenarios.

---

## 2. Model Architecture

The model is a **Denoising Diffusion Probabilistic Model (DDPM)**. You choose one of **four selectable backbones** via the `architecture` field when starting a run.

### 2.1 Selectable Architectures

| Value | Node-mixing | Node count | Notes |
|-------|-------------|-----------|-------|
| `axial` | Cross-node self-attention (no positional encoding) | any | **Recommended default.** Permutation-equivariant; learns pairwise node structure; needs no topology. |
| `deepsets` | Mean + max pooling → MLP | any | Cheapest. Each node sees only global summary statistics. |
| `gnn` | GCN message passing over an edge topology | any | Fully-connected graph by default (accepts a real adjacency). |
| `unet2d` | 2D convolution + spatial attention (diffusers `UNet2DModel`) | **even only** | Legacy. Requires an even node count (odd grids drop their last node). |

The three custom backbones (`axial`, `deepsets`, `gnn`) share a common 1-D **temporal** convolution U-Net (`architectures/temporal_blocks.py`) that:

- Downsamples only the **time** axis (W), never the **node** axis (H) — so they work for any number of nodes, unlike `unet2d`.
- Uses **circular padding** along the 48-slot day axis so the convolutions respect the cyclic day boundary.
- Injects the diffusion timestep `t` via a sinusoidal embedding + FiLM conditioning in every residual block.

```
Input: (batch, 1, n_nodes, n_timesteps)   ← single-channel "image" of power values
   │  temporal 1-D conv U-Net (time downsampled 2x per level; nodes preserved)
   │  + node-mixing (attention / pooling / graph conv) at every level
Output: (batch, 1, n_nodes, n_timesteps)  ← predicted noise
```

Only the **node-mixing** operator differs between the three; everything else (temporal convs, timestep conditioning, skip connections) is shared.

### 2.2 Noise Scheduler

- **Type**: DDPM (Denoising Diffusion Probabilistic Model)
- **Timesteps**: 1000 (forward noising steps)
- **Beta schedule**: `squaredcos_cap_v2` — cosine-based schedule that adds noise more gradually than linear, improving sample quality

### 2.3 Data Representation

Each training sample is a daily snapshot: a 2D matrix where rows are grid nodes and columns are measurement timestamps within a day.

Before training, power values are normalized:

```
p_norm = (p - power_subtract) / power_rescale
```

By default, `power_subtract` is the dataset mean and `power_rescale` is the dataset standard deviation (computed automatically). This centers the data near zero with unit variance, which is important for the diffusion process to work correctly.

If the number of nodes is odd, one node is dropped to ensure even spatial dimensions (required by the UNet's downsampling/upsampling path).

---

## 3. Training Pipeline

### 3.1 Data Flow

```
Database (Measurements table)
    │
    ▼
data_loader.py: load_power_data_from_db(require_even_nodes=...)
    → Queries by grid_ids, phase, time range, power range
    → Groups into daily snapshots: (n_days, n_nodes, n_daily_timesteps)
    → Drops last node only if odd AND architecture == "unet2d"
    │
    ▼
model_core.py: build_training_pipeline()
    → Creates HuggingFace Dataset directly from the daily snapshots
    → Applies normalization: p_norm = (p - mean) / std
    → Builds DataLoader (batch_size=16, shuffle=True)
    → build_model(config) dispatches on config.architecture
    → Initializes DDPMScheduler, AdamW optimizer, cosine warmup LR scheduler
    │
    ▼
model_core.py: train_diffusion_model()
    → Standard DDPM training loop (or DP-SGD variant)
    → Saves model weights + model_config.json to runs/{run_id}/model/
```

> The model trains **directly on the daily power snapshots** — there is no
> synthetic-grid / power-flow preprocessing step. (An earlier version generated a
> random grid and computed a voltage dataset that the trainer never used.)

### 3.2 Training Loop (Standard)

For each batch:

1. Sample clean power snapshots from the dataset
2. Sample random noise `ε ~ N(0, I)` and random timesteps `t ~ Uniform(0, 1000)`
3. Create noisy images: `x_t = √(ᾱ_t) · x_0 + √(1 - ᾱ_t) · ε`
4. Predict noise: `ε_θ = UNet(x_t, t)`
5. Compute loss: `L = MSE(ε_θ, ε)`
6. Backpropagate, clip gradients (norm 1.0), update weights

The model learns to predict the noise added at each timestep, which allows it to reverse the noising process during generation.

### 3.3 Sample Generation

After training, generating a new synthetic snapshot:

1. Start from pure noise: `x_T ~ N(0, I)` with shape `(1, 1, n_nodes, n_timesteps)`
2. For t = 1000, 999, ..., 1:
   - Predict noise: `ε_θ = UNet(x_t, t)`
   - Remove predicted noise: `x_{t-1} = scheduler.step(ε_θ, t, x_t)`
3. Denormalize: `p_phys = x_0 * power_rescale + power_subtract`
4. Return the `(n_nodes, n_timesteps)` power matrix

---

## 4. Differential Privacy

### 4.1 Why It Matters

The model trains on real power measurements from specific grids. Without privacy protection:

- The model can **memorize** individual daily profiles, especially with small datasets
- Generated samples may **reproduce** actual consumption patterns
- An attacker with access to the model could run **membership inference** attacks to determine whether a specific day's data was in the training set

This is particularly relevant for energy data, which can reveal occupancy patterns, industrial schedules, or equipment characteristics.

### 4.2 DP-SGD (Differentially Private Stochastic Gradient Descent)

When differential privacy is enabled, the training loop uses **DP-SGD** via the [Opacus](https://opacus.ai/) library. Three modifications are applied to the standard SGD process:

#### Per-Sample Gradient Clipping

Instead of computing one averaged gradient per batch, Opacus computes a **separate gradient for each training example**. Each per-sample gradient is then clipped to a maximum L2 norm:

```
g_i_clipped = g_i * min(1, C / ||g_i||₂)
```

where `C` is the `max_grad_norm` parameter. This bounds the maximum influence any single daily snapshot can have on a model update.

#### Calibrated Noise Addition

After clipping, Gaussian noise is added to the sum of clipped gradients:

```
g_noisy = (1/B) * (Σ g_i_clipped + N(0, σ²C²I))
```

where `σ` is the `noise_multiplier` parameter and `B` is the batch size. This noise masks the contribution of individual examples.

#### Privacy Accounting

Opacus tracks the cumulative privacy cost across all training steps using the **Rényi Differential Privacy (RDP)** accountant. After training, it reports the total **(ε, δ)** guarantee:

- **ε (epsilon)**: the privacy budget spent. Lower = more private.
- **δ (delta)**: the probability that the guarantee fails. Should be much smaller than 1/dataset_size.

The guarantee states: for any single daily snapshot in the training set, the probability distribution over model weights is nearly identical whether that snapshot was included or excluded.

### 4.3 Configuration Parameters

| Parameter | Default | Effect |
|-----------|---------|--------|
| `dp_enabled` | `false` | Toggle DP-SGD on/off |
| `dp_max_grad_norm` | `1.0` | Per-sample clipping bound (C). Lower = stronger privacy, slower learning |
| `dp_noise_multiplier` | `1.0` | Noise scale (σ). Higher = stronger privacy, noisier gradients |
| `dp_target_delta` | `1e-5` | Target δ for the (ε, δ)-DP guarantee |

### 4.4 Constraints When DP Is Enabled

- **Mixed precision is disabled**: Opacus requires full-precision (float32) gradients for correct per-sample clipping
- **Gradient accumulation is set to 1**: Opacus must see each physical batch to clip per-sample
- **Poisson sampling**: Opacus replaces the standard DataLoader with one that samples each example independently with probability `batch_size / dataset_size` (required for tight privacy accounting)
- **LR scheduler is skipped**: the wrapped optimizer doesn't support external LR scheduling
- **Training is ~2x slower**: per-sample gradient computation roughly doubles memory and compute per step

### 4.5 Interpreting the Privacy Report

After a DP-enabled run completes, the run detail page shows:

```
Epsilon (ε):         12.4
Delta (δ):           1.00e-05
Max Grad Norm:       1.0
Noise Multiplier:    1.0
```

**What epsilon means in practice:**

| ε range | Privacy level | Expected quality impact |
|---------|---------------|------------------------|
| < 1     | Strong        | Significant quality loss; needs much more data |
| 1 – 10  | Moderate      | Noticeable quality reduction; reasonable trade-off |
| 10 – 50 | Weak but formal | Mild impact; still protects against naive attacks |
| > 100   | Minimal       | Little practical protection |

For typical grid datasets (50–300 daily snapshots), expect ε in the 10–50 range with default parameters. To reduce ε: increase `noise_multiplier`, reduce `num_epochs`, or increase dataset size.

### 4.6 Privacy Metadata in Model Artifacts

When DP is used, the saved model includes privacy parameters in `model/grid_admittance.json`:

```json
{
  "differential_privacy": {
    "dp_epsilon": 12.4,
    "dp_delta": 1e-05,
    "dp_max_grad_norm": 1.0,
    "dp_noise_multiplier": 1.0
  }
}
```

This allows anyone receiving the model to verify what privacy guarantees were applied during training.

---

## 5. Privacy Check (empirical audit)

Differential privacy (Section 4) is a **preventive** guarantee applied during
training. The **Privacy Check** is the **empirical** counterpart: it measures
whether a trained model actually leaks its training data. It is the diffusion
equivalent of an attacker probing the model.

Starting a privacy check trains a **throwaway diagnostic model** — on a
held-out-aware split with a handful of synthetic "canary" days injected — and
runs two attacks against it. This audited model is **never saved** (it saw the
canaries) and cannot be downloaded or generated from; use a normal training run
for the model you ship.

### 5.1 Membership inference (loss-threshold attack)

For every day, the per-day denoising MSE is averaged over a fixed grid of
timesteps with a fixed noise draw (the training loss, made deterministic). A
lower loss means the model fits that day better, i.e. it is more likely to have
been a training member. The attack's **ROC AUC** is reported with a bootstrap
95% CI:

- **AUC ≈ 0.5** → the model is indistinguishable on members vs. held-out days (good).
- **AUC → 1.0** → members are clearly separable (leakage).
- **Pass bar:** AUC ≤ 0.55. With few held-out days the CI is wide — read the interval, not just the point.

### 5.2 Canary insertion test

A few structurally-distinctive synthetic days (double-spike patterns unlike any
real day) are injected into training. After training, a batch of samples is
generated and each canary's nearest-neighbour distance to that batch is compared
against the natural held-out days' distances. A canary whose distance falls
below the natural 5th percentile is **flagged as memorised** — the model
reproduces it as readily as real data.

The run detail page shows both results with pass/fail badges and two figures
(`mi_loss_distributions.png`, `canary_nn_distances.png`), and the full
`privacy_report.json` is served at `/diffusion/runs/{id}/privacy-report`.

---

## 6. Best-Epoch Search

Training too few epochs underfits; too many wastes compute and can overfit /
start memorising. The **epoch search** finds a good stopping point **without
training one model per candidate**:

1. Train **once** up to `max_epochs`.
2. At every `checkpoint_interval` epochs, generate samples and score them against
   a held-out temporal validation split using five distribution-distance metrics
   (temporal & spatial correlation Frobenius norms, ACF MAE, per-timestep mean &
   std MAE). Each checkpoint's model state is kept in memory.
3. The **composite score** for each checkpoint is the mean of the five metrics,
   each normalised by its max across the sweep (lower is better).
4. The best checkpoint is re-scored at full sampling fidelity, **saved as the
   run's model** (so you can download / generate from it), and a
   `metrics_vs_epoch.png` figure + `epoch_search_report.json` are produced.

The run detail page shows the winning epoch, its validation metrics, the
per-checkpoint table, and the metrics-vs-epoch figure.

---

## 7. Code Structure

All code lives under `gridarena/diffusion/`:

```
gridarena/diffusion/
  schemas.py        — configs + request/response models (incl. architecture,
                      privacy-check and epoch-search requests)
  architectures/    — the three custom backbones + shared temporal blocks:
      temporal_blocks.py  — shared 1-D temporal conv U-Net pieces
      deepsets_unet.py    — Deep Sets node mixing
      axial_unet.py       — cross-node attention node mixing (default)
      graph_unet.py       — GCN message passing node mixing
      topology.py         — edge_index for the GNN (fully-connected by default)
  data_loader.py    — load_power_data_from_db(): Measurements → daily snapshots
  model_core.py     — build_model() dispatch, DDPM training (standard + DP-SGD),
                      sampler, load/save, validation metrics
  job_common.py     — shared data-loading + config building for all three jobs
  training.py       — subprocess entry: normal training run
  privacy.py        — subprocess entry: empirical privacy audit (MI + canary)
  epoch_search.py   — subprocess entry: epoch-selection sweep
  run_manager.py    — background job management via ProcessPoolExecutor
  runs/             — each run stored as runs/{run_id}/ with:
                        run_config.json     — configuration + status + metrics
                        model/              — weights + model_config.json (train
                                              & epoch-search runs only)
                        diffusion_model.zip — archived model directory
                        *.png / *_report.json — privacy / epoch-search artifacts
```

API endpoints at `/diffusion/`:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/diffusion/train` | Start a training run (background) |
| POST | `/diffusion/privacy-check` | Start an empirical privacy audit |
| POST | `/diffusion/epoch-search` | Start an epoch-selection sweep |
| GET | `/diffusion/runs` | List all runs |
| GET | `/diffusion/runs/{id}` | Run status + metrics |
| GET | `/diffusion/runs/{id}/model` | Download model .zip (train / epoch-search) |
| GET | `/diffusion/runs/{id}/privacy-report` | Privacy audit report JSON |
| GET | `/diffusion/runs/{id}/epoch-report` | Epoch-search report JSON |
| GET | `/diffusion/runs/{id}/figure/{name}` | Report figure PNG |
| POST | `/diffusion/generate/{id}` | Generate one synthetic snapshot |

---

## 8. Quick Start

1. Upload a grid and historical measurements via the Grid and Historical UI pages
2. Navigate to **Diffusion Models** in the sidebar
3. Select one or more grids and an **architecture** (start with `axial`)
4. Set the number of epochs; optionally enable **Differential Privacy**
5. Click **Start Training** — the run executes in the background
6. Optionally, under **Diagnostics**, run a **Privacy Check** or a
   **Best-Epoch Search** on the same data and architecture
7. Once a training / epoch-search run completes, click **Generate Snapshot** to
   produce a synthetic daily power profile, or **Download Model** for offline use
