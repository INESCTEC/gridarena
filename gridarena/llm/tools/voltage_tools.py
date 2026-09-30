VOLTAGE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_training_voltage_control_data",
            "description": "Retrieve training snapshots with reference solutions for voltage control. Returns measurements and optimal solutions for each grid and timestamp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "voltage_limit": {
                        "type": "number",
                        "description": "Voltage threshold used to select snapshots with violations e.g. 230.0"
                    },
                    "scenario": {
                        "type": "string",
                        "enum": ["Overvoltages", "Undervoltages"],
                        "description": "Whether to retrieve overvoltage or undervoltage scenarios"
                    },
                    "difficulty": {
                        "type": "string",
                        "enum": ["clean", "easy", "medium", "hard"],
                        "description": "Filters snapshots by hardness. Default is clean."
                    }
                },
                "required": ["voltage_limit", "scenario"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_voltage_control_data",
            "description": "Retrieve testing snapshots for voltage control with hidden reference solutions. Returns anonymised measurement data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "voltage_limit": {
                        "type": "number",
                        "description": "Voltage threshold used to select snapshots with violations e.g. 230.0"
                    },
                    "scenario": {
                        "type": "string",
                        "enum": ["Overvoltages", "Undervoltages"],
                        "description": "Whether to retrieve overvoltage or undervoltage scenarios"
                    },
                    "difficulty": {
                        "type": "string",
                        "enum": ["clean", "easy", "medium", "hard"],
                        "description": "Filters snapshots by hardness. Default is clean."
                    }
                },
                "required": ["voltage_limit", "scenario"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "submit_voltage_control_guesses",
            "description": "Submit corrected voltage and power adjustment guesses for voltage control scenarios.",
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
                        "type": "object",
                        "description": "Dictionary mapping anonymised keys to lists of node solutions with corrected voltages and power adjustments"
                    }
                },
                "required": ["guess_id", "grid_id", "guesses"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_voltage_control_score",
            "description": "Get the voltage control score for a user on a specific grid. Returns overall score and per timestamp breakdown.",
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