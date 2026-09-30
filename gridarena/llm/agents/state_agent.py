import gridarena.schemas as sc
from gridarena.llm.base_agent import BaseAgent
from gridarena.routers.state_estimation_benchmark import (
    get_state_estimation_input,
    get_state_estimation_score,
    get_training_state_data,
    submit_state_estimates,
)


class StateAgent(BaseAgent):

    async def _training(self, noise_difficulty: str = "clean", observability: str = "medium"):
        self._record("get_training_state_data")
        return await self._call(
            get_training_state_data,
            noise_difficulty=noise_difficulty, observability=observability,
        )

    async def _input(self, user_id: str, noise_difficulty: str = "clean", observability: str = "medium"):
        self._record("get_state_estimation_input", user_id=user_id)
        return await self._call(
            get_state_estimation_input,
            user_id=user_id, noise_difficulty=noise_difficulty, observability=observability,
        )

    async def _submit(self, user_id: str, estimation_id: str, grid_id: str, timestamp: str, estimates: list):
        self._record("submit_state_estimates", user_id=user_id)
        submission = sc.StateEstimateSubmission(
            user_id=user_id, estimation_id=estimation_id, grid_id=grid_id,
            timestamp=timestamp, estimates=estimates,
        )
        return await self._call(submit_state_estimates, submission=submission)

    async def _score(self, user_id: str, estimation_id: str):
        self._record("get_state_estimation_score", user_id=user_id)
        return await self._call(
            get_state_estimation_score,
            user_id=user_id, estimation_id=estimation_id,
        )

    async def handle(self, tool_name: str, tool_args: dict):
        if tool_name == "get_training_state_data":
            return await self._training(
                noise_difficulty=tool_args.get("noise_difficulty", "clean"),
                observability=tool_args.get("observability", "medium"),
            )
        elif tool_name == "get_state_estimation_input":
            return await self._input(
                user_id=tool_args["user_id"],
                noise_difficulty=tool_args.get("noise_difficulty", "clean"),
                observability=tool_args.get("observability", "medium"),
            )
        elif tool_name == "submit_state_estimates":
            return await self._submit(
                user_id=tool_args["user_id"], estimation_id=tool_args["estimation_id"],
                grid_id=tool_args["grid_id"], timestamp=tool_args["timestamp"],
                estimates=tool_args["estimates"],
            )
        elif tool_name == "get_state_estimation_score":
            return await self._score(user_id=tool_args["user_id"], estimation_id=tool_args["estimation_id"])
        return await super().handle(tool_name, tool_args)
