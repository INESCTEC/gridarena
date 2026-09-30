# Benchmark Sequence Diagram

Request flow shared by all four benchmark modules (Phase Identification,
Topology Discovery, State Estimation, Voltage Control): a participant
downloads an anonymised, noise-corrupted dataset, then submits predictions
that are scored server-side against ground truth the participant never sees.
See [API Reference › Overview](../api/index.md#difficulty-and-noise-profiles)
for the exact difficulty/noise profile values.

```mermaid
sequenceDiagram
    actor Participant
    participant Router as Benchmark Router
    participant Noise as General Noise / Anonymisation
    participant DB as PostgreSQL

    Participant->>Router: GET /{benchmark}/data
    Router->>DB: fetch grid + measurement data
    Router->>DB: create benchmark task record
    Router->>Noise: apply seeded corruption (difficulty profile)
    Noise->>Noise: generate anonymisation key mapping
    Router->>DB: persist anonymisation key + ground truth
    Router-->>Participant: anonymised dataset + task id

    Participant->>Router: POST /{benchmark}/submit (guesses)
    Router->>DB: fetch ground truth via anonymisation key
    Router->>Router: score guesses vs ground truth
    Router->>DB: persist score
    Router-->>Participant: benchmark score

    Note over Participant,DB: Real node/phase/grid identifiers are never exposed to the participant
```
