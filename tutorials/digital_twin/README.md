# Digital Twin for Electrical Grids

This document describes the Digital Twin feature in GridArena, its architecture, and a step-by-step guide for creating and operating a digital twin.

---

## 1. Concept

A digital twin is a live, software replica of a physical electrical grid. It continuously ingests real-time measurements from an external data source, runs the backward/forward sweep power-flow algorithm, and compares simulated voltages against the true streamed values.

This enables:

- Real-time grid monitoring without direct SCADA access.
- Continuous validation of grid models against field measurements.
- Early detection of voltage deviations, measurement anomalies, and model drift.
- Historical tracking of power-flow accuracy over time.

---

## 2. Architecture

```
External REST API / data source
        │
        ▼
┌──────────────────────────┐
│  Connector Service        │  ← HTTP pull with auth (bearer, API key, basic)
│  (per-node fetch + retry) │     one API call per assigned grid node
└────────┬─────────────────┘
         │ raw JSON (per node)
         ▼
┌──────────────────────────┐
│  Field Mapper             │  ← declarative path mapping per node
│  (extract latest value)   │     supports data[0].value index notation
└────────┬─────────────────┘
         │ GridArena-compatible measurement batch
         ▼
┌──────────────────────────┐
│  Redis Streams            │  ← broker topic per digital twin
│  (message broker)         │
└────────┬─────────────────┘
         │ validated measurements
         ▼
┌──────────────────────────┐
│  Digital Twin Runner      │  ← consume from broker
│  (periodic loop)          │
│                           │
│  ┌────────────────────┐   │
│  │ Power Flow         │   │  ← existing backward/forward sweep
│  │ Algorithm          │   │
│  └────────┬───────────┘   │
│           │               │
│  ┌────────▼───────────┐   │
│  │ Comparison         │   │  ← simulated vs true voltage
│  │ & Metrics          │   │
│  └────────────────────┘   │
└────────┬─────────────────┘
         │
         ▼
┌──────────────────────────┐
│  PostgreSQL               │  ← results, events, metrics
│  + REST API               │
│  + Dashboard UI           │
└──────────────────────────┘
```

### Key design decisions

1. The message broker only receives messages that already conform to the existing GridArena measurement schema. All field mapping, validation, and external API access happen before publishing to the broker.

2. **Per-node fetching**: each grid node can have its own query parameters and field mapping. The runner makes a separate API call for each assigned node, allowing different sensors or variables to feed different nodes from the same base API.

---

## 3. Measurement Schema Compatibility

Streamed measurements reuse the same fields as GridArena historical measurements:

| Field | Type | Description |
|-------|------|-------------|
| `grid_id` | string | Grid identifier (must exist in the database) |
| `node_id` | string | Node identifier (must exist in the grid) |
| `datetime` | ISO 8601 string | Measurement timestamp |
| `phase` | `R`, `S`, `T`, or null | Electrical phase |
| `power_active` | float | Active power (kW) |
| `power_reactive` | float | Reactive power (kVAr) |
| `voltage_magnitude` | float | Voltage magnitude (V) |
| `voltage_angle` | float | Voltage angle (degrees), defaults to 0 |

After field mapping, each measurement batch is validated for:

- Grid existence
- Node existence within the grid
- Valid phase values
- Parseable timestamp
- Numeric values
- No duplicate node/phase/timestamp entries
- Non-negative voltage magnitude

---

## 4. Connector

### 4.1 HTTP REST

The connector fetches data from an external REST API. In per-node mode, each assigned node triggers its own API call using the shared base URL plus node-specific query parameters.

**Base configuration (shared across all nodes):**

| Field | Description |
|-------|-------------|
| `url` | Base URL of the external endpoint |
| `method` | `GET` or `POST` |
| `headers` | Additional HTTP headers (JSON object) |
| `auth_type` | `none`, `bearer`, `api_key`, or `basic` |
| `secret_ref` | Name of the environment variable holding the secret |
| `secret_header` | Header name for the secret (e.g. `Authorization`, `X-Api-Key`) |
| `retry_count` | Number of retry attempts (0–10, default 3) |

