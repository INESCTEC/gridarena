from gridarena.llm.base_agent import BaseAgent
from gridarena.routers.grid import delete_grid, get_grid


class GridAgent(BaseAgent):

    async def get_grid_data(self, grid_id: str, table: str):
        self.last_queried_grid = grid_id
        self._record("get_grid_data", grid_id=grid_id, table=table)
        return await self._call(get_grid, grid_id=grid_id, table=table)

    async def _delete_grid(self, grid_id: str, confirmed: bool = False):
        self._record("delete_grid", grid_id=grid_id)
        if not confirmed:
            return {"error": {
                "type": "confirmation_required",
                "detail": "Ask the user to confirm the deletion, then retry with confirmed=true.",
            }}
        return await self._call(delete_grid, grid_id=grid_id)

    async def handle(self, tool_name: str, tool_args: dict):
        if tool_name == "get_grid_data":
            return await self.get_grid_data(grid_id=tool_args["grid_id"], table=tool_args["table"])
        elif tool_name == "delete_grid":
            return await self._delete_grid(
                grid_id=tool_args["grid_id"], confirmed=tool_args.get("confirmed") is True,
            )
        return await super().handle(tool_name, tool_args)
