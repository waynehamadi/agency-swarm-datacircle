# agency-swarm-datacircle

Find the best GTM APIs. We benchmark all the GTM APIs and we put the results on our website.

Our website: https://datacircle.dev

This package gives [Agency Swarm](https://github.com/VRSEN/agency-swarm) four tools that call Datacircle's public API, https://api.datacircle.dev/v1. You need no key and no account.

| Tool | Gives | Call |
| --- | --- | --- |
| `datacircle_list_apis` | Every GTM API on Datacircle, with the API's slug, number of plans, number of providers and best plan | `GET /apis` |
| `datacircle_best_plans` | One API's plans, sorted by score out of 100, best first. Each plan comes with a rank and a price per 1,000 calls | `GET /apis/{slug}/best` |
| `datacircle_search_plans` | Plans that match a provider or plan name, on all APIs or on one API. You can sort them by score, provider or price | `GET /plans` |
| `datacircle_provider` | The APIs a provider sells, and the provider's rank on each API | `GET /providers/{slug}` |

## Install

```bash
pip install agency-swarm-datacircle
```

The package needs Agency Swarm 1.0 or later and Python 3.12 or later.

## Give the tools to an agent

```python
import asyncio

from agency_swarm import Agency, Agent
from agency_swarm_datacircle import datacircle_tools

researcher = Agent(
    name="Researcher",
    description="Finds the best GTM APIs.",
    instructions="You find the best GTM APIs with Datacircle's tools.",
    tools=datacircle_tools(),
)
agency = Agency(researcher)


async def main() -> None:
    response = await agency.get_response("Which email finder API is best for under $5 per 1,000?")
    print(response.final_output)


asyncio.run(main())
```

Each tool is a `BaseTool` class. Agency Swarm names each tool after the tool's class. Models call snake_case names best, so the classes have snake_case names. The model picks a tool. Agency Swarm runs the tool and gives the model the tool's result.

To add the tools beside your own, list them: `tools=[my_tool, *datacircle_tools()]`.

To give only some of the tools, name them: `datacircle_tools(["datacircle_best_plans"])`. You can also list the classes: `tools=[datacircle_best_plans]`.

To share the tools with every agent of an agency, pass them to `Agency(..., shared_tools=datacircle_tools())`. `shared_tools` needs Agency Swarm 1.7 or later.

## Call a tool yourself

`run()` returns a tool's output for the model, as JSON text:

```python
from agency_swarm_datacircle import datacircle_best_plans

print(datacircle_best_plans(slug="email-finder", limit=3).run())
```

The functions `list_apis`, `best_plans`, `search_plans` and `provider` return each tool's output as Python dicts.

## Serve the tools

Agency Swarm can serve the Datacircle tools without an agent:

- As an MCP server: `run_mcp(tools=datacircle_tools(), transport="stdio")`, from `agency_swarm.integrations.mcp_server`.
- As HTTP endpoints at `POST /tool/<name>`: `run_fastapi(tools=datacircle_tools())`, from `agency_swarm.integrations.fastapi`.

The HTTP endpoints and the MCP server over HTTP bind to `0.0.0.0` unless you pass `host`. Over stdio, the MCP server binds to no port.

## Tool output for the model

Each result is our API's answer as JSON text. Each plan comes with a rank, provider, plan, score, price per 1,000 (`perThousand`, in dollars) and a page on datacircle.dev. That page lists every field.

You can give a provider's name in place of a slug. The tool turns `Bright Data` into `bright-data`.

Pass an unknown slug and the model gets `{"error": ...}` with the API's error message. The error message for an unknown API slug lists every valid slug. The model can then pick one and call the tool again. The tool checks each argument from the model before the API call. For a number out of range, Agency Swarm sends the model an error message. The tool makes no API call.

## Network

Each tool call makes one HTTPS GET request to https://api.datacircle.dev/v1 and no other network calls. Agency Swarm runs the request in a thread, so your agency keeps running. The request holds only the tool's own arguments. The API takes up to 60 calls a minute from one IP address. If the API says to wait, the tool waits up to a minute. The tool waits at most once per call. All plans are in one file at https://datacircle.dev/datacircle.json.

## Links

- Datacircle: https://datacircle.dev
- The API: https://datacircle.dev/api
- The API's spec: https://api.datacircle.dev/v1/openapi.json
- What each key means: https://datacircle.dev/fields

MIT license.
