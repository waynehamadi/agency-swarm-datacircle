"""Agency Swarm tools for Datacircle's open API (https://api.datacircle.dev/v1): find the best GTM APIs. No key, no account.

    from agency_swarm import Agent
    from agency_swarm_datacircle import datacircle_tools

    agent = Agent(name="Researcher", instructions="...", tools=datacircle_tools())
"""

from agency_swarm_datacircle._api import BASE_URL, DatacircleError
from agency_swarm_datacircle.tools import (
    TOOLS,
    TOOL_NAMES,
    best_plans,
    datacircle_best_plans,
    datacircle_list_apis,
    datacircle_provider,
    datacircle_search_plans,
    datacircle_tools,
    list_apis,
    provider,
    search_plans,
)

__version__ = "0.1.0"

__all__ = [
    "BASE_URL",
    "TOOL_NAMES",
    "TOOLS",
    "best_plans",
    "datacircle_best_plans",
    "datacircle_list_apis",
    "datacircle_provider",
    "datacircle_search_plans",
    "datacircle_tools",
    "DatacircleError",
    "list_apis",
    "provider",
    "search_plans",
]
