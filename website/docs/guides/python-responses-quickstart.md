---
sidebar_position: 6
title: "Quickstart: the Responses API from Python"
description: "Install the OpenAI SDK, authenticate with API_SERVER_KEY, make your first /v1/responses request, stream it, and retry with backoff"
---

# Quickstart: the Responses API from Python

Hermes exposes an [OpenAI Responses-compatible HTTP API](/user-guide/features/api-server) at `POST /v1/responses`. The server runs the agent — tool calls, terminal, memory, everything — and hands back the final turn. This quickstart drives it with the **official OpenAI Python SDK** (`openai`): install, auth, a first request, streaming, and retry handling for a script that calls the agent unattended.

:::info
Every request in this guide was executed against a real `gateway/platforms/api_server.py` process at the time of writing; the raw HTTP record lives in [`python-responses-quickstart-tracebook.md`](./python-responses-quickstart-tracebook.md). The Hermes server implements a **subset** of the cloud OpenAI `/v1/responses` surface — if a feature you know from the hosted API isn't shown here, assume it is not implemented rather than "merely undocumented."
:::

## What you need

A running Hermes API server before anything else. Two server-side variables must be set **before** `hermes gateway` starts. The server reads them from plain `os.environ` — if `API_SERVER_KEY` is absent, the process exits at boot rather than starting an unauthenticated server, so check the gateway's startup log first when a request 401s from nowhere.

Server side (`~/.hermes/.env`, the file the gateway loads):

```bash
API_SERVER_ENABLED=true
API_SERVER_KEY=<a long random secret>
API_SERVER_PORT=8642
```

Start the server:

```bash
hermes gateway
# Expect on stdout:
#   [API Server] API server listening on http://127.0.0.1:8642
```

