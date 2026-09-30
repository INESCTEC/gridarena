from gridarena.llm.base_agent import BaseAgent
from gridarena.routers.powerflow import get_power_flow_results, run_power_flow


class PowerflowAgent(BaseAgent):

    async def _run(self, grid_id: str, phase: str, start_time=None, end_time=None):
        self.last_queried_grid = grid_id
        self._record("run_power_flow", grid_id=grid_id, phase=phase)
        return await self._call(
            run_power_flow,
            grid_id=grid_id, phase=phase, start_time=start_time, end_time=end_time,
        )

    async def _results(self, grid_id: str, phase: str):
        self.last_queried_grid = grid_id
        self._record("get_power_flow_results", grid_id=grid_id, phase=phase)
        return await self._call(get_power_flow_results, grid_id=grid_id, phase=phase)

    async def handle(self, tool_name: str, tool_args: dict):
        if tool_name == "run_power_flow":
            return await self._run(
                grid_id=tool_args["grid_id"], phase=tool_args["phase"],
                start_time=tool_args.get("start_time"), end_time=tool_args.get("end_time"),
            )
        elif tool_name == "get_power_flow_results":
            return await self._results(grid_id=tool_args["grid_id"], phase=tool_args["phase"])
        return await super().handle(tool_name, tool_args)
