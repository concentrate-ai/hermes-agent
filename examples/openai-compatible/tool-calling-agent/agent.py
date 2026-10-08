"""Standalone tool-calling agent loop against any OpenAI-compatible endpoint.

Configured purely by environment variables (see ../README.md):

- ``OPENAI_API_KEY``   required — bearer credential
- ``OPENAI_BASE_URL``  optional — defaults to https://api.openai.com/v1
- ``OPENAI_MODEL``     optional — defaults to ``DEFAULT_MODEL``

Imports nothing from hermes core: point ``OPENAI_BASE_URL`` at any
OpenAI-compatible gateway and this runs unchanged.

Usage::

    python agent.py "What's the weather in Tokyo, and what's in /tmp?"

The agent registers two safe, deterministic example tools:

- ``get_current_weather`` — a canned demo report (not a live feed)
- ``list_directory`` — lists a local directory's entries

Loop shape: send the user prompt plus the tool schemas; while the model
answers with ``tool_calls``, execute each tool, append a ``role: "tool"``
message (with ``tool_call_id``) per result, and call again. When the model
answers with plain text, that text is the final answer. A hard cap of
``MAX_STEPS`` iterations guards against runaway loops.

REPL commands: none — one prompt in, one final answer out.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from typing import Any

from openai import OpenAI

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

# Runaway guard: the loop makes at most this many model calls before giving up.
MAX_STEPS = 8

# Deterministic demo weather (not a live feed) so results are reproducible.
WEATHER_BY_CITY = {
    "tokyo": {"celsius": 18, "conditions": "light rain"},
    "london": {"celsius": 11, "conditions": "overcast"},
    "san francisco": {"celsius": 16, "conditions": "foggy until noon"},
}
CONDITIONS = ("sunny", "cloudy", "windy", "clear skies")

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": (
                "Get the current weather for a city. Demo tool with a "
                "deterministic canned response, not a live weather feed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g. 'Tokyo'",
                    }
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the entry names of a local filesystem directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the directory to list",
                    }
                },
                "required": ["path"],
            },
        },
    },
]


def resolve_config() -> dict[str, str]:
    """Read the env-only config contract.

    Raises ``SystemExit`` with a user-facing message when ``OPENAI_API_KEY``
    is missing — a clean exit, not a traceback.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(
            "error: set OPENAI_API_KEY (and optionally OPENAI_BASE_URL, OPENAI_MODEL)."
        )
    return {
        "base_url": os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
        "api_key": api_key,
        "model": os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
    }


def build_client(config: dict[str, str]) -> OpenAI:
    """Client pointed at whatever OPENAI_BASE_URL supplies."""
    return OpenAI(base_url=config["base_url"], api_key=config["api_key"])


def _get_current_weather(city: str) -> str:
    """Canned, deterministic weather so runs are reproducible."""
    key = city.strip().lower()
    if key in WEATHER_BY_CITY:
        report = WEATHER_BY_CITY[key]
    else:
        # Stable pseudo-weather for unknown cities (hash, not randomness).
        seed = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)
        report = {
            "celsius": seed % 36 - 5,  # -5..30
            "conditions": CONDITIONS[seed % len(CONDITIONS)],
        }
    return json.dumps({"city": city, **report})


def _list_directory(path: str) -> str:
    """Sorted directory listing — read-only, no secrets, no recursion."""
    entries = sorted(os.listdir(path))
    return json.dumps({"path": path, "entries": entries})


def execute_tool(name: str, arguments: str) -> str:
    """Dispatch one tool call and return the result as a string.

    Never raises: problems (unknown tool, bad arguments, filesystem errors)
    come back as ``error: ...`` strings the model can read and react to.
    """
    try:
        args: dict[str, Any] = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        return f"error: tool arguments were not valid JSON: {exc}"
    try:
        if name == "get_current_weather":
            return _get_current_weather(str(args["city"]))
        if name == "list_directory":
            return _list_directory(str(args["path"]))
        return f"error: unknown tool '{name}'"
    except KeyError as exc:
        return f"error: missing required argument {exc} for tool '{name}'"
    except OSError as exc:
        return f"error: {exc}"


def _tool_call_payloads(message: Any) -> list[dict[str, Any]]:
    """Assistant message's tool_calls in plain wire-format dicts."""
    return [tool_call.model_dump(exclude_none=True) for tool_call in message.tool_calls]


def run_agent(client: OpenAI, config: dict[str, str], user_prompt: str) -> str:
    """Run the agent loop until a final text answer (or the step cap trips).

    Each iteration sends the accumulated history plus the tool schemas. On a
    ``tool_calls`` reply every tool executes and its ``role: "tool"`` result
    (keyed by ``tool_call_id``) joins the history for the next call. The first
    plain-text reply ends the loop.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
    for _ in range(MAX_STEPS):
        response = client.chat.completions.create(
            model=config["model"], messages=messages, tools=TOOLS
        )
        message = response.choices[0].message
        if not message.tool_calls:
            return message.content or ""
        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": _tool_call_payloads(message),
            }
        )
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            result = execute_tool(name, tool_call.function.arguments)
            print(f"[tool] {name}({tool_call.function.arguments}) -> {result}")
            messages.append(
                {"role": "tool", "tool_call_id": tool_call.id, "content": result}
            )
    raise SystemExit(
        f"error: no final answer after {MAX_STEPS} model calls; "
        "stopping to avoid a runaway tool loop."
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minimal tool-calling agent for any OpenAI-compatible endpoint."
    )
    parser.add_argument("prompt", help="What the agent should accomplish")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = resolve_config()
    client = build_client(config)
    answer = run_agent(client, config, args.prompt)
    print(f"assistant> {answer}")


if __name__ == "__main__":
    main()
