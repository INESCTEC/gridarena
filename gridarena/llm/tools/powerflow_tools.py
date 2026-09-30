POWERFLOW_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_power_flow",
            "description": "Run the power flow algorithm for a specific grid and phase. Can optionally filter by datetime range. Results are stored and can be retrieved afterwards.",
            "parameters": {
                "type": "object",
                "properties": {
                    "grid_id": {
                        "type": "string",
                        "description": "The grid ID to run power flow on"
                    },
                    "phase": {
                        "type": "string",
                        "enum": ["R", "S", "T"],
                        "description": "The electrical phase to run power flow for"
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Optional start datetime in ISO format e.g. 2025-07-01T00:00:00"
                    },
                    "end_time": {
                        "type": "string",
                        "description": "Optional end datetime in ISO format e.g. 2025-07-01T23:59:59"
                    }
                },
                "required": ["grid_id", "phase"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_power_flow_results",
            "description": "Retrieve stored power flow results for a grid and phase. Returns voltage magnitude and angle per node per timestamp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "grid_id": {
                        "type": "string",
                        "description": "The grid ID to retrieve results for"
                    },
                    "phase": {
                        "type": "string",
                        "enum": ["R", "S", "T"],
                        "description": "The electrical phase to retrieve results for"
                    }
                },
                "required": ["grid_id", "phase"]
            }
        }
    }
]