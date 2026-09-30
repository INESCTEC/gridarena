STATE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_training_state_data",
            "description": "Retrieve historical measurement data for training a state estimation algorithm. Returns masked grid and node identifiers with measurements.",
            "parameters": {
                "type": "object",
                "properties": {
                    "noise_difficulty": {
                        "type": "string",
                        "enum": ["clean", "easy", "medium", "hard"],
                        "description": "Noise level added to measurements. Default is clean."
                    },
                    "observability": {
                        "type": "string",
                        "enum": ["clean", "easy", "medium", "hard"],
                        "description": "Controls how many nodes are observable. Default is medium."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_state_estimation_input",
            "description": "Retrieve state estimation input data for a specific user. Returns known and unknown nodes with measurement history for a randomly selected grid and timestamp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user ID requesting the estimation task"
                    },
                    "noise_difficulty": {
                        "type": "string",
                        "enum": ["clean", "easy", "medium", "hard"],
                        "description": "Noise level added to measurements. Default is clean."
                    },
                    "observability": {
                        "type": "string",
                        "enum": ["clean", "easy", "medium", "hard"],
                        "description": "Controls how many nodes are observable. Default is medium."
                    }
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "submit_state_estimates",
            "description": "Submit voltage magnitude and angle estimates for unknown nodes in a state estimation task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user ID submitting the estimates"
                    },
                    "estimation_id": {
                        "type": "string",
                        "description": "The estimation task ID returned from get_state_estimation_input"
                    },
                    "grid_id": {
                        "type": "string",
                        "description": "The masked grid ID"
                    },
                    "timestamp": {
                        "type": "string",
                        "description": "The timestamp of the estimation task in ISO format e.g. 2025-07-01T00:00:00"
                    },
                    "estimates": {
                        "type": "array",
                        "description": "List of voltage estimates for each unknown node",
                        "items": {
                            "type": "object",
                            "properties": {
                                "masked_node_id": {"type": "string"},
                                "voltage_magnitude": {"type": "number"},
                                "voltage_angle": {"type": "number"}
                            }
                        }
                    }
                },
                "required": ["user_id", "estimation_id", "grid_id", "timestamp", "estimates"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_state_estimation_score",
            "description": "Get the state estimation score for a user on a specific estimation task. Returns sum of squared errors between predicted and true voltages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user ID to check the score for"
                    },
                    "estimation_id": {
                        "type": "string",
                        "description": "The estimation task ID to check the score for"
                    }
                },
                "required": ["user_id", "estimation_id"]
            }
        }
    }
]