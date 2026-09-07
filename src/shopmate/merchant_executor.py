"""Host retail reads and search with task-wide budget failures preserved."""

from commerce_common.streaming import ToolOutcome
from merchant_agent.executor import MerchantToolExecutor
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .analysis_sandbox import SandboxCleanupError
from .provider import TaskBudgetExceeded
from .search_tool import execute_search
from .web_search import SearchUnavailable


class RecentOrdersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    limit: int = Field(default=6, ge=1, le=50)


RECENT_ORDERS_TOOL = {
    "name": "get_recent_orders",
    "description": (
        "Read this store's most recent standard and seckill SKU orders, ordered by creation "
        "time (newest first), including orders newer than report_as_of. This is a live order "
        "feed, not paid-period sales. Amounts are integer minor currency units; preserve "
        "payment, refund and fulfillment states separately. An absent payment or fulfillment "
        "record is unknown, and a requested refund is not money returned. If the fenced "
        "output is truncated, request fewer orders; do not infer whole-store totals."
    ),
    "input_schema": RecentOrdersRequest.model_json_schema(),
}


class RetailMerchantExecutor(MerchantToolExecutor):
    def handlers(self):
        return super().handlers() | {
            "web_search": self._web_search,
            "get_recent_orders": self._get_recent_orders,
        }

    async def _get_recent_orders(self, arguments):
        try:
            limit = RecentOrdersRequest.model_validate(arguments).limit
        except ValidationError:
            return ToolOutcome.error("Recent orders accepts only an integer limit from 1 to 50")
        orders = await self._backend.get_recent_orders(self._session, limit=limit)
        return self._fenced([order.model_dump(mode="json") for order in orders])

    async def _web_search(self, arguments):
        return await execute_search(self, arguments)

    def domain_error(self, error):
        if isinstance(error, (TaskBudgetExceeded, SandboxCleanupError)):
            raise error
        if isinstance(error, SearchUnavailable):
            return ToolOutcome.error(str(error))
        return super().domain_error(error)
