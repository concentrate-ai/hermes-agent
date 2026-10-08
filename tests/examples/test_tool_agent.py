"""Tests for examples/openai-compatible/tool-calling-agent/agent.py.

The sample app is intentionally outside the hermes package, so the module is
loaded from its file path instead of a package import. Requests go to a fake
OpenAI-compatible HTTP server (no network, no API key) whose responses are
scripted per test: one tool-calls turn then a final answer, or tool calls
forever to prove the step cap trips.
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
AGENT_PATH = (
    REPO_ROOT
    / "examples"
    / "openai-compatible"
    / "tool-calling-agent"
    / "agent.py"
)


@pytest.fixture()
def agent_module():
    """Load the sample app's agent.py from its file path (it is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "sample_tool_agent_under_test", AGENT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Wire-format response builders (what a real endpoint would send back)
# ---------------------------------------------------------------------------


def _tool_call_response(
    call_id: str, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """A chat.completion whose assistant message requests one tool call."""
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }


def _final_response(text: str) -> dict[str, Any]:
    """A chat.completion with a plain-text assistant answer."""
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }


class _ScriptedHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible /chat/completions stand-in.

    Responses are popped from ``server.script`` in order; once the script is
    exhausted, ``server.default_response`` answers every further request
    (the cap test sets that to a tool-calls reply that never stops).
    """

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        server = self.server
        assert isinstance(server, ScriptedOpenAIServer)
        server.captured_requests.append({"path": self.path, "body": body})

        if server.script:
            payload = server.script.pop(0)
        else:
            payload = server.default_response
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: Any) -> None:  # silence per-request stderr
        return


class ScriptedOpenAIServer(ThreadingHTTPServer):
    captured_requests: list[dict[str, Any]]
    script: list[dict[str, Any]]
    default_response: dict[str, Any]

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _ScriptedHandler)
        self.captured_requests = []
        self.script = []
        self.default_response = _final_response("done")


@pytest.fixture()
def scripted_server(monkeypatch: pytest.MonkeyPatch) -> ScriptedOpenAIServer:
    server = ScriptedOpenAIServer()
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
# Config resolution and tool execution (no server needed)
# ---------------------------------------------------------------------------


def test_resolve_config_reads_env(agent_module, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://gateway.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "my-model")
    assert agent_module.resolve_config() == {
        "base_url": "http://gateway.example/v1",
        "api_key": "sk-test",
        "model": "my-model",
    }


def test_missing_api_key_raises_system_exit(agent_module, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        agent_module.resolve_config()
    assert "OPENAI_API_KEY" in str(excinfo.value)


def test_tools_schema_is_valid_openai_shape(agent_module):
    names = [tool["function"]["name"] for tool in agent_module.TOOLS]
    assert names == ["get_current_weather", "list_directory"]
    for tool in agent_module.TOOLS:
        assert tool["type"] == "function"
        params = tool["function"]["parameters"]
        assert params["type"] == "object"
        assert isinstance(params["properties"], dict)


def test_weather_tool_is_deterministic(agent_module):
    first = agent_module.execute_tool("get_current_weather", '{"city": "Tokyo"}')
    second = agent_module.execute_tool(
        "get_current_weather", '{"city": "somewhere-else"}'
    )
    # Known city: canned report. Unknown city: stable hash-derived report.
    assert json.loads(first) == {
        "city": "Tokyo",
        "celsius": 18,
        "conditions": "light rain",
    }
    again = agent_module.execute_tool(
        "get_current_weather", '{"city": "somewhere-else"}'
    )
    assert second == again


def test_list_directory_tool_lists_sorted_entries(agent_module, tmp_path):
    # List a dedicated subdir: the repo conftest drops a fake home
    # (hermes_test) into every test's tmp_path, so tmp_path itself is not
    # an isolated directory to assert exact listings against.
    target = tmp_path / "listing"
    target.mkdir()
    for name in ("b.txt", "a.txt", "c"):
        (target / name).write_text("x", encoding="utf-8")
    result = agent_module.execute_tool(
        "list_directory", json.dumps({"path": str(target)})
    )
    assert json.loads(result) == {
        "path": str(target),
        "entries": ["a.txt", "b.txt", "c"],
    }


def test_execute_tool_survives_bad_input(agent_module):
    assert "error" in agent_module.execute_tool("no_such_tool", "{}")
    assert "error" in agent_module.execute_tool("list_directory", "not json")
    assert "error" in agent_module.execute_tool("list_directory", "{}")
    assert "error" in agent_module.execute_tool(
        "list_directory", json.dumps({"path": "/no/such/dir"})
    )


# ---------------------------------------------------------------------------
# Agent loop against the scripted server
# ---------------------------------------------------------------------------


def test_agent_sends_tool_schemas_on_first_request(agent_module, scripted_server):
    scripted_server.script = [_final_response("done")]
    config = agent_module.resolve_config()
    client = agent_module.build_client(config)

    agent_module.run_agent(client, config, "hello")

    body = scripted_server.captured_requests[0]["body"]
    assert body["model"] == "test-model"
    sent_names = [tool["function"]["name"] for tool in body["tools"]]
    assert sent_names == ["get_current_weather", "list_directory"]


def test_agent_executes_tool_and_terminates_on_final_answer(
    agent_module, scripted_server, tmp_path, capsys
):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "report.txt").write_text("hello", encoding="utf-8")
    scripted_server.script = [
        _tool_call_response("call-1", "list_directory", {"path": str(tmp_path / "docs")}),
        _final_response("The directory contains report.txt"),
    ]
    config = agent_module.resolve_config()
    client = agent_module.build_client(config)

    answer = agent_module.run_agent(client, config, "what is in that dir?")

    assert answer == "The directory contains report.txt"
    assert len(scripted_server.captured_requests) == 2

    # The follow-up request carries the assistant tool_calls turn and the
    # role:"tool" result, keyed by tool_call_id.
    followup_messages = scripted_server.captured_requests[1]["body"]["messages"]
    roles = [m["role"] for m in followup_messages]
    assert roles == ["user", "assistant", "tool"]
    tool_message = followup_messages[-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call-1"
    assert json.loads(tool_message["content"])["entries"] == ["report.txt"]
    assistant_turn = followup_messages[1]
    assert assistant_turn["tool_calls"][0]["id"] == "call-1"
    assert assistant_turn["tool_calls"][0]["function"]["name"] == "list_directory"

    # Tool trace was printed for the user.
    assert "[tool] list_directory(" in capsys.readouterr().out


def test_agent_handles_unknown_tool_then_finishes(agent_module, scripted_server):
    scripted_server.script = [
        _tool_call_response("call-x", "does_not_exist", {}),
        _final_response("recovered"),
    ]
    config = agent_module.resolve_config()
    client = agent_module.build_client(config)

    answer = agent_module.run_agent(client, config, "try the mystery tool")

    assert answer == "recovered"
    tool_message = scripted_server.captured_requests[1]["body"]["messages"][-1]
    assert tool_message["tool_call_id"] == "call-x"
    assert "error: unknown tool 'does_not_exist'" in tool_message["content"]


def test_agent_cap_trips_when_model_always_calls_tools(
    agent_module, scripted_server
):
    scripted_server.default_response = _tool_call_response(
        "call-loop", "get_current_weather", {"city": "Tokyo"}
    )
    config = agent_module.resolve_config()
    client = agent_module.build_client(config)

    with pytest.raises(SystemExit) as excinfo:
        agent_module.run_agent(client, config, "loop forever")

    assert str(agent_module.MAX_STEPS) in str(excinfo.value)
    # The cap is the exact number of model calls made — then it stops.
    assert len(scripted_server.captured_requests) == agent_module.MAX_STEPS
    # The last request carried the accumulated results of the first
    # MAX_STEPS - 1 iterations; the final tool result never gets sent.
    last_body = scripted_server.captured_requests[-1]["body"]
    tool_roles = [m["role"] for m in last_body["messages"] if m["role"] == "tool"]
    assert len(tool_roles) == agent_module.MAX_STEPS - 1


def test_main_prints_final_answer(agent_module, scripted_server, capsys):
    scripted_server.script = [_final_response("all done")]

    # main() re-resolves config from the env set by the fixture.
    agent_module.main(["do the thing"])
    assert "assistant> all done" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Live endpoint (opt-in)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_live_endpoint_tool_roundtrip(agent_module, monkeypatch):
    """Runs only with real credentials: OPENAI_API_KEY (+ optional BASE_URL/MODEL)."""
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set — live-endpoint check is opt-in")
    config = agent_module.resolve_config()
    client = agent_module.build_client(config)
    answer = agent_module.run_agent(
        client,
        config,
        "Use the list_directory tool on '/home', then tell me how many entries "
        "it has in one short sentence.",
    )
    assert answer.strip()
