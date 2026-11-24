"""Agency Swarm tools on Datacircle's open API, https://api.datacircle.dev/v1: no key, no account.

Each tool is a BaseTool class: Agent(tools=[...]) takes the class, Agency Swarm makes the tool's schema from its fields
and its description (its docstring, one line, as Agency Swarm gives the model the docstring as it is) and runs it when
the model calls it. Agency Swarm names a tool by its class's name, and a call to a name it has not ends the run, so each
class is named in snake_case: asked for a provider's plans, gpt-oss:120b called DatacircleSearchPlans
datacircleSearchPlans in 10 runs of 11. A tool makes one HTTPS GET, in a thread as Agency Swarm runs a plain run(), and
gives the model the API's answer as JSON text. A refusal of the API (an unknown slug, the API out of reach) is {"error":
the API's words}, so the model can call again. An argument the API can't take is refused before any call by the tool's
own checks, each a ValueError in its own words: Agency Swarm gives the model a value error's words, and since 2.0 hides
pydantic's others.
"""

import json
import urllib.parse
from collections.abc import Callable, Iterable
from typing import Any, Dict, List, Literal, Optional

from agency_swarm.tools import BaseTool
from pydantic import Field, field_validator, model_validator

from agency_swarm_datacircle import _api


def _best(plans: Any) -> Optional[Dict[str, Any]]:
    """A provider's best plan on an API: its lowest rank, a plan with no score having none."""
    ranked = sorted(plans, key=lambda plan: plan.get("rank") if isinstance(plan.get("rank"), (int, float)) else float("inf"))
    return _api.brief(ranked[0], ["plan", "score", "perThousand", "page"]) if ranked else None


