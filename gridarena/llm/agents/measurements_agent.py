from gridarena.llm.base_agent import BaseAgent
from gridarena.routers.measurements import (
    delete_measurements,
    get_measurements_data,
)


class MeasurementsAgent(BaseAgent):

    async def _delete(self, grid_id: str, node_id=None, phase=None, start=None, end=None, confirmed: bool = False):
        self._record("delete_measurements", grid_id=grid_id)
        if not confirmed:
            return {"error": {
                "type": "confirmation_required",
                "detail": "Ask the user to confirm the deletion, then retry with confirmed=true.",
            }}
        return await self._call(
            delete_measurements,
            grid_id=grid_id, node_id=node_id, phase=phase, start=start, end=end,
        )

    async def _get(self, grid_id: str, node_id=None, start=None, end=None,
                   per_phase: bool = True, phase=None):
        self.last_queried_grid = grid_id
        self._record("get_measurements_data", grid_id=grid_id)
        return await self._call(
            get_measurements_data,
            grid_id=grid_id, node_id=node_id, start=start, end=end,
            per_phase=per_phase, phase=phase,
        )

    async def handle(self, tool_name: str, tool_args: dict):
        if tool_name == "delete_measurements":
            return await self._delete(
                grid_id=tool_args["grid_id"],
                node_id=tool_args.get("node_id"),
                phase=tool_args.get("phase"),
                start=tool_args.get("start"),
                end=tool_args.get("end"),
                confirmed=tool_args.get("confirmed") is True,
            )
        elif tool_name == "get_measurements_data":
            return await self._get(
                grid_id=tool_args["grid_id"],
                node_id=tool_args.get("node_id"),
                start=tool_args.get("start"),
                end=tool_args.get("end"),
                per_phase=tool_args.get("per_phase", True),
                phase=tool_args.get("phase"),
            )
        return await super().handle(tool_name, tool_args)
