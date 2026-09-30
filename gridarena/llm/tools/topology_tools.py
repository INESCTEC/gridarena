TOPOLOGY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_training_topology_data",
            "description": "Retrieve historical measurement and grid topology data for training a topology discovery algorithm. True topology is visible.",
            "parameters": {
                "type": "object",
                "properties": {
                    "difficulty": {
                        "type": "string",
                        "enum": ["clean", "easy", "medium", "hard"],
                        "description": "Difficulty level of data corruption. Default is clean."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_topology_discovery_data",
            "description": "Retrieve anonymised historical measurement data for testing a topology discovery algorithm. True topology is hidden.",
            "parameters": {
                "type": "object",
                "properties": {
                    "difficulty": {
                        "type": "string",
                        "enum": ["clean", "easy", "medium", "hard"],
                        "description": "Difficulty level of data corruption. Default is clean."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "submit_topology_guesses",
            "description": "Submit topology guesses for a grid. Guesses are a list of edges represented as pairs of node indices.",
            "parameters": {
                "type": "object",
                "properties": {
                    "guess_id": {
                        "type": "string",
                        "description": "The user or submission ID"
                    },
                    "grid_id": {
                        "type": "string",
                        "description": "The grid ID the guesses are for"
                    },
                    "guesses": {
                        "type": "array",
                        "description": "List of edges as pairs of node indices e.g. [[0,1],[1,2],[2,3]]",
                        "items": {
                            "type": "array",
                            "items": {"type": "integer"}
                        }
                    }
                },
                "required": ["guess_id", "grid_id", "guesses"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_topology_score",
            "description": "Get the topology discovery accuracy score for a user on a specific grid. Returns correct edges, missed edges and overall accuracy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "guess_id": {
                        "type": "string",
                        "description": "The user or submission ID"
                    },
                    "grid_id": {
                        "type": "string",
                        "description": "The grid ID to check the score for"
                    }
                },
                "required": ["guess_id", "grid_id"]
            }
        }
    }
]