**Per-node configuration:**

| Field | Description |
|-------|-------------|
| `query_params` | Query parameters appended to the base URL for this node |
| `update_interval_seconds` | How often to fetch this node's data (5–86400, default 60) |
| `timeout_seconds` | Request timeout for this node (1–300, default 30) |

### 4.2 Authentication

Secrets are never stored in the database. Instead, you provide the name of an environment variable that holds the token or API key. The connector reads the value at runtime.

**Bearer token example:**

```
# In your .env file or environment:
SCADA_API_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6...

# In the digital twin configuration:
auth_type: bearer
secret_ref: SCADA_API_TOKEN
# The connector sends: Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**API key example:**

```
# Environment:
GRID_DATA_API_KEY=abc123xyz

# Configuration:
auth_type: api_key
secret_ref: GRID_DATA_API_KEY
secret_header: X-Api-Key
# The connector sends: X-Api-Key: abc123xyz
```

---

## 5. Field Mapping

The digital twin supports two mapping modes: **per-node mapping** (recommended) and **global batch mapping** (legacy).

### 5.1 Per-node mapping

Each assigned node has its own mapping configuration that extracts measurement values from that node's API response. This is the mode used by the creation wizard.

**Per-node mapping fields:**

| Field | Description | Example |
|-------|-------------|---------|
| `timestamp` | Path to the measurement timestamp | `data[0].datetime` |
| `active_power` | Path to active power value | `data[0].value` |
| `reactive_power` | Path to reactive power value (optional) | `data[0].q_value` |
| `voltage_magnitude` | Path to voltage magnitude (optional) | `data[0].voltage` |
| `voltage_angle` | Path to voltage angle (optional) | `data[0].angle` |

### 5.2 Path syntax

Paths use dot-separated keys to traverse nested JSON structures:

| Pattern | Meaning |
|---------|---------|
| `field` | Direct key access |
| `data.timestamp` | Nested access: `{"data": {"timestamp": "..."}}` |
| `data[0].value` | First element of array: `{"data": [{"value": 123}, ...]}` |
| `data[-1].value` | Last element of array |
| `items[].value` | Iterate over array, extract `value` from each element |

### 5.3 Extracting the latest measurement from a list

Many APIs return time series as arrays sorted newest-first. Use `[0]` to extract the latest entry.

**External API response:**

```json
{
  "data": [
    {
      "datetime": "2026-06-25T13:15:33Z",
      "variable": "pv_3_pac",
      "value": 1664.625,
      "units": "w",
      "updated_at": "2026-06-25T13:30:03Z"
    },
    {
      "datetime": "2026-06-25T13:10:33Z",
      "variable": "pv_3_pac",
      "value": 1604.125,
      "units": "w",
      "updated_at": "2026-06-25T13:30:03Z"
    }
  ]
}
```

**Per-node mapping:**

| Field | Path | Resolved value |
|-------|------|----------------|
| `timestamp` | `data[0].datetime` | `"2026-06-25T13:15:33Z"` |
| `active_power` | `data[0].value` | `1664.625` |

The `[0]` index picks the first (latest) element from the `data` array, then `.datetime` or `.value` extracts the field from that element.

### 5.4 Per-node query parameters

Each node can add its own query parameters to the base URL. This allows a single API endpoint to serve data for different sensors or variables.

**Example:** base URL is `https://api.example.com/measurements` and three nodes are configured:

| Node | Query Params | Full request |
|------|--------------|--------------|
| N1 | `{"variable": "pv_1_pac"}` | `GET /measurements?variable=pv_1_pac` |
| N2 | `{"variable": "pv_2_pac"}` | `GET /measurements?variable=pv_2_pac` |
| N3 | `{"variable": "pv_3_pac"}` | `GET /measurements?variable=pv_3_pac` |

Each response is mapped independently using that node's mapping paths.

### 5.5 Global batch mapping (legacy)

If no per-node assignments are configured, the runner falls back to a single API call with global field mapping. This mode expects the API to return all measurements in one response.

