PHASE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_training_phase_data",
            "description": "Retrieve historical measurement data for training a phase detection algorithm. Returns labelled data with true phases visible.",
            "parameters": {
                "type": "object",
                "properties": {
                    "difficulty": {
                        "type": "string",
                        "enum": ["clean", "easy", "medium", "hard"],
                        "description": "Difficulty level of the data corruption profile. Default is clean."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_phase_identification_data",
            "description": "Retrieve anonymised historical measurement data for testing a phase detection algorithm. True phases are hidden.",
            "parameters": {
                "type": "object",
                "properties": {
                    "difficulty": {
                        "type": "string",
                        "enum": ["clean", "easy", "medium", "hard"],
                        "description": "Difficulty level of the data corruption profile. Default is clean."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "submit_phase_guesses",
            "description": "Submit phase identification guesses for anonymised measurement keys in a grid.",
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
                        "description": "Dictionary mapping anonymised keys to guessed phases e.g. {'key1': 'R', 'key2': 'S'}"
                    }
                },
                "required": ["guess_id", "grid_id", "guesses"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_phase_score",
            "description": "Get the phase identification accuracy score for a user on a specific grid.",
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