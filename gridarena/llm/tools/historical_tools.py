HISTORICAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "delete_historical_database",
            "description": "Delete an entire historical database, including its timeline and every series/record within it",
            "parameters": {
                "type": "object",
                "properties": {
                    "database_id": {
                        "type": "string",
                        "description": "The database ID to delete"
                    },
                    "confirmed": {
                        "type": "boolean",
                        "description": "Set true only after the user has explicitly confirmed this deletion in their own words."
                    }
                },
                "required": ["database_id", "confirmed"]
            },
            "x-destructive": True
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_historical_series_records",
            "description": "Delete records for one series within a historical database. Can filter by phase and datetime range. The series and database registration are not deleted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "database_id": {
                        "type": "string",
                        "description": "The database the series belongs to"
                    },
                    "series_id": {
                        "type": "string",
                        "description": "The series ID to delete records for"
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
                "required": ["database_id", "series_id", "confirmed"]
            },
            "x-destructive": True
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_historical_series_data",
            "description": "Retrieve records for one series within a historical database. Can filter by phase and datetime range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "database_id": {
                        "type": "string",
                        "description": "The database the series belongs to"
                    },
                    "series_id": {
                        "type": "string",
                        "description": "The series ID to retrieve records for"
                    },
                    "start": {
                        "type": "string",
                        "description": "Optional start datetime ISO format e.g. 2025-07-01T00:00:00"
                    },
                    "end": {
                        "type": "string",
                        "description": "Optional end datetime ISO format e.g. 2025-08-01T00:00:00"
                    },
                    "phase": {
                        "type": "string",
                        "enum": ["R", "S", "T"],
                        "description": "Optional single phase filter"
                    }
                },
                "required": ["database_id", "series_id"]
            }
        }
    }
]
