GRID_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_grid_data",
            "description": "Use when user asks about a grid's nodes, connections, cables or general info",
            "parameters": {
                "type": "object",
                "properties": {
                    "grid_id": {"type": "string"},
                    "table": {
                        "type": "string",
                        "enum": ["Node", "Cable", "Connection", "grids"]
                    }
                },
                "required": ["grid_id", "table"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_grid",
            "description": "Use when user wants to delete a grid",
            "parameters": {
                "type": "object",
                "properties": {
                    "grid_id": {"type": "string"},
                    "confirmed": {
                        "type": "boolean",
                        "description": "Set true only after the user has explicitly confirmed this deletion in their own words.",
                    },
                },
                "required": ["grid_id", "confirmed"]
            },
            "x-destructive": True,
        }
    }
]