"""Fault-injection tests for the usage_events capture hook (spec art_tZvdMeCj).

The hook must never break a conversation: a failed usage-event insert leaves
the API call's return value and update_token_counts state identical.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from run_agent import AIAgent


def _mock_response(*, usage: dict, content: str = "done"):
    msg = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    return SimpleNamespace(
        choices=[choice],
        model="test/model",
        usage=SimpleNamespace(**usage),
    )


def _make_agent(session_db):
    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            session_db=session_db,
            session_id="capture-session",
            platform="telegram",
        )
    agent.client = MagicMock()
    agent.client.chat.completions.create.return_value = _mock_response(
        usage={
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        }
    )
    return agent


def test_capture_hook_records_one_event_per_api_call():
    session_db = MagicMock()
    agent = _make_agent(session_db)

    result = agent.run_conversation("hello")

    assert result["final_response"] == "done"
    session_db.record_usage_event.assert_called_once()
    kwargs = session_db.record_usage_event.call_args.kwargs
    assert kwargs["session_id"] == "capture-session"
    # CanonicalUsage fields land on the event row.
    assert kwargs["input_tokens"] == 11
    assert kwargs["output_tokens"] == 7
    assert kwargs["api_status"] == "ok"


def test_capture_hook_failure_never_breaks_conversation():
    session_db = MagicMock()

    def _boom(*args, **kwargs):
        raise RuntimeError("forced usage-event insert failure")

    session_db.record_usage_event.side_effect = _boom
    agent = _make_agent(session_db)

    result = agent.run_conversation("hello")

    # The API call's return value is unaffected...
    assert result["final_response"] == "done"
    assert result["completed"] is True
    # ...and update_token_counts still ran exactly once, unchanged.
    session_db.update_token_counts.assert_called_once()


def test_capture_hook_reuses_cost_result_without_second_estimate():
    session_db = MagicMock()
    agent = _make_agent(session_db)
    agent.session_estimated_cost_usd = 0.0
    agent.session_cost_status = None
    agent.session_cost_source = None

    import agent.conversation_loop as conv_loop

    with patch.object(
        conv_loop, "estimate_usage_cost", wraps=conv_loop.estimate_usage_cost
    ) as spy:
        result = agent.run_conversation("hello")

        assert result["final_response"] == "done"
        # estimate_usage_cost is called ONCE per API call — the CostResult
        # is reused by both the session update and the event capture.
        assert spy.call_count == 1
        kwargs = session_db.record_usage_event.call_args.kwargs
        assert kwargs["cost_status"] is not None or kwargs["cost_source"] is not None
