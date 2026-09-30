from gridarena.llm.base_agent import BaseAgent
from gridarena.routers.historical import (
    delete_historical_database,
    delete_historical_series_records,
    get_historical_series_data,
)


class HistoricalAgent(BaseAgent):

    async def _delete_database(self, database_id: str, confirmed: bool = False):
        self._record("delete_historical_database", database_id=database_id)
        if not confirmed:
            return {"error": {
                "type": "confirmation_required",
                "detail": "Ask the user to confirm the deletion, then retry with confirmed=true.",
            }}
        return await self._call(delete_historical_database, database_id=database_id)

    async def _delete_series_records(
        self, database_id: str, series_id: str, phase=None, start=None, end=None, confirmed: bool = False,
    ):
        self._record("delete_historical_series_records", database_id=database_id, series_id=series_id)
        if not confirmed:
            return {"error": {
                "type": "confirmation_required",
                "detail": "Ask the user to confirm the deletion, then retry with confirmed=true.",
            }}
        return await self._call(
            delete_historical_series_records,
            database_id=database_id, series_id=series_id, phase=phase, start=start, end=end,
        )

    async def _get(self, database_id: str, series_id: str, start=None, end=None, phase=None):
        self._record("get_historical_series_data", database_id=database_id, series_id=series_id)
        return await self._call(
            get_historical_series_data,
            database_id=database_id, series_id=series_id, start=start, end=end, phase=phase,
        )

    async def handle(self, tool_name: str, tool_args: dict):
        if tool_name == "delete_historical_database":
            return await self._delete_database(
                database_id=tool_args["database_id"], confirmed=tool_args.get("confirmed") is True,
            )
        elif tool_name == "delete_historical_series_records":
            return await self._delete_series_records(
                database_id=tool_args["database_id"],
                series_id=tool_args["series_id"],
                phase=tool_args.get("phase"),
                start=tool_args.get("start"),
                end=tool_args.get("end"),
                confirmed=tool_args.get("confirmed") is True,
            )
        elif tool_name == "get_historical_series_data":
            return await self._get(
                database_id=tool_args["database_id"],
                series_id=tool_args["series_id"],
                start=tool_args.get("start"),
                end=tool_args.get("end"),
                phase=tool_args.get("phase"),
            )
        return await super().handle(tool_name, tool_args)
