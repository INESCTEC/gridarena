# Historical Agent

## Overview

The Historical Agent handles historical **databases**: named collections of standalone power/voltage series ("historicals") that are **not** tied to any specific grid or node, and all share the exact same timeline.

A database has a `database_id`, a declared list of `timestamps` (its shared timeline), and any number of series inside it. Each series has its own `series_id` (unique within that database), a `grid_level` tag (`"MV"`, `"LV"`, or `"Feeder"`), and a list of values whose `datetime`s must all be members of the database's declared `timestamps` — every series in a database is required to line up on the same time axis. A series can hold power values (`power_active`/`power_reactive`), voltage values (`voltage_magnitude`/`voltage_angle`), or both — each recorded value must include at least one of power or voltage.

Users only ever upload whole databases, never a single bare series. A database can contain as many series as needed.

This is a lighter-weight data library than the Measurements Agent: useful for storing and browsing curves before deciding how (or whether) they map onto a specific registered grid. **It is not currently consumed by any power flow simulation or benchmark** — if you need data that feeds directly into those, use the Measurements Agent instead, which requires a registered grid and node for every reading.

---

## Functions

### Uploading a historical database

There is no tool for this — the assistant cannot upload files on the user's behalf. To
upload a historical database (one or more standalone power/voltage curves sharing a
common timeline, not tied to any particular grid or node), the user must upload it
themselves through the historical data page in the web UI, or by calling `POST
/historical/` directly with a JSON file that includes `database_id`, a `timestamps` list,
and a `historicals` list (each entry needs `series_id`, `grid_level` — `"MV"`, `"LV"`, or
`"Feeder"` — and a `values` list). Every value's `datetime` must be a member of the
database's `timestamps` list, or the upload is rejected (422). Re-uploading the same
`database_id` refreshes its metadata, adds any new timestamps, and upserts each series'
data.

---

### get_historical_series_data

Use this when you want to inspect what's in one series of a database, or filter its records by time range or phase.

**Parameters:**
- `database_id` (string, required): The database the series belongs to
- `series_id` (string, required): The series to query
- `start` (string, optional): Start of time range (ISO 8601 format, e.g. `"2025-07-01T00:00:00"`)
- `end` (string, optional): End of time range (ISO 8601 format)
- `phase` (string, optional): Filter to a single phase — `"R"`, `"S"`, or `"T"` (series values are often unphased, i.e. `phase` is `null`)

**Returns:** Series metadata (`grid_level`, `name`, `description`) plus matching records.

**How to interpret:**
- `power_active`/`power_reactive`: real/reactive power, same units and sign convention as the Measurements Agent
- `voltage_magnitude`/`voltage_angle`: RMS voltage and phase angle, same convention as the Measurements Agent
- Any of these four fields may be `null` on a given record — a series can be power-only or voltage-only
- `grid_level`: whether this series is meant to represent an MV-level, LV-level, or feeder-level quantity

**Example:**
```json
{
  "database_id": "db001",
  "series_id": "series001",
  "start": "2025-07-01T00:00:00",
  "end": "2025-07-01T01:00:00"
}
```

---

### delete_historical_series_records

Use this when you want to remove records from one series within a database — e.g. clearing a bad time window before re-uploading corrected values.

**Parameters:**
- `database_id` (string, required): The database the series belongs to
- `series_id` (string, required): The series whose records to delete
- `phase` (string, optional): Limit deletion to a specific phase
- `start` (string, optional): Start of time range to delete
- `end` (string, optional): End of time range to delete

**Returns:** Confirmation message.

**Notes:**
- Omitting optional filters deletes every record for that series, but the series and database registrations are left in place
- This operation is irreversible

**Example:**
```json
{
  "database_id": "db001",
  "series_id": "series001",
  "start": "2025-07-01T00:00:00",
  "end": "2025-07-01T01:00:00"
}
```

---

### delete_historical_database

Use this when you want to remove an entire database — its timeline, every series in it, and all their records.

**Parameters:**
- `database_id` (string, required): The database to delete

**Returns:** Confirmation message.

**Notes:**
- This deletes everything in the database, not just one series — use `delete_historical_series_records` instead if you only want to clear one series
- This operation is irreversible

**Example:**
```json
{
  "database_id": "db001"
}
```
