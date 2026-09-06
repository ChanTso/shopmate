"""Host search support with task-wide budget failures preserved."""

from commerce_common.streaming import ToolOutcome
from merchant_agent.executor import MerchantToolExecutor

from .analysis_sandbox import SandboxCleanupError
from .provider import TaskBudgetExceeded
from .search_tool import execute_search
from .web_search import SearchUnavailable


class RetailMerchantExecutor(MerchantToolExecutor):
    def handlers(self):
        return super().handlers() | {"web_search": self._web_search}

    async def _web_search(self, arguments):
        return await execute_search(self, arguments)

    def domain_error(self, error):
        if isinstance(error, (TaskBudgetExceeded, SandboxCleanupError)):
            raise error
        if isinstance(error, SearchUnavailable):
            return ToolOutcome.error(str(error))
        return super().domain_error(error)
