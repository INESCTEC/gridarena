import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class BaseAgent:
    """Base class for all LLM tool agents."""

    def __init__(self):
        self.last_queried_grid: Optional[str] = None
        self.query_history: list[dict] = []

    def _record(self, action: str, **kwargs):
        self.query_history.append({"action": action, **kwargs})

    async def _call(self, func, *args, **kwargs) -> Any:
        """Invoke a router function. Failures are returned to the model as data, never hidden."""
        try:
            return await func(*args, **kwargs)
        except HTTPException as e:
            logger.info("Tool %s returned HTTP %s: %s", func.__name__, e.status_code, e.detail)
            return {"error": {"type": "http_error", "status": e.status_code, "detail": e.detail}}
        except TypeError as e:
            logger.error("Tool %s called with wrong arguments: %s", func.__name__, e, exc_info=True)
            return {"error": {"type": "internal_error",
                               "detail": "This tool is misconfigured on the server and cannot be used."}}
        except Exception:
            logger.error("Tool %s failed", func.__name__, exc_info=True)
            return {"error": {"type": "internal_error",
                               "detail": "The operation failed. See server logs."}}

    async def handle(self, tool_name: str, tool_args: Dict) -> Any:
        raise NotImplementedError(f"{type(self).__name__} has no handler for {tool_name}")
