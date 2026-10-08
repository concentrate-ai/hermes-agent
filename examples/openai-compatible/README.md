# OpenAI-compatible sample apps

Three small, self-contained clients that run against **any** OpenAI-compatible
endpoint — OpenAI, a gateway, a router, a local server — by changing
environment variables only. No code edits, no config files, no SDK specifics.

These are reference *consumers*: the minimum a real client needs (chat,
streaming, tool calls). They complement the conformance suite, which defines
what correct OpenAI-compatible server behavior looks like.

## Apps

| App | Path | Demonstrates |
| --- | --- | --- |
| Python CLI chat | [`python-cli-chat/`](./python-cli-chat/) | Multi-turn chat, `--stream` token streaming |
| Streaming web UI | [`web-streaming-ui/`](./web-streaming-ui/) | SSE parsing, TTFT and tokens/sec in the browser, keyless mock mode |
| Tool-calling agent | [`tool-calling-agent/`](./tool-calling-agent/) | Tool schemas, `role: "tool"` results, agent loop with a step cap |

## Config contract

All three apps read the same three environment variables and nothing else:

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `OPENAI_BASE_URL` | no | `https://api.openai.com/v1` | Root URL of any OpenAI-compatible API |
| `OPENAI_API_KEY` | **yes** | — | Bearer credential sent to that endpoint |
| `OPENAI_MODEL` | no | per-app default (`gpt-4o-mini` for the CLI) | Model id passed in the request body |

Nothing is hard-coded to one provider. Concentrate AI is a **configuration
choice**, not a special case — point `OPENAI_BASE_URL` at its gateway and every
app works:

```bash
export OPENAI_BASE_URL="https://<your-concentrate-gateway-host>/v1"
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="gpt-4o-mini"
```

Switching to OpenAI proper, OpenRouter, or a local server is the same three
variables with different values. The samples mirror the power-user contract
already used by `hermes_cli/config.py` (`OPENAI_API_KEY` / `OPENAI_BASE_URL`)
and `cli-config.yaml.example`'s `provider: "custom"` semantics, but they import
nothing from hermes core and are fully decoupled from the repo's build system.

## Running the Python CLI chat

```bash
cd examples/openai-compatible/python-cli-chat
pip install -r requirements.txt

export OPENAI_API_KEY="sk-..."          # required
export OPENAI_BASE_URL="https://api.openai.com/v1"  # optional — any compatible endpoint
export OPENAI_MODEL="gpt-4o-mini"       # optional

python chat.py            # request/response mode
python chat.py --stream   # stream tokens as they arrive
```

In the REPL: `/reset` clears conversation history, `/exit` (or Ctrl-D) quits.
Missing `OPENAI_API_KEY` exits cleanly with a message instead of a traceback.

## Running the streaming web UI

No build step, no framework — a static page plus one ES module:

```bash
cd examples/openai-compatible/web-streaming-ui
python -m http.server 8080
# then open http://localhost:8080
```

Set the endpoint in the page's **Settings** panel — the same three fields as
the env contract (base URL, API key, model), stored in `localStorage`. The
panel is the browser twin of the environment variables: point the base URL at
Concentrate AI's gateway, OpenAI, OpenRouter, or any compatible server.

### Mock mode (no API key needed)

Open the page with [`?mock=1`](http://localhost:8080/?mock=1) or flip the
**Mock stream** toggle in Settings. A local generator then emits the identical
SSE envelope a real server sends (`data: {…choices:[{delta:{content}}]} …
`data: [DONE]`) over ~2 seconds — **zero network calls**. The same parser
renders it token by token, with live TTFT and tokens/sec in the header, so the
UI can be demoed and screenshotted without credentials.

![Streaming web UI rendering the mock stream, with MOCK badge and live
TTFT/tokens-per-sec](./mock-mode.png)

## Running the tool-calling agent

```bash
cd examples/openai-compatible/tool-calling-agent
pip install -r requirements.txt

export OPENAI_API_KEY="sk-..."          # required
export OPENAI_BASE_URL="https://api.openai.com/v1"  # optional — any compatible endpoint
export OPENAI_MODEL="gpt-4o-mini"       # optional

python agent.py "What's the weather in Tokyo, and what's in /tmp?"
```

The agent registers two safe, deterministic example tools —
`get_current_weather` (a canned demo report, not a live feed) and
`list_directory` (read-only directory listing). It sends the tool schemas with
the request; while the model answers with `tool_calls`, each tool executes and
its `role: "tool"` result (keyed by `tool_call_id`) joins the history for the
next call. The first plain-text reply ends the loop, and a hard cap of 8 model
calls stops runaway loops with a clean `SystemExit`.

## Tests

Python apps have mirrored pytest suites under `tests/examples/`, using a fake
OpenAI-compatible HTTP server (no network, no API key). Live-endpoint tests
exist behind the `integration` pytest marker and are excluded from default
runs; run them manually when credentials are available:

```bash
scripts/run_tests.sh tests/examples/
```
