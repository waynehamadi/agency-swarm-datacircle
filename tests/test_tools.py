"""Offline tests: the tools against a local stand-in for the API on 127.0.0.1, by their own run, by their plain
functions, as Agency Swarm adapts them (an Agent's FunctionTools) and run by an Agency's own loop on a scripted Chat
Completions model, also on 127.0.0.1."""

import asyncio
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")  # no trace of a test is sent to OpenAI
os.environ.setdefault("OPENAI_API_KEY", "unused")

import pytest
from agency_swarm import Agency, Agent, function_tool
from agents import FunctionTool, OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from pydantic import ValidationError

import agency_swarm_datacircle as dc
from agency_swarm_datacircle import (TOOL_NAMES, datacircle_best_plans, DatacircleError, datacircle_list_apis,
                                     datacircle_provider, datacircle_search_plans, datacircle_tools)
from agency_swarm_datacircle import _api

PLAN = {"api": "Employee email", "rank": 1, "provider": "Hunter", "plan": "Starter", "score": 80.1, "perThousand": 4.9,
        "page": "https://datacircle.dev/x", "terms": "long", "aggregators": ["a"]}
BRIEF = {key: value for key, value in PLAN.items() if key not in ("terms", "aggregators")}
SEEN = []
BUSY = []
ASKED: List[Dict[str, Any]] = []