```json
{
  "timestamp": "meta.captured_at",
  "measurements": "data.readings",
  "node_id": "sensor_id",
  "phase": "phase",
  "active_power": "active_power_kw",
  "reactive_power": "reactive_power_kvar",
  "voltage_magnitude": "voltage_v"
}
```

---

## 6. Broker

The digital twin uses **Redis Streams** as the message broker.

### 6.1 Topic naming

Each digital twin gets a dedicated stream:

```
gridarena.digital_twin.{digital_twin_id}.measurements
```

You can override the topic in the configuration if needed.

### 6.2 Message format

Each message in the stream contains a single field `payload` with a JSON-serialized `StreamedMeasurementBatch`. The broker only ever receives validated, schema-compatible data.

### 6.3 Configuration

Set the `REDIS_URL` environment variable:

```
REDIS_URL=redis://localhost:6379
```

If not set, it defaults to `redis://localhost:6379`.

---

## 7. Power-Flow Comparison

After each update, the digital twin:

1. Takes the streamed measurements for the configured phase.
2. Builds the complex power array `S = P + jQ` for each node.
3. Loads the grid topology and cable admittances from the database.
4. Runs the backward/forward sweep power-flow algorithm.
5. Compares simulated voltages against the true streamed voltage magnitudes.

### 7.1 Metrics computed

| Metric | Description |
|--------|-------------|
| `convergence_status` | `converged` or `failed` |
| `voltage_mae` | Mean Absolute Error across all nodes with true voltage (V) |
| `voltage_rmse` | Root Mean Square Error (V) |
| `max_voltage_error` | Worst-case voltage deviation (V) |
| `active_power_error` | Mean active power error if computable (kW) |
| `measurements_count` | Number of measurements in the batch |
| `missing_measurements` | Nodes in the grid with no streamed data |
| `invalid_measurements` | Measurements that could not be mapped to grid nodes |
| `execution_time_ms` | Wall-clock time for the power-flow computation |

### 7.2 Per-node details

Each result also stores a per-node breakdown with `true_voltage`, `simulated_voltage`, and `error` for every node that had both a true measurement and a simulated value.

---

## 8. REST API

All endpoints are under the `/digital-twins` prefix.

### 8.1 CRUD

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/digital-twins/` | Create a digital twin |
| `GET` | `/digital-twins/` | List all digital twins |
| `GET` | `/digital-twins/{id}` | Get digital twin details |
| `PATCH` | `/digital-twins/{id}` | Update configuration (must be stopped) |
| `DELETE` | `/digital-twins/{id}` | Delete digital twin and its data |

### 8.2 Lifecycle

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/digital-twins/{id}/start` | Start periodic execution |
| `POST` | `/digital-twins/{id}/stop` | Stop periodic execution |
| `POST` | `/digital-twins/{id}/tick` | Run one cycle manually |

### 8.3 Validation and testing

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/digital-twins/validate-field-mapping` | Validate a global mapping against a sample payload |
| `GET` | `/digital-twins/grid-graph/{grid_id}` | Get grid nodes, connections and graph layout |
| `POST` | `/digital-twins/{id}/test-source` | Test connectivity to the external API |
| `POST` | `/digital-twins/{id}/publish-sample` | Fetch, map, validate, and publish one sample |

### 8.4 Results and monitoring

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/digital-twins/{id}/latest-state` | Latest measurements + latest result |
| `GET` | `/digital-twins/{id}/results` | Power-flow comparison results |
| `GET` | `/digital-twins/{id}/metrics` | Aggregated metrics summary |
| `GET` | `/digital-twins/{id}/events` | Event log (created, started, errors, ticks) |

---

## 9. Frontend

The digital twin UI is split into two pages, accessible from the sidebar under **Digital Twin**:

- **Overview** (`/digital-twins/ui`) — lists all existing digital twins with status, last run time, errors, and lifecycle actions (Start, Stop, Tick, Delete).
- **New Twin** (`/digital-twins/ui/new`) — a step-by-step wizard for creating a new digital twin.

