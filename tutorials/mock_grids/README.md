# Mock Grids

This folder contains example JSON files for uploading grids through the gridarena UI.

---

## LV Grid Example

**File:** `lv_grid_example.json`

A 230V low-voltage residential distribution grid with:

- **11 nodes** — 1 transformer point (PT) + 10 load/generation nodes
- **3 cable types** — 4x95mm² (main feeder), 4x50mm² (branches), 4x25mm² (end segments)
- **10 connections** — radial tree from PT

### Topology

```
        PT (transformer)
       /        \
      N1         N9
     / \          \
    N2   N5       N10
   / \     \
  N3  (N2)  N6
  / \
 N4   N7
       \
        N8
```

### Cable types

| Cable ID | Cross-section | R (ohm/km) | X (ohm/km) | Nominal Current (A) |
|----------|--------------|------------|------------|---------------------|
| CBL_4x95 | 4x95 mm² | 0.320 | 0.078 | 245 |
| CBL_4x50 | 4x50 mm² | 0.641 | 0.083 | 160 |
| CBL_4x25 | 4x25 mm² | 1.200 | 0.086 | 110 |

### How to use

1. Go to **LV Grids** in the sidebar (under Database)
2. Upload `lv_grid_example.json`
3. Click **Validate** — the preview shows 11 nodes, 3 cables, 10 connections, and the interactive graph
4. Set the use-case flags (phase detection, topology, etc.) as needed
5. Click **Save to Database**
6. The grid is now available for historical data, power flow, benchmarks, RL training, and diffusion models

### JSON format reference

```json
{
  "grid_id": "string (unique ID)",
  "nodes": [
    {"node_id": "PT", "coord_lat": 0.0, "coord_lon": 0.0, "coord_error": 0}
  ],
  "cables": [
    {
      "cable_id": "string",
      "r_imp_real": 0.0, "r_imp_imag": 0.0,
      "s_imp_real": 0.0, "s_imp_imag": 0.0,
      "t_imp_real": 0.0, "t_imp_imag": 0.0,
      "r_nom_curr": 0.0, "s_nom_curr": 0.0, "t_nom_curr": 0.0
    }
  ],
  "connections": [
    {
      "connection_id": "string",
      "from_node_id": "string (must exist in nodes)",
      "to_node_id": "string (must exist in nodes)",
      "cable_id": "string (must exist in cables)",
      "length": 0.0
    }
  ]
}
```

### Validation rules

The `/grid/validate` endpoint checks:
- `grid_id` is not empty
- At least one node exists
- No duplicate node, cable, or connection IDs
- All `from_node_id` / `to_node_id` in connections reference existing nodes
- All `cable_id` in connections reference existing cables

---

## MV Grid Example

**File:** `mv_grid_example.json`

A 20kV medium voltage distribution network with:

- **10 MV nodes** — 1 substation (MV_SUB), 5 junctions, 4 connection points
- **3 cable types** — varying impedance and current ratings
- **9 connections** — radial tree topology from the substation
- **4 connection points** — where LV grids can be attached (CP1–CP4)
- **4 transformers** — pre-defined MV/LV bridges (250–1000 kVA) with impedance data

### Topology

```
                MV_SUB (substation)
               /       |       \
            MV_N1    MV_N3    MV_N4
           /    \      |         |
        MV_N2  MV_CP1 MV_CP3  MV_CP4
          |      (CP1)  (CP3)   (CP4)
        MV_N5
          |
        MV_CP2
         (CP2)
```

### How to use

1. Go to **MV Grid** in the sidebar
2. Upload `mv_grid_example.json`
3. Click **Validate** to check the file — the preview shows 10 nodes, 9 connections, 4 connection points, 4 transformers
4. Click **Save to Database**
5. Open the grid detail page
6. Connect existing LV grids to the connection points:
   - Select a connection point (e.g. CP1)
   - Choose an LV grid from the dropdown
   - Confirm or adjust the transformer parameters
   - Click **Connect**
7. View aggregated P/V pairs for any connected LV grid

### JSON format reference

```json
{
  "mv_grid_id": "string (unique ID)",
  "name": "optional display name",
  "description": "optional description",
  "nominal_voltage_kv": 20.0,
  "region": "optional region/location",

  "nodes": [
    {"node_id": "string", "coord_lat": 0.0, "coord_lon": 0.0, "node_type": "substation|junction|connection_point"}
  ],

  "cables": [
    {"cable_id": "string", "imp_real": 0.0, "imp_imag": 0.0, "nom_curr": 0.0}
  ],

  "connections": [
    {"connection_id": "string", "from_node_id": "string", "to_node_id": "string", "cable_id": "string", "length": 0.0}
  ],

  "connection_points": [
    {"connection_point_id": "string", "node_id": "string (must exist in nodes)", "name": "optional"}
  ],

  "transformers": [
    {
      "transformer_id": "string",
      "connection_point_id": "string (must exist in connection_points)",
      "lv_grid_id": "optional (connect later via UI)",
      "rated_power_kva": 400.0,
      "primary_voltage_kv": 20.0,
      "secondary_voltage_v": 230.0,
      "imp_real": 0.004,
      "imp_imag": 0.040,
      "name": "optional"
    }
  ]
}
```

### Validation rules

The upload endpoint checks:
- All `from_node_id` / `to_node_id` in connections reference existing nodes
- All `cable_id` in connections reference existing cables
- All `node_id` in connection points reference existing nodes
- No duplicate `connection_point_id` values
- All `connection_point_id` in transformers reference existing connection points
- Transformer `primary_voltage_kv` matches the grid's `nominal_voltage_kv`