class Handler(BaseHTTPRequestHandler):
    """The API's stand-in on GET, the scripted model's on POST /v1/chat/completions: the last user message's
    `CALL <tool> <json>` lines are the calls it asks for, then `done` once the request holds their results."""

    def log_message(self, *args):
        pass

    def reply(self, status, body, headers=None):
        data = json.dumps(body).encode()
        self.send_response(status)
        for key, value in {"Content-Type": "application/json", "Content-Length": str(len(data)), **(headers or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        SEEN.append((url.path, query, self.headers.get("User-Agent")))
        if url.path == "/v1/plans" and query.get("query") == "busy" and not BUSY:
            BUSY.append(1)
            return self.reply(429, {"error": "slow down"}, {"Retry-After": "1"})
        if url.path == "/v1/apis":
            return self.reply(200, [{"api": "Employee email", "slug": "email-finder", "plans": 9, "providers": 3, "extra": 1},
                                    {"api": "Employee profile", "slug": "linkedin-profile", "plans": 4, "providers": 2}])
        if url.path == "/v1/apis/email-finder/best":
            return self.reply(200, {"api": "Employee email", "slug": "email-finder", "total": 1, "plans": [PLAN]})
        if url.path.startswith("/v1/apis/"):
            return self.reply(404, {"error": "no API has the slug nope", "slugs": ["email-finder", "linkedin-profile"]})
        if url.path == "/v1/plans" and query.get("query") == "down":
            return self.reply(503, {"error": "down for a minute"})
        if url.path == "/v1/plans":
            return self.reply(200, {"total": 1, "offset": 0, "plans": [PLAN]})
        if url.path == "/v1/providers/bright-data":
            return self.reply(200, {"provider": "Bright Data", "slug": "bright-data", "website": "https://brightdata.com",
                                    "apis": [{"api": "Employee email", "slug": "email-finder", "rank": 7, "sheetPage": "s",
                                              "plans": [dict(PLAN, rank=9, plan="B"), dict(PLAN, rank=7, plan="A")]}]})
        return self.reply(404, {"error": "no provider has this slug"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        ASKED.append(body)
        messages = body.get("messages", [])
        last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
        said = messages[last_user].get("content") if last_user >= 0 else ""
        said = said if isinstance(said, str) else " ".join(part.get("text", "") for part in said)
        answered = any(m.get("role") == "tool" for m in messages[last_user + 1:])
        calls = [] if answered else re.findall(r"CALL (\w+) (\{.*?\})\s*$", said, re.M)
        message = {"role": "assistant", "content": None if calls else "done"}
        if calls:
            message["tool_calls"] = [{"id": f"call_{len(ASKED)}_{i}", "type": "function",
                                      "function": {"name": name, "arguments": arguments}}
                                     for i, (name, arguments) in enumerate(calls)]
        self.reply(200, {"id": f"chatcmpl-{len(ASKED)}", "object": "chat.completion", "created": 0, "model": "scripted",
                         "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


@pytest.fixture(scope="module", autouse=True)
def stand_in():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    before = _api.BASE_URL
    _api.BASE_URL = f"http://127.0.0.1:{server.server_address[1]}/v1"
    yield
    _api.BASE_URL = before
    server.shutdown()


def scripted() -> OpenAIChatCompletionsModel:
    return OpenAIChatCompletionsModel(model="scripted", openai_client=AsyncOpenAI(base_url=_api.BASE_URL, api_key="scripted"))


def outputs(message: str, tools: List[Any]) -> Dict[str, Any]:
    """An Agency's own turn on the scripted model: each tool's output as Agency Swarm gave it the model, by its name."""
    ASKED.clear()
    agency = Agency(Agent(name="Researcher", instructions="Find the best GTM APIs.", tools=tools, model=scripted()))
    result = asyncio.run(agency.get_response(message))
    assert result.final_output == "done"
    calls = {}
    for body in ASKED:
        for m in body.get("messages", []):
            for call in m.get("tool_calls") or []:
                calls[call["id"]] = call["function"]["name"]
    given = {calls[m["tool_call_id"]]: m["content"] for m in ASKED[-1]["messages"] if m.get("role") == "tool"}
    return {name: json.loads(text) if text.startswith("{") else text for name, text in given.items()}


def test_the_tools_as_agency_swarm_adapts_them():
    tools = Agent(name="Researcher", instructions="x", tools=datacircle_tools()).tools
    assert [t.name for t in tools] == TOOL_NAMES and all(isinstance(t, FunctionTool) for t in tools)
    for t in tools:
        assert "https://datacircle.dev" in t.description and "\n" not in t.description
        assert t.params_json_schema["type"] == "object" and t.params_json_schema["additionalProperties"] is False
    by_name = {t.name: t.params_json_schema for t in tools}
    assert by_name["datacircle_best_plans"]["required"] == ["slug"] and by_name["datacircle_provider"]["required"] == ["slug"]
    assert not by_name["datacircle_list_apis"].get("required") and not by_name["datacircle_search_plans"].get("required")
    search = by_name["datacircle_search_plans"]["properties"]
    assert search["sort"]["enum"] == ["score", "provider", "price"] and search["sort"]["default"] == "score"
    assert {key: search["limit"][key] for key in ("type", "minimum", "maximum", "default")} == \
        {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}
    assert datacircle_tools(["datacircle_provider", "datacircle_list_apis"]) == [datacircle_provider, datacircle_list_apis]
    assert datacircle_tools([]) == []
    with pytest.raises(ValueError, match="its tools are datacircle_list_apis"):
        datacircle_tools(["DatacircleNope"])
    with pytest.raises(TypeError):
        datacircle_tools("datacircle_provider")


def test_each_tool_by_its_own_run_and_by_its_function():
    SEEN.clear()
    assert json.loads(datacircle_list_apis(query="profile").run()) == \
        {"total": 1, "apis": [{"api": "Employee profile", "slug": "linkedin-profile", "plans": 4, "providers": 2}]}
    assert json.loads(datacircle_list_apis(limit=1).run())["apis"][0]["slug"] == "email-finder"
    assert json.loads(datacircle_best_plans(slug="Email Finder", limit=3).run())["plans"] == [BRIEF]
    found = json.loads(datacircle_search_plans(query="hunter", sort="Price", limit="2", unknown=1).run())
    assert found["total"] == 1 and "terms" not in found["plans"][0]
    assert json.loads(datacircle_provider(slug="Bright Data").run())["apis"] == \
        [{"api": "Employee email", "slug": "email-finder", "rank": 7, "plans": 2,
          "best": {"plan": "A", "score": 80.1, "perThousand": 4.9, "page": "https://datacircle.dev/x"}}]
    assert dc.best_plans("email-finder", limit="2")["slug"] == "email-finder"
    assert ("/v1/apis/email-finder/best", {"limit": "3"}, _api.USER_AGENT) in SEEN
    assert ("/v1/plans", {"query": "hunter", "sort": "price", "limit": "2", "offset": "0"}, _api.USER_AGENT) in SEEN
    assert _api.USER_AGENT == f"agency-swarm-datacircle/{dc.__version__}"


def test_refusals_in_the_apis_words_and_the_tools():
    SEEN.clear()
    words = json.loads(datacircle_best_plans(slug="nope").run())["error"]
    assert "answered 404: no API has the slug nope; the slugs: email-finder, linkedin-profile" in words
    assert json.loads(datacircle_search_plans(query="down").run()) == {"error": "Datacircle's API answered 503: down for a minute"}
    SEEN.clear()
    for build, said in [(lambda: datacircle_search_plans(limit=0), "limit must be from 1 to 50, not 0"),
                        (lambda: datacircle_search_plans(limit="many"), "limit must be a whole number, not 'many'"),
                        (lambda: datacircle_search_plans(sort="cheapest"), "sort must be score, provider or price, not 'cheapest'"),
                        (lambda: datacircle_list_apis(limit=2.5), "limit must be a whole number, not 2.5"),
                        (lambda: datacircle_provider(), "Give a provider's slug or name"),
                        (lambda: datacircle_best_plans(slug=" !! "), "Give an API's slug")]:
        with pytest.raises(ValidationError, match=re.escape(said)):
            build()
    assert not SEEN  # refused before any call
    with pytest.raises(DatacircleError) as raised:
        dc.search_plans(query="down")
    assert raised.value.status == 503 and raised.value.retryable


def test_a_429_is_waited_once():
    BUSY.clear()
    assert json.loads(datacircle_search_plans(query="busy").run())["total"] == 1 and BUSY == [1]


def test_the_agency_runs_each_tool():
    given = outputs('Which email finder API is best?\nCALL datacircle_list_apis {"query": "email", "limit": 1}\n'
                    'CALL datacircle_best_plans {"slug": "email-finder", "limit": 3}\n'
                    'CALL datacircle_search_plans {"query": "hunter", "sort": "score"}\n'
                    'CALL datacircle_provider {"slug": "Bright Data"}', datacircle_tools())
    assert sorted(given) == sorted(TOOL_NAMES)
    assert given["datacircle_list_apis"]["apis"][0]["slug"] == "email-finder"
    assert given["datacircle_best_plans"]["plans"] == [BRIEF] and given["datacircle_search_plans"]["plans"] == [BRIEF]
    assert given["datacircle_provider"]["provider"] == "Bright Data"


def test_the_agency_gives_refusals_to_the_model():
    SEEN.clear()
    given = outputs('CALL datacircle_best_plans {"slug": "nope"}\nCALL datacircle_search_plans {"limit": 100, "query": 7}',
                    datacircle_tools())
    assert "the slugs: email-finder" in given["datacircle_best_plans"]["error"]
    assert "limit must be from 1 to 50, not 100" in given["datacircle_search_plans"]
    assert not [seen for seen in SEEN if seen[0] == "/v1/plans"]


def test_beside_an_apps_own_tool_and_one_tool_alone():
    @function_tool
    def weekday(date: str) -> str:
        """The day of the week of a date."""
        return "Tuesday"

    given = outputs('CALL weekday {"date": "2026-11-25"}\nCALL datacircle_best_plans {"slug": "email-finder"}',
                    [weekday, *datacircle_tools()])
    assert given["weekday"] == "Tuesday" and given["datacircle_best_plans"]["plans"] == [BRIEF]
    given = outputs('CALL datacircle_provider {"slug": "bright-data"}', [datacircle_provider])
    assert given["datacircle_provider"]["provider"] == "Bright Data"