### 9.1 Creation wizard flow

**Step 1 — Select Grid**

Select an existing grid from the dropdown. Give the digital twin a name and optional description.

**Step 2 — External Data Source**

Enter the base URL of the external REST API and configure authentication. Query parameters are not set here — they are configured per node in the next step.

- Base URL (e.g. `https://api.example.com/measurements`)
- HTTP method (GET or POST)
- Auth type (None, Bearer Token, API Key, Basic Auth)
- Secret environment variable name (if authentication is required)
- Extra headers

**Step 3 — Assign Nodes**

This step displays the grid as an interactive NetworkX graph rendered with Plotly. Nodes are color-coded:

- Blue: unassigned nodes
- Green: assigned nodes
- Red: transformer point (PT)

Click any node on the graph to open a configuration panel on the right side, where you set:

- **Phase** — R, S, or T
- **Query parameters** — JSON object appended to the base URL for this node's API call (e.g. `{"variable": "pv_3_pac"}`)
- **Update interval** — polling frequency in seconds
- **Timeout** — request timeout in seconds
- **Field mapping paths** — dot-separated paths with `[0]` index support:
  - Timestamp: e.g. `data[0].datetime`
  - Active power: e.g. `data[0].value`
  - Reactive power (optional)
  - Voltage magnitude (optional)

Click **Assign Node** to confirm. A table below the graph tracks all assignments. At least one node must be assigned before proceeding.

**Step 4 — Power-Flow Configuration**

- Select the electrical phase for the power-flow algorithm (R, S, or T)
- Set the reference voltage (typically 230V for European LV grids)
- Optionally override the broker topic

**Step 5 — Review & Create**

Review the full configuration summary and node assignments JSON. Click **Create Digital Twin** to save. After creation, you are redirected to the monitoring detail page.

### 9.2 Monitoring page

The detail page (`/digital-twins/ui/{id}`) shows:

- **Summary cards** — status, interval, total runs, last run time
- **Lifecycle controls** — Start, Stop, Run Once (Tick), Test Source, Publish Sample
- **Latest metrics** — convergence status, voltage MAE/RMSE, max error, execution time
- **True vs Simulated Voltage chart** — per-node Plotly bar chart
- **MAE over time chart** — line chart tracking accuracy drift
- **Results table** — full history of power-flow comparison results
- **Event log** — chronological log of all events
- **Configuration details** — collapsible section with source config, node assignments, and power-flow settings

---

## 10. Example Configuration

### 10.1 Per-node mode (recommended)

This example creates a digital twin that monitors three nodes of an LV grid. Each node fetches data from the same base API but with different query parameters.

```json
{
  "grid_id": "LV_GRID_01",
  "name": "Porto LV Twin",
  "description": "Real-time monitoring of the Porto residential LV grid",
  "update_interval_seconds": 60,
  "broker_type": "redis",
  "source_config": {
    "source_type": "http",
    "url": "https://scada.example.com/api/v2/latest",
    "method": "GET",
    "headers": {"Accept": "application/json"},
    "auth_type": "bearer",
    "secret_ref": "SCADA_API_TOKEN",
    "retry_count": 3
  },
  "node_assignments": [
    {
      "node_id": "N1",
      "phase": "R",
      "query_params": {"variable": "pv_1_pac"},
      "update_interval_seconds": 60,
      "timeout_seconds": 15,
      "mapping": {
        "timestamp": "data[0].datetime",
        "active_power": "data[0].value",
        "voltage_magnitude": null,
        "reactive_power": null
      }
    },
    {
      "node_id": "N2",
      "phase": "R",
      "query_params": {"variable": "pv_2_pac"},
      "update_interval_seconds": 60,
      "timeout_seconds": 15,
      "mapping": {
        "timestamp": "data[0].datetime",
        "active_power": "data[0].value"
      }
    },
    {
      "node_id": "N3",
      "phase": "R",
      "query_params": {"variable": "pv_3_pac"},
      "update_interval_seconds": 60,
      "timeout_seconds": 15,
      "mapping": {
        "timestamp": "data[0].datetime",
        "active_power": "data[0].value"
      }
    }
  ],
  "powerflow_config": {
    "phase": "R",
    "voltage_ref": 230.0
  }
}
```

