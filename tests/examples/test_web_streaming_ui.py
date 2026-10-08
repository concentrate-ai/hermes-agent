"""Tests for examples/openai-compatible/web-streaming-ui.

The UI is a static ES module with no build step, so the suite does three
things without a browser or network:

1. Loads ``index.html`` and asserts the DOM contract ``main.js`` expects
   (element ids, module script tag).
2. Parse-checks ``main.js`` with Node (the ``apps/desktop/*.test.cjs``
   precedent: CI has no JS pipeline, so pytest drives Node directly).
3. Runs the exported pure helpers in Node — SSE frame parsing on chunk
   boundaries, delta extraction, metrics — and pushes a full mock stream
   through the parser to prove the envelope the generator emits is exactly
   what the parser consumes.

Not marked integration: no network calls are made.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_DIR = REPO_ROOT / "examples" / "openai-compatible" / "web-streaming-ui"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required for the JS checks"
)


@pytest.fixture(scope="module")
def index_html() -> str:
    return (UI_DIR / "index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. index.html DOM contract
# ---------------------------------------------------------------------------


def test_index_html_references_main_js_as_module(index_html: str) -> None:
    assert '<script type="module" src="./main.js">' in index_html


@pytest.mark.parametrize(
    "element_id",
    [
        "mock-badge",  # mock-mode indicator (required in the screenshot)
        "ttft",  # time-to-first-token readout
        "tps",  # tokens-per-second readout
        "settings",  # settings panel container
        "base-url",  # OPENAI_BASE_URL equivalent
        "api-key",  # OPENAI_API_KEY equivalent
        "model",  # OPENAI_MODEL equivalent
        "mock-toggle",  # 'Mock stream' toggle
        "chat",  # message list
        "composer",  # input form
        "prompt",  # message textarea
        "send",  # submit button
        "error",  # error banner
    ],
)
def test_index_html_has_required_elements(index_html: str, element_id: str) -> None:
    assert f'id="{element_id}"' in index_html


def test_index_html_has_no_build_step_or_workspace_membership() -> None:
    assert not (UI_DIR / "package.json").exists()
    assert not (UI_DIR / "node_modules").exists()
    assert sorted(p.name for p in UI_DIR.iterdir()) == ["index.html", "main.js"]


# ---------------------------------------------------------------------------
# 2. Node parse-check
# ---------------------------------------------------------------------------


def test_main_js_parses_as_an_es_module() -> None:
    result = subprocess.run(
        ["node", "--input-type=module", "--check"],
        stdin=(UI_DIR / "main.js").open("rb"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"main.js failed Node parse-check:\n{result.stderr}"


# ---------------------------------------------------------------------------
# 3. Functional checks run in Node against the exported helpers
# ---------------------------------------------------------------------------

NODE_CHECK = """
import { createSSEFrameParser, extractDeltaText, computeTokensPerSecond,
         formatMs, shouldUseMock, mockSSEStream } from '%(main_js)s';
import assert from 'node:assert/strict';

// --- frame parsing, including chunk-boundary splits and CRLF -------------
const parser = createSSEFrameParser();
assert.deepEqual(parser.feed('data: {"a":1}\\n\\ndata: {"b":2'), ['{"a":1}']);
assert.deepEqual(parser.feed('}\\n\\n'), ['{"b":2}']);
const crlf = createSSEFrameParser();
assert.deepEqual(crlf.feed('data: {"c":3}\\r\\n\\r\\n'), ['{"c":3}']);
assert.equal(crlf.isDone(), false);
crlf.feed('data: [DONE]\\n\\n');
assert.equal(crlf.isDone(), true);
// comments / keep-alive frames produce no payloads
assert.deepEqual(createSSEFrameParser().feed(': keep-alive\\n\\n'), []);

// --- delta extraction ----------------------------------------------------
assert.equal(extractDeltaText('{"choices":[{"delta":{"content":"Hi"}}]}'), 'Hi');
assert.equal(extractDeltaText('{"choices":[{"delta":{"role":"assistant"}}]}'), '');
assert.equal(extractDeltaText('not json'), '');

// --- metrics -------------------------------------------------------------
assert.equal(computeTokensPerSecond(0, 0, 100), 0);
assert.equal(computeTokensPerSecond(20, 0, 1000), 20);
assert.equal(computeTokensPerSecond(10, 0, 2500), 4);
assert.equal(formatMs(412.6), '413 ms');

// --- mock decision: ?mock=1 wins, stored preference is the fallback ------
assert.equal(shouldUseMock('?mock=1', false), true);
assert.equal(shouldUseMock('?mock=0', true), false);
assert.equal(shouldUseMock('', true), true);
assert.equal(shouldUseMock('', false), false);

// --- the mock stream's envelope is exactly what the parser consumes ------
let joined = '';
let frameCount = 0;
for await (const chunk of mockSSEStream('hello')) {
  joined += chunk;
  for (const payload of parser.feed(chunk)) {
    const text = extractDeltaText(payload);
    assert.notEqual(text, '', 'every mock frame must carry delta content');
    joined += '|OK|';
    frameCount += 1;
  }
}
assert.equal(parser.isDone(), true);
assert.ok(frameCount > 3, `expected several delta frames, got ${frameCount}`);
assert.ok(joined.endsWith('data: [DONE]\\n\\n'), 'stream must end with data: [DONE]');
assert.ok(joined.includes('data: {"id":"chatcmpl-mock"'), 'frames must be data: + JSON envelope');
assert.ok(joined.includes('"object":"chat.completion.chunk"'));
"""


def test_node_runs_mock_stream_through_the_real_parser(tmp_path: Path) -> None:
    script = tmp_path / "mock_stream_check.mjs"
    script.write_text(NODE_CHECK % {"main_js": (UI_DIR / "main.js").as_uri()}, encoding="utf-8")
    result = subprocess.run(
        ["node", str(script)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"Node functional check failed:\n{result.stdout}\n{result.stderr}"


# ---------------------------------------------------------------------------
# 4. The wire contract the fetch path must produce (source-level assertions)
# ---------------------------------------------------------------------------


def test_main_js_sends_stream_true_and_sse_auth_header() -> None:
    source = (UI_DIR / "main.js").read_text(encoding="utf-8")
    assert "chat/completions" in source
    assert "stream: true" in source
    assert "Authorization: `Bearer ${config.apiKey}`" in source
    # The mock branch must short-circuit before fetch is reachable.
    assert source.index("if (mock)") < source.index("await fetch(")


def test_readme_documents_mock_mode() -> None:
    readme = (REPO_ROOT / "examples" / "openai-compatible" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "web-streaming-ui" in readme
    assert "mock" in readme.lower()
