# API Reference — Overview

This section documents the JSON API exposed by each of gridarena's 15 FastAPI
routers. It's a handwritten companion to the auto-generated, always-accurate
[Swagger UI](../getting-started.md#interactive-api-documentation) — use these
pages for the workflow/context and Swagger for exact live schemas.

## Base URL and routing

Each router is mounted under a fixed path prefix in `gridarena/app.py`:

| Prefix | Router | OpenAPI tag |
|---|---|---|
| `/grid` | [Grid](grid.md) | Grid |
| `/mv_grid` | [MV Grid](mv-grid.md) | MV Grid |
| `/measurements` | [Measurements](measurements.md) | Measurements |
| `/historical` | [Historical](historical.md) | Historical |
| `/powerflow` | [Power Flow](powerflow.md) | Algorithm |
| `/phase_identification_benchmark` | [Phase Identification Benchmark](phase-identification-benchmark.md) | Phase Identification Benchmark |
| `/topology_discovery_benchmark` | [Topology Discovery Benchmark](topology-discovery-benchmark.md) | Topology Discovery Benchmark |
| `/state_estimation_benchmark` | [State Estimation Benchmark](state-estimation-benchmark.md) | State Estimation Benchmark |
| `/voltage_control_benchmark` | [Voltage Control Benchmark](voltage-control-benchmark.md) | Voltage Control Benchmark |
| `/digital-twins` | [Digital Twin](digital-twin.md) | Digital Twin |
| `/diffusion` | [Diffusion Models](diffusion.md) | Diffusion Models |
| `/pf-datagen` | [PF Data Generation](pf-datagen.md) | PF Data Generation |
| `/rl` | [Reinforcement Learning](rl.md) | Reinforcement Learning |
| `/chat` | [Chat](chat.md) | Chat |
| `/offline-scenarios` | [Offline Scenarios](offline-scenarios.md) | Offline Scenarios |

Requests and responses are JSON (`application/json`) except file uploads,
which use `multipart/form-data`.

## Authentication

There is currently **no authentication or authorization** — every endpoint is
open. `guess_id` / `user_id` fields used throughout the benchmark and
state-estimation endpoints are caller-supplied identifiers, not verified
credentials; they exist to let a single grid support multiple independent
participants, not to restrict access. Treat any deployment of this API
accordingly (e.g. put it behind a reverse proxy or VPN if it shouldn't be
publicly reachable).

If route-level API-key auth is added later, note that the [Chat](chat.md)
assistant's tool calls go through router functions **directly, in-process**,
never over HTTP — a route-level dependency would not cover that path, and the
WebSocket itself would need its own check (the document-assistant WebSocket
already has a minimal placeholder for this, gated on the `LVGPLAY_API_KEY`
env var; see chat.md).

## Error format

Errors follow FastAPI's standard shape:

```json
{ "detail": "Grid 'grid001' not found." }
```

or, for request-validation failures (HTTP 422, raised by Pydantic), a list of
per-field errors:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["query", "grid_id"],
      "msg": "Field required",
      "input": null
    }
  ]
}
```

| Status | Meaning |
|---|---|
| `200` | Success. |
| `400` | Malformed request (e.g. a required file was not attached). |
| `404` | The referenced resource (grid, run, digital twin, ...) doesn't exist. |
| `413` | An uploaded file exceeded the size limit (see below). |
| `422` | Request validation failed (bad JSON shape, out-of-range value, unknown key). |
| `500` | Unexpected server-side error. The response `detail` is a generic message; full details are logged server-side, not returned to the client. |

## Resource-safety limits

A few platform-wide limits apply across routers to bound worst-case request
cost:

| Limit | Value | Applies to |
|---|---|---|
| Upload size | 200 MB | Every file-upload endpoint (grid, MV grid, measurements, historical, chat custom-agent documents). Exceeding it returns `413`. |
| Row cap per request | 50,000 rows | `GET` endpoints that could otherwise return an entire table (historical records, measurements). Once the cap is hit, the response is truncated and includes `"truncated": true` plus a `"truncation_hint"` telling the caller to narrow the request with `start`/`end`. |
| Submission array/dict size | 5,000 entries | Benchmark guess submissions (state estimation, phase/topology/voltage-control guesses) and chat tool lists. Exceeding it returns `422`. |
| Chat message length | 8,000 characters | `POST` chat messages; longer messages get a friendly rejection instead of being sent to the LLM backend. |

## Difficulty and noise profiles

All four benchmarks accept a platform-controlled `difficulty` query parameter
(`clean`, `easy`, `medium`, `hard`) that determines how much synthetic noise
is applied to measurement values before they're returned to a participant.
The exact profile is echoed back in the response body as `"profile"`, so a
client never has to hardcode these values:

| Difficulty | `pq_rel_sigma` | `v_mag_rel_sigma` | `v_ang_rel_sigma` | `outlier_prob` | `outlier_scale` |
|---|---|---|---|---|---|
| `clean` | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| `easy` | 0.01 | 0.002 | 0.02 | 0.002 | 10.0 |
| `medium` | 0.03 | 0.005 | 0.06 | 0.008 | 12.0 |
| `hard` | 0.07 | 0.010 | 0.15 | 0.020 | 15.0 |

Noise is deterministic and reproducible: it's generated from a `random.Random`
seeded with a SHA-256 hash of `(grid_id, key, difficulty)`, so repeated calls
with the same parameters return identical corrupted values, but different
`difficulty` values produce independent noise draws.

## Anonymisation pattern

The three benchmarks that hide ground truth (Phase Identification, Voltage
Control, and — via `NodeMask`/`GridMask` — State Estimation) all follow the
same shape: a real identifier (`node_id`, `phase`, or `(grid_id, datetime)`)
is mapped to a persistent random key the first time it's requested, and that
mapping is reused on every subsequent call for the same input. Submissions
reference the anonymised key, never the real identifier; scoring joins back
through the mapping table server-side. See [Data Model › Benchmarks](../database-schema.md#benchmarks).