### 10.2 Expected API response per node

For each node, the connector calls:

```
GET https://scada.example.com/api/v2/latest?variable=pv_3_pac
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

And receives:

```json
{
  "data": [
    {
      "datetime": "2026-06-25T13:15:33Z",
      "variable": "pv_3_pac",
      "value": 1664.625,
      "units": "w",
      "updated_at": "2026-06-25T13:30:03Z"
    },
    {
      "datetime": "2026-06-25T13:10:33Z",
      "variable": "pv_3_pac",
      "value": 1604.125,
      "units": "w",
      "updated_at": "2026-06-25T13:30:03Z"
    }
  ]
}
```

The mapping `data[0].value` extracts `1664.625` (the latest measurement) and `data[0].datetime` extracts `"2026-06-25T13:15:33Z"`.

### 10.3 Resulting broker message

After all nodes are fetched and mapped, the broker receives a single batch:

```json
{
  "grid_id": "LV_GRID_01",
  "timestamp": "2026-06-25T13:15:33Z",
  "measurements": [
    {
      "node_id": "N1",
      "phase": "R",
      "datetime": "2026-06-25T13:15:33Z",
      "power_active": 1520.0,
      "power_reactive": 0.0,
      "voltage_magnitude": 0.0,
      "voltage_angle": 0.0
    },
    {
      "node_id": "N2",
      "phase": "R",
      "datetime": "2026-06-25T13:15:33Z",
      "power_active": 1890.25,
      "power_reactive": 0.0,
      "voltage_magnitude": 0.0,
      "voltage_angle": 0.0
    },
    {
      "node_id": "N3",
      "phase": "R",
      "datetime": "2026-06-25T13:15:33Z",
      "power_active": 1664.625,
      "power_reactive": 0.0,
      "voltage_magnitude": 0.0,
      "voltage_angle": 0.0
    }
  ]
}
```

### 10.4 Global batch mode (legacy)

If the external API returns all nodes in a single response, you can use the global field mapping instead of per-node assignments:

```json
{
  "grid_id": "LV_GRID_01",
  "name": "Batch Mode Twin",
  "source_config": {
    "source_type": "http",
    "url": "https://scada.example.com/api/v2/all-measurements",
    "method": "GET",
    "query_params": {"grid": "porto_lv_01"},
    "auth_type": "bearer",
    "secret_ref": "SCADA_API_TOKEN"
  },
  "field_mapping": {
    "timestamp": "meta.captured_at",
    "measurements": "data.readings",
    "node_id": "sensor_id",
    "phase": "phase",
    "active_power": "active_power_kw",
    "reactive_power": "reactive_power_kvar",
    "voltage_magnitude": "voltage_v"
  },
  "powerflow_config": {
    "phase": "R",
    "voltage_ref": 230.0
  }
}
```

---

## 11. Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GRID_DB_DSN` | Yes | PostgreSQL connection string |
| `REDIS_URL` | No | Redis connection URL (default: `redis://localhost:6379`) |
| `{your_secret_ref}` | Per twin | Token/API key for external API access |

---

## 12. Limitations

- **One broker type**: Only Redis Streams is currently supported. Kafka/RabbitMQ/MQTT can be added by implementing the same publish/consume interface.
- **Single phase per twin**: Each digital twin runs power flow on one phase. Create separate twins for multi-phase monitoring.
- **HTTP pull only**: The connector polls the external API. Push-based ingestion (webhooks, MQTT subscriptions) is not yet supported.
- **Radial grids**: The backward/forward sweep power-flow algorithm assumes a radial (tree-structured) grid topology.
- **No automatic credential rotation**: If a token expires, update the environment variable and restart the twin.
- **Per-node call overhead**: In per-node mode, each tick makes N API calls (one per assigned node). For grids with many nodes, this can be slower than a single batch call. Use the global batch mode if the API supports it.
