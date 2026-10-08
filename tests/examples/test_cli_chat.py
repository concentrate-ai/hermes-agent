"""Tests for examples/openai-compatible/python-cli-chat/chat.py.

The sample app is intentionally outside the hermes package, so the module is
loaded from its file path instead of a package import. Requests go to a fake
OpenAI-compatible HTTP server (no network, no API key), asserting the exact
request shape a real endpoint would receive.
"""

from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAT_PATH = (
    REPO_ROOT
    / "examples"
    / "openai-compatible"
    / "python-cli-chat"
    / "chat.py"
)


@pytest.fixture()
def chat_module():
    """Load the sample app's chat.py from its file path (it is not a package)."""
    spec = importlib.util.spec_from_file_location("sample_chat_under_test", CHAT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeOpenAIHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible /chat/completions stand-in.

    Echoes the last user message as the assistant reply. Streaming requests
    get a real SSE envelope (delta frames, then ``data: [DONE]``) so the app's
    stream parser is exercised against the wire format it must consume.
    """

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        server = self.server
        assert isinstance(server, FakeOpenAIServer)
        server.captured_requests.append({"path": self.path, "body": body})

        reply = _echo_reply(body)
        if body.get("stream"):
            self._send_stream(reply, str(body.get("model", "")))
        else:
            self._send_json(reply, str(body.get("model", "")))

    def _send_json(self, reply: str, model: str) -> None:
        payload = {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply},
                    "finish_reason": "stop",
                }
            ],
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_stream(self, reply: str, model: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def frame(delta: dict[str, Any], finish: str | None = None) -> None:
            chunk = {
                "id": "chatcmpl-fake",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()

        frame({"role": "assistant", "content": ""})
        # Emit the reply in small pieces to force multiple delta frames.
        for piece in (reply[:3], reply[3:6], reply[6:]):
            if piece:
                frame({"content": piece})
        frame({}, finish="stop")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *args: Any) -> None:  # silence per-request stderr
        return


class FakeOpenAIServer(ThreadingHTTPServer):
    captured_requests: list[dict[str, Any]]

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _FakeOpenAIHandler)
        self.captured_requests = []


def _echo_reply(body: dict[str, Any]) -> str:
    """Deterministic reply: echo the last user message."""
    messages = body.get("messages", [])
    for message in reversed(messages):
        if message.get("role") == "user":
            return f"echo: {message.get('content', '')}"
    return "echo: "


@pytest.fixture()
def fake_server(monkeypatch: pytest.MonkeyPatch) -> FakeOpenAIServer:
    server = FakeOpenAIServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(
        "OPENAI_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}/v1"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    yield server
    server.shutdown()


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def test_resolve_config_reads_env(chat_module, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://gateway.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "my-model")
    assert chat_module.resolve_config() == {
        "base_url": "http://gateway.example/v1",
        "api_key": "sk-test",
        "model": "my-model",
    }


def test_resolve_config_defaults(chat_module, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    config = chat_module.resolve_config()
    assert config["base_url"] == "https://api.openai.com/v1"
    assert config["model"] == "gpt-4o-mini"
    assert config["api_key"] == "sk-test"


def test_missing_api_key_raises_system_exit(chat_module, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        chat_module.resolve_config()
    assert "OPENAI_API_KEY" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Request shape against the fake server
# ---------------------------------------------------------------------------


def test_non_streaming_request_shape(chat_module, fake_server):
    config = chat_module.resolve_config()
    client = chat_module.build_client(config)
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "echo: hi"},
        {"role": "user", "content": "what?"},
    ]
    reply = chat_module.complete_once(client, config, history)

    assert reply == "echo: what?"
    captured = fake_server.captured_requests
    assert len(captured) == 1
    body = captured[0]["body"]
    assert body["model"] == "test-model"
    assert body["messages"] == history
    assert not body.get("stream")


def test_streaming_request_shape_and_render(chat_module, fake_server, capsys):
    config = chat_module.resolve_config()
    client = chat_module.build_client(config)
    history = [{"role": "user", "content": "stream me"}]

    reply = chat_module.stream_once(client, config, history)

    assert reply == "echo: stream me"
    captured_out = capsys.readouterr().out
    assert "echo: stream me" in captured_out
    body = fake_server.captured_requests[0]["body"]
    assert body["model"] == "test-model"
    assert body["messages"] == history
    assert body["stream"] is True


def test_multi_turn_history_accumulates(chat_module, fake_server):
    config = chat_module.resolve_config()
    client = chat_module.build_client(config)
    history: list[dict[str, str]] = []

    first = chat_module.complete_once(client, config, history + [
        {"role": "user", "content": "turn one"}
    ])
    history.append({"role": "user", "content": "turn one"})
    history.append({"role": "assistant", "content": first})

    second = chat_module.complete_once(client, config, history + [
        {"role": "user", "content": "turn two"}
    ])

    assert first == "echo: turn one"
    assert second == "echo: turn two"
    second_body = fake_server.captured_requests[1]["body"]
    roles = [m["role"] for m in second_body["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert second_body["messages"][1]["content"] == "echo: turn one"


# ---------------------------------------------------------------------------
# REPL loop
# ---------------------------------------------------------------------------


def _feed_input(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> None:
    """Patch builtins.input to return lines in order, then EOF."""
    iterator = iter(lines)

    def fake_input(_prompt: str = "") -> str:
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", fake_input)


def test_repl_exits_and_reset(chat_module, fake_server, capsys, monkeypatch):
    _feed_input(monkeypatch, ["hello", "/reset", "again", "/exit"])
    config = chat_module.resolve_config()
    client = chat_module.build_client(config)

    chat_module.run_repl(client, config)

    out = capsys.readouterr().out
    assert "assistant> echo: hello" in out
    assert "(history reset)" in out
    # Only two API turns happened (/reset clears; /exit quits before calling).
    assert len(fake_server.captured_requests) == 2
    third_turn_messages = fake_server.captured_requests[1]["body"]["messages"]
    assert third_turn_messages == [{"role": "user", "content": "again"}]


def test_repl_eof_exits(chat_module, fake_server, monkeypatch):
    _feed_input(monkeypatch, ["hello"])  # then EOF
    config = chat_module.resolve_config()
    client = chat_module.build_client(config)

    chat_module.run_repl(client, config)  # returns instead of raising

    assert len(fake_server.captured_requests) == 1


def test_repl_survives_api_error(chat_module, capsys, monkeypatch):
    """An API failure surfaces a message and keeps the session alive."""
    _feed_input(monkeypatch, ["hello", "are you there?", "/exit"])

    class FailingClient:
        class chat:  # noqa: N801 - mirrors OpenAI client shape
            class completions:
                @staticmethod
                def create(**_: Any) -> None:
                    import openai

                    raise openai.APIError("boom", request=None, body=None)

    config = {"base_url": "http://127.0.0.1:1/v1", "api_key": "k", "model": "m"}
    chat_module.run_repl(FailingClient(), config)  # type: ignore[arg-type]

    out = capsys.readouterr().out
    assert "API call failed" in out
    # Both turns attempted the API after the first error — session stayed alive.
    assert out.count("API call failed") == 2


# ---------------------------------------------------------------------------
# Live endpoint (opt-in)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_live_endpoint_roundtrip(chat_module, monkeypatch):
    """Runs only with real credentials: OPENAI_API_KEY (+ optional BASE_URL/MODEL)."""
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set — live-endpoint check is opt-in")
    config = chat_module.resolve_config()
    client = chat_module.build_client(config)
    reply = chat_module.complete_once(
        client, config, [{"role": "user", "content": "Reply with the word: pong"}]
    )
    assert "pong" in reply.lower()