Client side (your script's environment):

```bash
export HERMES_API_KEY="<the same long random secret>"
# Optional; defaults to http://localhost:8642/v1 — set it only if you moved the server:
export HERMES_BASE_URL="http://localhost:8642/v1"   # noqa: example only
```

`HERMES_API_KEY` is *not* a Hermes setting — it's just a conventional client-side name for the **same value** the server holds in `API_SERVER_KEY`. Name yours whatever fits your codebase; only the value must match. Never paste the secret itself into source.

:::tip Prove the server is up before debugging your client
```bash
curl -i http://localhost:8642/v1/models
```
`401` (missing header): server up, your request reached it — this curl with no key is always the first check. `200` with a JSON `data` array means auth works too: `curl -i -H "Authorization: Bearer $HERMES_API_KEY" http://localhost:8642/v1/models`.
:::

## 1. Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install openai==2.24.0
```

That's the exact `openai` version Hermes itself dogfoods (`pyproject.toml:34`) and the version this guide's calls were all tested with. Hermes has no bespoke Python client package — the OpenAI SDK pointed at your server **is** the client. If you're on uv instead: `uv pip install openai==2.24.0`.

:::caution Immutability check
Recent OpenAI SDK releases have changed the Responses surface; the query syntax drift may show up as unexpected exceptions at `.create()` time. If you upgrade `openai`, re-run this guide's scripts before trusting any other example from this guide with the newer client.
:::

## 2. First request (non-streaming)

Save as `quickstart_first.py`, run from the activated venv:

```python
import os

import openai

client = openai.OpenAI(
    api_key=os.environ["HERMES_API_KEY"],
    base_url=os.environ.get("HERMES_BASE_URL", "http://localhost:8642/v1"),
)

resp = client.responses.create(
    model="hermes-agent",
    input="In one sentence, what is Hermes?",
)

print("id:", resp.id)
print("status:", resp.status)
print("model:", resp.model)
print("text:", resp.output_text)
print("usage:", resp.usage)
```

Run it:

```console
$ python quickstart_first.py
id: resp_…    # values differ every run; see the trace book for a real captured value
status: completed
model: hermes-agent
text: Hermes is a self-hosted agent platform that exposes an OpenAI-compatible HTTP API and runs your configured agent server-side, streaming or batch.
usage: ResponseUsage(input_tokens=1245, input_tokens_details=None, output_tokens=17, output_tokens_details=None, total_tokens=1262)
```

Three things worth noticing in your first response:

- **`id`** — a `resp_`-prefixed identifier, used for chaining in [§7](#7-chaining-retrieval-and-truncation) and by `GET /v1/responses/{id}`.
- **`resp.output` vs `resp.output_text`** — `output` is a list of items the agent produced this turn: tool calls (`"type": "function_call"`), their results (`"type": "function_call_output"`), and the final assistant message. `output_text` is the SDK's convenience: just the text from the final message, concatenated. For most callers `output_text` is the right read.
- **`usage`** — token accounting for the turn: `input_tokens` (everything the model saw, including tool outputs), `output_tokens`, `total_tokens`.

:::note What the model field is doing
Hermes has one agent, configured server-side: whatever `model` you send, the same agent runs. The response's `model` field just echoes your request's value back (`api_server.py:2993` — `body.get("model", self._model_name)`), or shows the server's configured name when you send none. Treat it as cosmetic: don't branch on it expecting different capabilities, and don't expect it to tell you what actually served the answer.
:::

## 3. Streaming (`stream=True`)

For interactive UIs and anywhere you want to show progress while the agent works, stream. Same client, one kwarg:

```python
import os

import openai

client = openai.OpenAI(
    api_key=os.environ["HERMES_API_KEY"],
    base_url=os.environ.get("HERMES_BASE_URL", "http://localhost:8642/v1"),
)

stream = client.responses.create(
    model="hermes-agent",
    input="In one sentence, what is Hermes?",
    stream=True,
)

for event in stream:
    if event.type == "response.output_text.delta":
        print(event.delta, end="", flush=True)  # token-by-token text
    elif event.type == "response.output_text.done":
        pass  # final text for the message item already printed via deltas
    elif event.type == "response.completed":
        print()  # newline after the deltas
        print("[completed] id =", event.response.id)
        print("[completed] output items =", len(event.response.output))
```

**Event types the Hermes server emits on this endpoint** (SSE, `Content-Type: text/event-stream`) — in the order they arrive, and the complete list:

| Order | Event | Meaning |
|-------|-------|---------|
| 1 | `response.created` | Envelope with `status="in_progress"` — the first event to arrive, carries the `id` used for retrieve-after-disconnect |
| 2 | `response.output_item.added` / `response.output_item.done` | For **every** output item: the assistant message always emits both (framing the text events), and `function_call` items emit both when the agent uses tools, with `done` carrying the finalized arguments |
| 3 | `response.output_text.delta` | One per text chunk — the server batches deltas (~50 ms), so chunks arrive coarser than per-token |
| 4 | `response.output_text.done` | Fires once after the final `delta`, carrying the complete text |
| 5 | `response.completed` **or** `response.failed` | Terminal — carries the full response object, same shape as non-streaming |

:::warning Don't double-print on `output_text.done`
The stream sequence is:

```
delta: "Hermes"
delta: " is"
delta: " a"
...
done:  "Hermes is a self-hosted agent platform with full tool access that replies in its final turn."
```

The `done` event's `text` **is the complete assembled answer**, not one more token. If your handler prints deltas *and* prints `event.text` on `done`, the reader sees the response twice. The loop above prints deltas and ignores `done`. And the server batches deltas (~50 ms), so `delta` events arrive in coarser chunks than a token-level comparator would expect — treat deltas as chunks, not tokens.
:::

:::tip If you don't need stream, don't stream
Streaming buys you progress visibility; it costs one HTTP connection for the whole turn and per-token decode on the client. For batch, cron, and other machine listeners, the plain `client.responses.create(...)` call is the cheaper and simpler choice.
:::

:::note Only these events
The `response.created` envelope arrives first and carries the response id inside its `response` object — capture it early if you want to `retrieve` the response after an unexpected disconnect. Hermes does not emit any *other* event types on this endpoint beyond the ones in the table. In particular there is **no `response.in_progress` event** — the `in_progress` state is only ever a field inside the `created` payload — and event names like `response.reasoning_summary_text.delta` from other products never arrive here. If an upstream agent error occurs, the terminal event is `response.failed` with the error details under `response.error`.
:::

## 4. Authentication

Auth on the wire is one HTTP header. The OpenAI SDK builds it from `api_key=`:

```http
Authorization: Bearer <API_SERVER_KEY value>
```

Three failure modes, in the order you'll likely hit them:

| Cause | What the client sees | What the server returned |
|-------|----------------------|---------------------------|
| `HERMES_API_KEY` missing from env | `KeyError: 'HERMES_API_KEY'` at client-construction time, **before any HTTP request happens** | — |
| Env set, wrong value | `openai.AuthenticationError` on the **first** `.create()` call | `401 {"error": {"message": "Invalid API key", "type": "invalid_request_error", "code": "invalid_api_key"}}` |
| Server not running (wrong port, or `API_SERVER_ENABLED=false`) | `openai.APIConnectionError` | — |

:::note Keys rotate via restart
The key check is a constant-time string comparison, so timing-side-channel probing of the header is not a practical attack. Keys you rotate require a gateway restart; there is no runtime key-reload endpoint.
:::

## 5. Retries: client-side, exponential backoff with jitter

The server attaches no server-side timing hint to its error responses — don't write code that parses one (there is nothing to parse). Retry policy is yours, and the shape that works for an HTTP client is exponential backoff **with jitter**:

```python
import os
import random
import time

import openai

client = openai.OpenAI(
    api_key=os.environ["HERMES_API_KEY"],
    base_url=os.environ.get("HERMES_BASE_URL", "http://localhost:8642/v1"),
)


def _transient(exc: Exception) -> bool:
    """True for errors worth retrying."""
    if isinstance(exc, openai.APIConnectionError):
        return True  # server restarting, port temporarily refused, network blip
    if isinstance(exc, openai.RateLimitError):
        return True  # 429 — in practice upstream provider throttling, not this endpoint (see the note below)
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500


def create_with_backoff(**kwargs):
    """POST /v1/responses, exponential backoff with full jitter.

    Never retry 4xx (400 bad request, 401 auth, 404 unknown id): the server
    is telling you the request is wrong as written — resending the same
    bytes cannot fix it.
    """
    for attempt in range(1, 6):  # 5 tries total
        try:
            return client.responses.create(**kwargs)
        except openai.APIStatusError as exc:
            if not _transient(exc):
                raise  # 4xx — log it, fix the code, don't burn wall-clock
        except (openai.APIConnectionError, openai.RateLimitError):
            pass  # fall through to backoff below
        delay = min(16.0, 0.5 * (2 ** (attempt - 1))) * random.uniform(0.5, 1.5)
        print(f"attempt {attempt} transient — backing off {delay:.2f}s")
        time.sleep(delay)
    raise RuntimeError("POST /v1/responses: retries exhausted")
```

:::warning Keep 4xx out of the retry loop
An HTTP 400 from this server means malformed JSON, a missing `input` field, or mutually exclusive `previous_response_id` + `conversation`; 404 means an unknown id. Retrying those exact same bytes can't succeed. Retry only what `_transient` says, and log everything else loudly.
:::

:::note 429s exist, but not from this endpoint today
Hermes's `/v1/runs` interface returns 429 once 10 concurrent runs are in flight. `POST /v1/responses` does not currently enforce its own limit — a 429 on your Responses calls is coming from upstream provider pressure, not from this server; the backoff above still handles it correctly. If you enable `/v1/responses` throttling one day, `RateLimitError` will be the signal, and the backoff loop above needs no change.
:::

:::note Long-running requests and SDK timeouts
The default openai SDK timeout is 600 s; an agent turn that takes longer (multi-step tool use, web search) raises `openai.APITimeoutError` — a subclass of `APIConnectionError`, so the backoff loop above will retry it. For genuinely long agent runs, pass `timeout` explicitly when constructing the client, or use the streaming route and treat delta lulls as your liveness signal.
:::

## 6. Idempotency

If you split retries across processes and want retries (or an orchestrator re-submitting a task) to not run the agent twice for the same logical request, attach an `Idempotency-Key` header. The server dedupes **non-streaming** requests on it for a 5-minute window:

```python
resp = client.responses.create(
    model="hermes-agent",
    input="In one sentence, what is Hermes?",
    extra_headers={"Idempotency-Key": "order-4171-turn-2"},
)
```

- A **repeat of the same key with the same body** skips the agent run and replays the stored result — in the live test, the first call took 0.24 s and the replay 0.00 s — but still returns a **fresh `resp_` id**: the dedupe unit is the *result*, not the response object. Don't compare ids to prove a dedupe happened; compare the result text or your metrics.
- **Same key + different body** is accepted as a new, separate request — the cache hit requires the request fingerprint (the body content) to match the stored entry (`api_server.py:584`), and on mismatch the server transparently runs a new agent turn and replaces the stored entry. No error is raised, so a small body change silently re-runs the agent; keep the body content-stable for the life of a key.
- **Streaming requests ignore the key entirely.** The `stream: true` branch returns before the idempotency guard in the handler, so an `Idempotency-Key` on a streamed request does nothing — verified live: two identical streamed posts under one key got distinct `resp_` ids and two real agent runs. Dedupe belongs on the non-streaming path only.
- The cache is a 5-minute LRU capped at 1,000 entries, held in server memory — there is no API to list or inspect it, and a server restart empties it.
- **Concurrent duplicates are coalesced.** Two posts with the same key while the first agent run is still in flight share that single run — the server routes both onto one in-flight task (`api_server.py:584`), so a retry-while-running can't double-execute the agent either.
- Generate one key per logical unit of work (e.g., `f"{order_id}-{turn}"`), not per HTTP attempt — that's what makes a retry a **re-send** rather than a **second agent run**.

:::caution The key is not a lock
A repeated `Idempotency-Key` makes the server return the stored response for the first matching request in the window. It does **not** prevent two different keys from running the agent concurrently, nor does it dedupe across a window longer than 5 minutes.
:::

## 7. Chaining, retrieval, and truncation

Multi-turn context is server-side. You don't send the conversation back; you send the id of the last response, and the server reconnects from there — including stored tool calls and their outputs.

```python
import os

import openai

client = openai.OpenAI(
    api_key=os.environ["HERMES_API_KEY"],
    base_url=os.environ.get("HERMES_BASE_URL", "http://localhost:8642/v1"),
)

first = client.responses.create(
    model="hermes-agent",
    input="List the files in the current directory.",
)

second = client.responses.create(
    model="hermes-agent",
    input="Which of those look like tests?",
    previous_response_id=first.id,           # server replays first's full history
)

# Or fetch a stored response back later:
stored = client.responses.retrieve(first.id)
print(stored.status)                          # "completed"
tool_calls = [i.name for i in stored.output if i.type == "function_call"]
print("turn-1 tool calls:", tool_calls)       # [] if turn 1 made no tool calls
```

:::tip Disconnected mid-stream? The response is still recoverable
If a streamed response dies between `response.created` and `response.completed` (network blip, killed client process), the turn is not lost. Hermes persists a snapshot when the stream opens and rewrites it to `status="incomplete"` once it notices the disconnect — keeping whatever output had been assembled so far. Capture the id **from the `response.created` event** (the very first event), then `client.responses.retrieve(id)`: immediately after the disconnect it may still read `in_progress` for a moment; a second later it reads `incomplete` with the partial text. A chained follow-up to that id with `previous_response_id` works as usual — the recovered context is usable, not dead weight.

For dispatch-like workloads (you're submitting a job, not rendering text), the better remediation is different: re-send the exact same request with the same `Idempotency-Key` (§6) instead of salvaging the torn stream. The server recognizes the fingerprint and replays the stored result — one agent run for the money, no torn output to reconcile. (The streaming branch never reaches the idempotency cache, so the replay must be the plain non-streaming call.)
:::

Truncation is opt-in, not automatic: send `truncation="auto"` and the server keeps only the most recent **100** messages of stored history before the agent runs (`api_server.py:2843`). Without it, history is sent whole — and very long chains grow every turn. Either way, for a multi-day agent conversation, checkpoint deliberately by starting a fresh chain and summarizing, rather than assuming the model remembers turn 1.

## 8. What this guide deliberately skipped

- **Named conversations** (`conversation="my-project"` as an alternative to `previous_response_id`) — [full API server reference](/user-guide/features/api-server#named-conversations).
- **Inline image input** (`input_image` parts in `input`) — supported on this endpoint, not covered here.
- **`X-Hermes-Session-Key`** — long-term-memory scope for multi-user frontends.
- **The runs API** (`/v1/runs`) — a pollable alternative for long jobs; see [the API server guide](/user-guide/features/api-server).

Read [the full API server reference](/user-guide/features/api-server) for the complete endpoint surface.
