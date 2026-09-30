MEASUREMENTS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "delete_measurements",
            "description": "Delete measurement records for a grid. Can filter by node, phase, and datetime range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "grid_id": {
                        "type": "string",
                        "description": "The grid ID to delete measurements for"
                    },
                    "node_id": {
                        "type": "string",
                        "description": "Optional node ID to filter deletion"
                    },
                    "phase": {
                        "type": "string",
                        "enum": ["R", "S", "T"],
                        "description": "Optional phase filter"
                    },
                    "start": {
                        "type": "string",
                        "description": "Optional start datetime in ISO format e.g. 2025-07-01T00:00:00"
                    },
                    "end": {
                        "type": "string",
                        "description": "Optional end datetime in ISO format e.g. 2025-08-01T00:00:00"
                    },
                    "confirmed": {
                        "type": "boolean",
                        "description": "Set true only after the user has explicitly confirmed this deletion in their own words."
                    }
                },
                "required": ["grid_id", "confirmed"]
            },
            "x-destructive": True
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_measurements_data",
            "description": "Retrieve measurements for a grid. Can filter by node, phase, and datetime range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "grid_id": {
                        "type": "string",
                        "description": "The grid ID to retrieve measurements for"
                    },
                    "node_id": {
                        "type": "string",
                        "description": "Optional node ID filter"
                    },
                    "start": {
                        "type": "string",
                        "description": "Optional start datetime ISO format e.g. 2025-07-01T00:00:00"
                    },
                    "end": {
                        "type": "string",
                        "description": "Optional end datetime ISO format e.g. 2025-08-01T00:00:00"
                    },
                    "per_phase": {
                        "type": "boolean",
                        "description": "If true returns per phase data, if false returns aggregated data. Default true."
                    },
                    "phase": {
                        "type": "string",
                        "enum": ["R", "S", "T"],
                        "description": "Optional single phase filter, only used when per_phase is true"
                    }
                },
                "required": ["grid_id"]
            }
        }
    }
]
