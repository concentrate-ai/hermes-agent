"""Standalone multi-turn chat REPL against any OpenAI-compatible endpoint.

Configured purely by environment variables (see ../README.md):

- ``OPENAI_API_KEY``   required — bearer credential
- ``OPENAI_BASE_URL``  optional — defaults to https://api.openai.com/v1
- ``OPENAI_MODEL``     optional — defaults to ``DEFAULT_MODEL``

Imports nothing from hermes core: point ``OPENAI_BASE_URL`` at any
OpenAI-compatible gateway and this runs unchanged.

Usage::

    python chat.py            # request/response mode
    python chat.py --stream   # print tokens as they arrive

REPL commands: ``/reset`` clears history, ``/exit`` (or Ctrl-D) quits.
"""

from __future__ import annotations

import argparse
import os

import openai
from openai import OpenAI

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

EXIT_COMMANDS = frozenset({"/exit", "/quit"})
RESET_COMMAND = "/reset"


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


def complete_once(
    client: OpenAI, config: dict[str, str], history: list[dict[str, str]]
) -> str:
    """One non-streaming completion; returns the assistant text."""
    response = client.chat.completions.create(model=config["model"], messages=history)
    return response.choices[0].message.content or ""


def stream_once(
    client: OpenAI, config: dict[str, str], history: list[dict[str, str]]
) -> str:
    """Streamed completion: prints deltas as they arrive, returns the full text."""
    stream = client.chat.completions.create(
        model=config["model"], messages=history, stream=True
    )
    pieces: list[str] = []
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            print(delta, end="", flush=True)
            pieces.append(delta)
    print()
    return "".join(pieces)


def run_repl(client: OpenAI, config: dict[str, str], stream: bool = False) -> None:
    """Read-eval-print loop; keeps multi-turn history in a plain message list."""
    history: list[dict[str, str]] = []
    mode = "streaming" if stream else "request/response"
    print(f"Chatting with {config['model']} at {config['base_url']} ({mode}).")
    print("Commands: /reset clears history, /exit quits.")
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not user_input:
            continue
        if user_input in EXIT_COMMANDS:
            return
        if user_input == RESET_COMMAND:
            history.clear()
            print("(history reset)")
            continue
        history.append({"role": "user", "content": user_input})
        try:
            if stream:
                reply = stream_once(client, config, history)
            else:
                reply = complete_once(client, config, history)
                print(f"assistant> {reply}")
        except openai.APIError as exc:
            # Surface the API error and keep the session alive; the pending
            # user turn stays in history so the next exchange retries it.
            print(f"\n(error: API call failed — {exc})")
            continue
        history.append({"role": "assistant", "content": reply})


def build_parser() -> argparse.ArgumentParser:
    """CLI flags (stdlib argparse, mirroring hermes_cli/usage_report.py)."""
    parser = argparse.ArgumentParser(
        prog="chat",
        description="Multi-turn chat against any OpenAI-compatible endpoint.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="stream response tokens as they arrive instead of one block",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = resolve_config()  # raises SystemExit when OPENAI_API_KEY is unset
    run_repl(build_client(config), config, stream=args.stream)


if __name__ == "__main__":
    main()