def list_apis(query: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    count = _api.whole("limit", limit, 1, 200) or 20
    apis = _api.get("/apis")
    words = [word for word in str(query or "").lower().replace("-", " ").split() if word]
    held = []
    for index, api in enumerate(apis):
        name = f"{api.get('api', '')} {str(api.get('slug', '')).replace('-', ' ')}".lower()
        matched = sum(word in name for word in words)
        if matched or not words:
            held.append((-matched, index, api))
    found = [_api.brief(api, _api.API_KEYS) for _, _, api in sorted(held, key=lambda h: h[:2])]
    return {"total": len(found), "apis": found[:count]}


def best_plans(slug: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    made = _api.slug(slug)
    if not made:
        raise _api.DatacircleError("Give an API's slug, like 'email-finder': datacircle_list_apis gives every slug")
    answer = _api.get(f"/apis/{urllib.parse.quote(made)}/best", {"limit": _api.whole("limit", limit, 1, 50)})
    return {**answer, "plans": [_api.brief(plan) for plan in answer.get("plans") or []]}


def search_plans(api: Optional[str] = None, query: Optional[str] = None, sort: Optional[str] = None,
                 limit: Optional[int] = None, offset: Optional[int] = None) -> Dict[str, Any]:
    order = str(sort).strip().lower() if sort not in (None, "") else None
    if order is not None and order not in ("score", "provider", "price"):
        raise _api.DatacircleError(f"sort must be score, provider or price, not {sort!r}")
    params = {"api": api, "query": query, "sort": order, "limit": _api.whole("limit", limit, 1, 50),
              "offset": _api.whole("offset", offset, 0)}
    answer = _api.get("/plans", params)
    return {**answer, "plans": [_api.brief(plan) for plan in answer.get("plans") or []]}


def provider(slug: Optional[str] = None) -> Dict[str, Any]:
    made = _api.slug(slug)
    if not made:
        raise _api.DatacircleError("Give a provider's slug or name, like 'bright-data' or 'Bright Data'")
    answer = _api.get(f"/providers/{urllib.parse.quote(made)}")
    apis = [{**_api.brief(entry, ["api", "slug", "rank", "bestPage"]), "plans": len(entry.get("plans") or []),
             "best": _best(entry.get("plans") or [])} for entry in answer.get("apis") or []]
    return {**answer, "apis": apis}


def _answer(make: Callable[[], Dict[str, Any]]) -> str:
    """What a tool gives the model: the answer as JSON text, or {"error": the API's words}."""
    try:
        return json.dumps(make(), ensure_ascii=False)
    except _api.DatacircleError as error:
        return json.dumps({"error": str(error)}, ensure_ascii=False)


def _whole(name: str, low: int, high: Optional[int], default: int) -> Any:
    """A check of a whole-number field before pydantic's: its default for null, a number sent as text taken, the rest
    refused in the tool's words."""
    def check(cls: Any, value: Any) -> int:
        try:
            number = _api.whole(name, value, low, high)
        except _api.DatacircleError as error:
            raise ValueError(str(error)) from None
        return default if number is None else number
    return field_validator(name, mode="before")(check)


def _text(name: str) -> Any:
    """A check of a text field before pydantic's: null is left out, a number made text."""
    def check(cls: Any, value: Any) -> str:
        return "" if value is None else str(value)
    return field_validator(name, mode="before")(check)


def _needed(field: str, words: str) -> Any:
    """A slug the model left out or sent with no letter or digit, refused in the tool's words, never pydantic's."""
    def check(cls: Any, data: Any) -> Any:
        if isinstance(data, dict) and not _api.slug(data.get(field)):
            raise ValueError(words)
        return data
    return model_validator(mode="before")(check)


_PRICE = "perThousand is a plan's price of 1,000 items in dollars, pay the plan's whole price in its currency."
_LIMIT = "How many plans to give, 1 to 50."


class datacircle_list_apis(BaseTool):
    __doc__ = ("Lists the GTM APIs on Datacircle's sheet (https://datacircle.dev), with each API's slug, how many plans "
               "and providers it has and its best plan. Call it first to find an API's slug. Gives total, the APIs "
               "found, and apis, up to limit of them.")

    query: str = Field("", description="Words of the API's name or slug, like 'email' or 'linkedin profile': the APIs "
                                       "that hold the most of them come first. The sheet's order when left out.")
    limit: int = Field(20, ge=1, le=200, description="How many APIs to give, 1 to 200: the sheet has about 160.")

    check_query = _text("query")
    check_limit = _whole("limit", 1, 200, 20)

    def run(self) -> str:
        return _answer(lambda: list_apis(self.query, self.limit))


class datacircle_best_plans(BaseTool):
    __doc__ = ("Gives an API's plans best first by their score out of 100 on Datacircle's benchmark "
               "(https://datacircle.dev), each with its rank, provider, plan, $ per 1,000 calls and its page: the best "
               "providers of an API. " + _PRICE)

    slug: str = Field(..., description="The API's slug, like 'email-finder' or 'linkedin-profile', as "
                                       "datacircle_list_apis gives it.")
    limit: int = Field(10, ge=1, le=50, description=_LIMIT)

    check_given = _needed("slug", "Give an API's slug, like 'email-finder': datacircle_list_apis gives every slug")
    check_slug = _text("slug")
    check_limit = _whole("limit", 1, 50, 10)

    def run(self) -> str:
        return _answer(lambda: best_plans(self.slug, self.limit))


class datacircle_search_plans(BaseTool):
    __doc__ = ("Searches every plan on Datacircle's sheet (https://datacircle.dev), or one API's, by provider or plan "
               "name, sorted by score, provider or price. Gives total, offset and up to limit plans. " + _PRICE)

    api: str = Field("", description="Only this API's plans: its name or slug, like 'email-finder'. A provider's name "
                                     "goes in query, never here. Every API when left out.")
    query: str = Field("", description="Words that must all appear in the provider's or plan's name, like 'bright data'.")
    sort: Literal["score", "provider", "price"] = Field(
        "score", description="score (best first), provider (A to Z) or price ($ per 1,000, lowest first).")
    limit: int = Field(10, ge=1, le=50, description=_LIMIT)
    offset: int = Field(0, ge=0, description="How many found plans to skip first.")

    check_api = _text("api")
    check_query = _text("query")
    check_limit = _whole("limit", 1, 50, 10)
    check_offset = _whole("offset", 0, None, 0)

    @field_validator("sort", mode="before")
    @classmethod
    def check_sort(cls, value: Any) -> str:
        order = "score" if value in (None, "") else str(value).strip().lower()
        if order not in ("score", "provider", "price"):
            raise ValueError(f"sort must be score, provider or price, not {value!r}")
        return order

    def run(self) -> str:
        return _answer(lambda: search_plans(self.api, self.query, self.sort, self.limit, self.offset))


class datacircle_provider(BaseTool):
    __doc__ = ("Gives each API one provider sells and its rank on each on Datacircle's benchmark "
               "(https://datacircle.dev), with its best plan there.")

    slug: str = Field(..., description="The provider's slug, like 'bright-data', or its name, like 'Bright Data': the "
                                       "name is made a slug.")

    check_given = _needed("slug", "Give a provider's slug or name, like 'bright-data' or 'Bright Data'")
    check_slug = _text("slug")

    def run(self) -> str:
        return _answer(lambda: provider(self.slug))


TOOLS = [datacircle_list_apis, datacircle_best_plans, datacircle_search_plans, datacircle_provider]
TOOL_NAMES = [tool.__name__ for tool in TOOLS]


def datacircle_tools(names: Optional[Iterable[str]] = None) -> List[type]:
    """The tools named, in their order, or all four: BaseTool classes, for an Agent's tools beside an app's own."""
    if isinstance(names, str):
        raise TypeError("names is a list of tool names, like ['datacircle_best_plans']")
    tools = dict(zip(TOOL_NAMES, TOOLS))
    chosen = TOOL_NAMES if names is None else list(names)
    unknown = [name for name in chosen if name not in tools]
    if unknown:
        raise ValueError(f"Datacircle has no tool {unknown[0]!r}: its tools are {', '.join(TOOL_NAMES)}")
    return [tools[name] for name in chosen]
