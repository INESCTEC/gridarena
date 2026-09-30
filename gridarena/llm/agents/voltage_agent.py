import gridarena.schemas as sc
from gridarena.llm.base_agent import BaseAgent
from gridarena.routers.voltage_control_benchmark import (
    get_score,
    get_training_voltage_control_data,
    get_voltage_control_data,
    submit_voltage_control_guesses,
)


class VoltageAgent(BaseAgent):

    async def _training(self, voltage_limit: float, scenario: str = "Overvoltages", difficulty: str = "clean"):
        self._record("get_training_voltage_control_data")
        return await self._call(
            get_training_voltage_control_data,
            voltage_limit=voltage_limit, Scenario=scenario, difficulty=difficulty,
        )

    async def _test(self, voltage_limit: float, scenario: str = "Overvoltages", difficulty: str = "clean"):
        self._record("get_voltage_control_data")
        return await self._call(
            get_voltage_control_data,
            voltage_limit=voltage_limit, Scenario=scenario, difficulty=difficulty,
        )

    async def _submit(self, guess_id: str, grid_id: str, guesses: dict):
        self.last_queried_grid = grid_id
        self._record("submit_voltage_control_guesses", grid_id=grid_id)
        submission = sc.VCGuessSubmission(guess_id=guess_id, grid_id=grid_id, guesses=guesses)
        return await self._call(submit_voltage_control_guesses, vc_guess=submission)

    async def _score(self, guess_id: str, grid_id: str):
        self.last_queried_grid = grid_id
        self._record("get_voltage_control_score", grid_id=grid_id)
        return await self._call(get_score, guess_id=guess_id, grid_id=grid_id)

    async def handle(self, tool_name: str, tool_args: dict):
        if tool_name == "get_training_voltage_control_data":
            return await self._training(
                voltage_limit=tool_args["voltage_limit"],
                scenario=tool_args.get("scenario", "Overvoltages"),
                difficulty=tool_args.get("difficulty", "clean"),
            )
        elif tool_name == "get_voltage_control_data":
            return await self._test(
                voltage_limit=tool_args["voltage_limit"],
                scenario=tool_args.get("scenario", "Overvoltages"),
                difficulty=tool_args.get("difficulty", "clean"),
            )
        elif tool_name == "submit_voltage_control_guesses":
            return await self._submit(
                guess_id=tool_args["guess_id"], grid_id=tool_args["grid_id"], guesses=tool_args["guesses"],
            )
        elif tool_name == "get_voltage_control_score":
            return await self._score(guess_id=tool_args["guess_id"], grid_id=tool_args["grid_id"])
        return await super().handle(tool_name, tool_args)
