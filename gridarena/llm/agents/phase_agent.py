import gridarena.schemas as sc
from gridarena.llm.base_agent import BaseAgent
from gridarena.routers.phase_identification_benchmark import (
    get_phase_identification_data,
    get_score,
    get_training_phase_identification_data,
    submit_phase_guesses,
)


class PhaseAgent(BaseAgent):

    async def _training(self, difficulty: str = "clean"):
        self._record("get_training_phase_data", difficulty=difficulty)
        return await self._call(get_training_phase_identification_data, difficulty=difficulty)

    async def _test(self, difficulty: str = "clean"):
        self._record("get_phase_identification_data", difficulty=difficulty)
        return await self._call(get_phase_identification_data, difficulty=difficulty)

    async def _submit(self, guess_id: str, grid_id: str, guesses: dict):
        self.last_queried_grid = grid_id
        self._record("submit_phase_guesses", grid_id=grid_id)
        submission = sc.PhaseGuessSubmission(guess_id=guess_id, grid_id=grid_id, guesses=guesses)
        return await self._call(submit_phase_guesses, phase_guess=submission)

    async def _score(self, guess_id: str, grid_id: str):
        self.last_queried_grid = grid_id
        self._record("get_phase_score", grid_id=grid_id)
        return await self._call(get_score, guess_id=guess_id, grid_id=grid_id)

    async def handle(self, tool_name: str, tool_args: dict):
        if tool_name == "get_training_phase_data":
            return await self._training(difficulty=tool_args.get("difficulty", "clean"))
        elif tool_name == "get_phase_identification_data":
            return await self._test(difficulty=tool_args.get("difficulty", "clean"))
        elif tool_name == "submit_phase_guesses":
            return await self._submit(
                guess_id=tool_args["guess_id"], grid_id=tool_args["grid_id"], guesses=tool_args["guesses"],
            )
        elif tool_name == "get_phase_score":
            return await self._score(guess_id=tool_args["guess_id"], grid_id=tool_args["grid_id"])
        return await super().handle(tool_name, tool_args)
