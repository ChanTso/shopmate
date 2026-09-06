"""The same external research tool for both authenticated retail roles."""

from commerce_common.streaming import AgentEvent, ToolOutcome
from pydantic import ValidationError

from .web_search import SearchQuery


async def execute_search(executor, arguments):
    try:
        query = SearchQuery.model_validate(arguments).query
    except ValidationError:
        return ToolOutcome.error("Web search needs only a public query of 1 to 1000 characters")
    executor._backend._bound(executor._session)
    evidence = await executor._backend.web_search.search(query)
    return executor._fenced(evidence, [AgentEvent.ui("web_sources", evidence)])
