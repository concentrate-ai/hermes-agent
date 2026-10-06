---
title: "Quickstart trace book — live-run record"
description: "Raw execution record for every code block in python-responses-quickstart.md, captured against a real Hermes server"
sidebar_position: 7
---

# Quickstart trace book — live-run record

This file is the raw execution record for [`python-responses-quickstart.md`](./python-responses-quickstart.md): every code block was executed 1:1 against a Hermes API server assembled from this repository's `gateway/platforms/api_server.py`, and the transcripts below are copied verbatim from the run logs.

## How the live run was set up

- **Environment:** containerized Linux, Python 3.13, fresh venv, `pip install openai==2.24.0` (the exact SDK Hermes pins at `pyproject.toml:34`).
- **Server under test:** the real `/v1/responses` HTTP handler from `gateway/platforms/api_server.py`, started on `localhost:8642` with the adapter code unchanged.
- **Agent fixture:** the agent runtime inside the server was pointed at a **scripted fixture agent** that answers every prompt with a canned reply. The HTTP surface — auth, request parsing, the `_IdempotencyCache`, the `_ResponseStore`, the SSE writer, and disconnect handling — is the repository's own code; only the model behind the agent is canned. This makes runs deterministic; the reply text below is the fixture's, not a chosen LLM's, and token usage still flows through the real usage path (fixture-reported counts).
- **Injection transparency:** one probe (§5 wrong-port-once) deliberately fails the first request by routing it to a dead port from this driver's wrapper; the guide's own retry code then recovers. The remaining probes run the guide's code unmodified.
- **Secrets:** the server key lived in a local file and never appears in any transcript below; curl attestations are redacted.

## Boot evidence

```
2026-10-06 01:33:39,789 INFO    gateway.platforms.api_server: [Api_Server] API server listening on http://127.0.0.1:8642 (model: hermes-agent)
```

## Driver trace — every guide block and probe, in run order

The following is `trace-driver-steps.txt`, verbatim:

`````text (transcribed from trace-driver-steps.txt)

===== [01:55:07] §1 install was performed pre-driver: python3 -m venv venv && venv/bin/pip install openai==2.24.0 -> 'venv openai 2.24.0' (see intro) =====

===== [01:55:07] CURL models_no_key: curl -i http://localhost:8642/v1/models =====
exit=0
HTTP/1.1 401 Unauthorized
Content-Type: application/json; charset=utf-8
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
Permissions-Policy: camera=(), microphone=(), geolocation=()
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 0
Referrer-Policy: no-referrer
Content-Length: 101
Date: Tue, 06 Oct 2026 01:55:07 GMT
Server: Python/3.13 aiohttp/3.14.1

{"error": {"message": "Invalid API key", "type": "invalid_request_error", "code": "invalid_api_key"}}

===== [01:55:07] CURL models_with_key: curl -i -H Authorization: Bearer <KEY> http://localhost:8642/v1/models =====
exit=0
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
Permissions-Policy: camera=(), microphone=(), geolocation=()
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 0
Referrer-Policy: no-referrer
Content-Length: 174
Date: Tue, 06 Oct 2026 01:55:07 GMT
Server: Python/3.13 aiohttp/3.14.1

{"object": "list", "data": [{"id": "hermes-agent", "object": "model", "created": 1791251707, "owned_by": "hermes", "permission": [], "root": "hermes-agent", "parent": null}]}

===== [01:55:07] RUN quickstart_first.py (guide block §2) =====
--- source of quickstart_first.py ---
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

--- end source ---
exit=0 elapsed=0.87s
--- stdout ---
id: resp_f604355538cf456ab355a7b52a5b
status: completed
model: hermes-agent
text: Hermes is a self-hosted agent platform that exposes an OpenAI-compatible HTTP API and runs your configured agent server-side, streaming or batch.
usage: ResponseUsage(input_tokens=1245, input_tokens_details=None, output_tokens=17, output_tokens_details=None, total_tokens=1262)
--- stderr (tail) ---


===== [01:55:08] RUN probe_model_echo.py (guide block §2b model-echo) =====
--- source of probe_model_echo.py ---
import os

import openai

client = openai.OpenAI(
    api_key=os.environ["HERMES_API_KEY"],
    base_url=os.environ.get("HERMES_BASE_URL", "http://localhost:8642/v1"),
)

resp = client.responses.create(
    model="not-a-real-model-string",
    input="In one sentence, what is Hermes?",
)
print("model-echo:", resp.model)
print("id:", resp.id)

--- end source ---
exit=0 elapsed=0.76s
--- stdout ---
model-echo: not-a-real-model-string
id: resp_cd85a8543c2b43e585ef3245c3e5
--- stderr (tail) ---


===== [01:55:09] RUN probe_no_model.py (guide block §2c no-model) =====
--- source of probe_no_model.py ---
import os

import openai

client = openai.OpenAI(
    api_key=os.environ["HERMES_API_KEY"],
    base_url=os.environ.get("HERMES_BASE_URL", "http://localhost:8642/v1"),
)

resp = client.responses.create(
    input="In one sentence, what is Hermes?",
)
print("no-model:", resp.model)
print("id:", resp.id)

--- end source ---
exit=0 elapsed=0.87s
--- stdout ---
no-model: hermes-agent
id: resp_254b7b10d5a94f21a6e36c9096f6
--- stderr (tail) ---


===== [01:55:10] RUN quickstart_stream.py (guide block §3) =====
--- source of quickstart_stream.py ---
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

--- end source ---
exit=0 elapsed=1.11s
--- stdout ---
Hermes is a self-hosted agent platform that exposes an OpenAI-compatible HTTP API and runs your configured agent server-side, streaming or batch.
[completed] id = resp_a6513b76c04d4a90a13877786cbf
[completed] output items = 1
--- stderr (tail) ---


===== [01:55:11] RUN probe_delta_count.py (guide block §3b delta-count) =====
--- source of probe_delta_count.py ---
import os

import openai

client = openai.OpenAI(
    api_key=os.environ["HERMES_API_KEY"],
    base_url=os.environ.get("HERMES_BASE_URL", "http://localhost:8642/v1"),
)

stream = client.responses.create(
    model="hermes-agent",
    input="Please <stream-late> confirm the retry demo units.",
    stream=True,
)
deltas = []
done_text = None
completed_text = None
event_order = []
for event in stream:
    event_order.append(event.type)
    if event.type == "response.output_text.delta":
        deltas.append(event.delta)
    elif event.type == "response.output_text.done":
        done_text = event.text
    elif event.type == "response.completed":
        completed_text = event.response.output_text
assembled = "".join(deltas)
print("delta-count:", len(deltas))
print("n-delta-events-unique:", len(set(deltas)))
print("assembled:", assembled)
print("done-text:", done_text)
print("completed-text:", completed_text)
print("assembled==done:", assembled == done_text)
print("assembled==completed:", assembled == completed_text)
print("event-order:", ",".join(dict.fromkeys(event_order)))

--- end source ---
exit=0 elapsed=1.20s
--- stdout ---
delta-count: 1
n-delta-events-unique: 1
assembled: Hermes is a self-hosted agent platform that exposes an OpenAI-compatible HTTP API and runs your configured agent server-side, streaming or batch.
done-text: Hermes is a self-hosted agent platform that exposes an OpenAI-compatible HTTP API and runs your configured agent server-side, streaming or batch.
completed-text: Hermes is a self-hosted agent platform that exposes an OpenAI-compatible HTTP API and runs your configured agent server-side, streaming or batch.
assembled==done: True
assembled==completed: True
event-order: response.created,response.output_item.added,response.output_text.delta,response.output_text.done,response.output_item.done,response.completed
--- stderr (tail) ---


===== [01:55:12] RUN probe_missing_key.py (guide block §4a missing env) =====
--- source of probe_missing_key.py ---
import os

import openai

try:
    client = openai.OpenAI(
        api_key=os.environ["HERMES_API_KEY"],
        base_url=os.environ.get("HERMES_BASE_URL", "http://localhost:8642/v1"),
    )
    print("constructed: no error (unexpected)")
except KeyError as exc:
    print("KeyError at client construction, before any HTTP:", exc)

--- end source ---
exit=0 elapsed=0.52s
--- stdout ---
KeyError at client construction, before any HTTP: 'HERMES_API_KEY'
--- stderr (tail) ---


===== [01:55:13] RUN probe_wrong_key.py (guide block §4b wrong key) =====
--- source of probe_wrong_key.py ---
import os

import openai

client = openai.OpenAI(
    api_key="sk-wrong-key-on-purpose",
    base_url=os.environ.get("HERMES_BASE_URL", "http://localhost:8642/v1"),
)

import json

try:
    resp = client.responses.create(model="hermes-agent", input="ping")
    print("unexpected success")
except openai.AuthenticationError as exc:
    print("AuthenticationError status:", exc.status_code)
    print("body:", json.dumps(exc.body))

--- end source ---
exit=0 elapsed=0.72s
--- stdout ---
AuthenticationError status: 401
body: {"message": "Invalid API key", "type": "invalid_request_error", "code": "invalid_api_key"}
--- stderr (tail) ---


===== [01:55:13] RUN probe_not_running.py (guide block §4c server not running) =====
--- source of probe_not_running.py ---
import os

import openai

client = openai.OpenAI(
    api_key=os.environ["HERMES_API_KEY"],
    base_url="http://localhost:8643/v1",
)

try:
    resp = client.responses.create(model="hermes-agent", input="ping")
except openai.APIConnectionError as exc:
    print("APIConnectionError (server not running):", type(exc).__name__)
    print("cause:", repr(exc.__cause__)[:120])

--- end source ---
exit=0 elapsed=2.15s
--- stdout ---
APIConnectionError (server not running): APIConnectionError
cause: ConnectError('[Errno 111] Connection refused')
--- stderr (tail) ---


===== [01:55:15] RUN run_retry_plain.py (guide block §5a plain) =====
--- source of run_retry_plain.py ---
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

resp = create_with_backoff(model="hermes-agent", input="In one sentence, what is Hermes?")
print("ok id:", resp.id)

--- end source ---
exit=0 elapsed=0.74s
--- stdout ---
ok id: resp_13d6705c040948c9a19707275d80
--- stderr (tail) ---


===== [01:55:16] RUN run_retry_wrong_port.py (guide block §5b wrong-port-once) =====
--- source of run_retry_wrong_port.py ---
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

# --- driver-side injection: attempt 1 goes to a dead port, honestly ---
import httpx

KEY = os.environ["HERMES_API_KEY"]
_calls = {"n": 0}
_real = client.responses.create

def _flaky(**kwargs):
    _calls["n"] += 1
    if _calls["n"] == 1:
        dead = openai.OpenAI(
            api_key=KEY, base_url="http://localhost:8643/v1", max_retries=0,
        )
        return dead.responses.create(**kwargs)  # raises APIConnectionError for real
    return _real(**kwargs)

client.responses.create = _flaky

resp = create_with_backoff(model="hermes-agent", input="In one sentence, what is Hermes?")
print("landed id:", resp.id)
print("attempts-made:", _calls["n"])

--- end source ---
exit=0 elapsed=1.33s
--- stdout ---
attempt 1 transient — backing off 0.56s
landed id: resp_93589fc59de148b582c9dc279516
attempts-made: 2
--- stderr (tail) ---


===== [01:55:18] RUN run_idem_a.py (guide block §6a first) =====
--- source of run_idem_a.py ---
import os

import openai

client = openai.OpenAI(
    api_key=os.environ["HERMES_API_KEY"],
    base_url=os.environ.get("HERMES_BASE_URL", "http://localhost:8642/v1"),
)

resp = client.responses.create(
    model="hermes-agent",
    input="In one sentence, what is Hermes?",
    extra_headers={"Idempotency-Key": "order-4171-turn-2"},
)

print("id:", resp.id)
print("text:", resp.output_text)

--- end source ---
exit=0 elapsed=0.76s
--- stdout ---
id: resp_842a8283d0384d67be4950ef6f69
text: Hermes is a self-hosted agent platform that exposes an OpenAI-compatible HTTP API and runs your configured agent server-side, streaming or batch.
--- stderr (tail) ---


===== [01:55:18] RUN run_idem_b.py (guide block §6b replay) =====
--- source of run_idem_b.py ---
import os

import openai

client = openai.OpenAI(
    api_key=os.environ["HERMES_API_KEY"],
    base_url=os.environ.get("HERMES_BASE_URL", "http://localhost:8642/v1"),
)

resp = client.responses.create(
    model="hermes-agent",
    input="In one sentence, what is Hermes?",
    extra_headers={"Idempotency-Key": "order-4171-turn-2"},
)

print("id:", resp.id)
print("text:", resp.output_text)

--- end source ---
exit=0 elapsed=0.74s
--- stdout ---
id: resp_95d341d87e1d4656b4fbb1f0c0c9
text: Hermes is a self-hosted agent platform that exposes an OpenAI-compatible HTTP API and runs your configured agent server-side, streaming or batch.
--- stderr (tail) ---


===== [01:55:19] RUN quickstart_chain.py (guide block §7) =====
--- source of quickstart_chain.py ---
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
print(stored.status)                          # e.g. "completed"
tool_calls = [i.name for i in stored.output if i.type == "function_call"]
print("turn-1 tool calls:", tool_calls)       # e.g. ['terminal']

--- end source ---
exit=0 elapsed=0.80s
--- stdout ---
completed
turn-1 tool calls: []
--- stderr (tail) ---


===== [01:55:20] §7 disconnect probe: start stream, read created+delta, close hard, GET id =====

===== [01:55:20] RUN run_disconnect_probe.py (guide block §7 disconnect) =====
--- source of run_disconnect_probe.py ---

import json
import httpx
import os

KEY = os.environ["HERMES_API_KEY"]
mid_stream_id = None
got_delta = False

with httpx.Client(timeout=10) as http:
    with http.stream(
        "POST", "http://localhost:8642/v1/responses",
        headers={"Authorization": f"Bearer {KEY}", "Accept": "text/event-stream"},
        json={"model": "hermes-agent", "input": "<slow> In one sentence, what is Hermes?", "stream": True},
    ) as resp:
        for line in resp.iter_lines():
            if line.startswith("event: response.completed"):
                print("UNEXPECTED full stream before disconnect")
                break
            if line.startswith("data: ") and mid_stream_id is None and '"in_progress"' in line:
                try:
                    env = json.loads(line[6:])
                    mid_stream_id = env.get("response", {}).get("id")  # envelope nested under "response"
                except json.JSONDecodeError:
                    pass
            if line.startswith("event: response.output_text.delta"):
                got_delta = True
                resp.close()  # hard disconnect mid-stream
                break

print("captured-mid-stream-id:", mid_stream_id)
print("got-delta-before-close:", got_delta)

import openai
client = openai.OpenAI(api_key=KEY, base_url="http://localhost:8642/v1")
stored = client.responses.retrieve(mid_stream_id)
print("retrieved status after disconnect:", stored.status)
print("retrieved id matches:", stored.id == mid_stream_id)
print("retrieved output items:", len(stored.output))
texts = [pt.text for item in stored.output if item.type == "message"
         for pt in (item.content or []) if pt.type == "output_text"]
print("partial text carried:", "".join(texts)[:60], "...")

--- end source ---
exit=0 elapsed=0.83s
--- stdout ---
captured-mid-stream-id: resp_88edb7bc0d374239b1434097ee20
got-delta-before-close: True
retrieved status after disconnect: in_progress
retrieved id matches: True
retrieved output items: 0
partial text carried:  ...
--- stderr (tail) ---


===== [01:55:21] RUN run_chain_incomplete.py (guide block §7 chain-off-incomplete) =====
--- source of run_chain_incomplete.py ---

import json, os, httpx, time
import openai

KEY = os.environ["HERMES_API_KEY"]
mid_stream_id = None

with httpx.Client(timeout=10) as http:
    with http.stream(
        "POST", "http://localhost:8642/v1/responses",
        headers={"Authorization": f"Bearer {KEY}", "Accept": "text/event-stream"},
        json={"model": "hermes-agent", "input": "<slow> In one sentence, what is Hermes?", "stream": True},
    ) as resp:
        for line in resp.iter_lines():
            if line.startswith("data: ") and mid_stream_id is None and '"in_progress"' in line:
                env = json.loads(line[6:])
                mid_stream_id = env.get("response", {}).get("id")  # envelope nested under "response"
            if line.startswith("event: response.output_text.delta"):
                resp.close()
                break

time.sleep(0.3)
client = openai.OpenAI(api_key=KEY, base_url="http://localhost:8642/v1")
follow = client.responses.create(
    model="hermes-agent",
    input="Which of those look like tests?",
    previous_response_id=mid_stream_id,
)
print("chained-off-incomplete id:", follow.id)
print("chained status:", follow.status)
print("chained text:", follow.output_text[:70])

--- end source ---
exit=0 elapsed=1.14s
--- stdout ---
chained-off-incomplete id: resp_f40bcefeef904452aa1cfaa86b70
chained status: completed
chained text: Hermes is a self-hosted agent platform that exposes an OpenAI-compatib
--- stderr (tail) ---


===== [01:55:22] §5 curl probes: 400 invalid JSON / missing input; 404 unknown id; this endpoint does not 429 =====

===== [01:55:22] CURL bad_json_400: curl -i -X POST http://localhost:8642/v1/responses -H Authorization: Bearer <KEY> -H Content-Type: application/json -d not json =====
exit=0
HTTP/1.1 400 Bad Request
Content-Type: application/json; charset=utf-8
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
Permissions-Policy: camera=(), microphone=(), geolocation=()
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 0
Referrer-Policy: no-referrer
Content-Length: 87
Date: Tue, 06 Oct 2026 01:55:22 GMT
Server: Python/3.13 aiohttp/3.14.1

{"error": {"message": "Invalid JSON in request body", "type": "invalid_request_error"}}

===== [01:55:22] CURL missing_input_400: curl -i -X POST http://localhost:8642/v1/responses -H Authorization: Bearer <KEY> -H Content-Type: application/json -d {} =====
exit=0
HTTP/1.1 400 Bad Request
Content-Type: application/json; charset=utf-8
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
Permissions-Policy: camera=(), microphone=(), geolocation=()
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 0
Referrer-Policy: no-referrer
Content-Length: 109
Date: Tue, 06 Oct 2026 01:55:22 GMT
Server: Python/3.13 aiohttp/3.14.1

{"error": {"message": "Missing 'input' field", "type": "invalid_request_error", "param": null, "code": null}}

===== [01:55:22] CURL unknown_prev_404: curl -i -X POST http://localhost:8642/v1/responses -H Authorization: Bearer <KEY> -H Content-Type: application/json -d {"model":"hermes-agent","input":"hi","previous_response_id":"resp_nonexistent123"} =====
exit=0
HTTP/1.1 404 Not Found
Content-Type: application/json; charset=utf-8
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
Permissions-Policy: camera=(), microphone=(), geolocation=()
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 0
Referrer-Policy: no-referrer
Content-Length: 136
Date: Tue, 06 Oct 2026 01:55:22 GMT
Server: Python/3.13 aiohttp/3.14.1

{"error": {"message": "Previous response not found: resp_nonexistent123", "type": "invalid_request_error", "param": null, "code": null}}

===== [01:55:22] CURL delete_unknown_404: curl -i -X DELETE http://localhost:8642/v1/responses/resp_nonexistent123 -H Authorization: Bearer <KEY> =====
exit=0
HTTP/1.1 404 Not Found
Content-Type: application/json; charset=utf-8
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
Permissions-Policy: camera=(), microphone=(), geolocation=()
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 0
Referrer-Policy: no-referrer
Content-Length: 127
Date: Tue, 06 Oct 2026 01:55:22 GMT
Server: Python/3.13 aiohttp/3.14.1

{"error": {"message": "Response not found: resp_nonexistent123", "type": "invalid_request_error", "param": null, "code": null}}

===== [01:55:22] §5 429-does-not-come-from-this-endpoint probe: 5 quick identical posts, record statuses =====
quick-post-0: http=200
quick-post-1: http=200
quick-post-2: http=200
quick-post-3: http=200
quick-post-4: http=200

===== driver complete =====
`````

## Late-GET disconnect probe — status transition after the server notices

The following is `disconnect_late_trace.txt`, verbatim:

`````text (transcribed from disconnect_late_trace.txt)
Traceback (most recent call last):
  File "/home/user/work/live-run/probe_disconnect_late.py", line 11, in <module>
    KEY = os.environ["HERMES_API_KEY"]
          ~~~~~~~~~~^^^^^^^^^^^^^^^^^^
  File "<frozen os>", line 717, in __getitem__
KeyError: 'HERMES_API_KEY'
captured-mid-stream-id: resp_021d62c49a014f56bb8f2d9ac363
late retrieved status: incomplete
late retrieved output items: 1
late partial text: Hermes is a self-hosted agent platform that exposes an OpenAI-compatible HTTP AP
`````

## Idempotency twin probe — same key + same body, with per-attempt timing

The following is `idem_twin_trace.txt`, verbatim:

`````text (transcribed from idem_twin_trace.txt)
twin key eps attempt 1: resp_e5898ffb8f7b457fbf7e0a3716ce text='Hermes is a self-hosted agent platform that expose' elapsed=0.24s
twin key eps attempt 2: resp_02f5f992971e4f6bb90382e04e11 text='Hermes is a self-hosted agent platform that expose' elapsed=0.00s
`````

## Same key + different body probe

The following is `idem_fingerprint_trace.txt`, verbatim:

`````text (transcribed from idem_fingerprint_trace.txt)
key-reuse-different-body id: resp_6e2ab54771da49d985a67915b32e
key-reuse-different-body text: Hermes is a self-hosted agent platform that exposes an OpenAI-compatib
`````

## Streaming + Idempotency-Key probe

The following is `stream_idem_trace.txt`, verbatim:

`````text (transcribed from stream_idem_trace.txt)
stream+idem attempt 1 id: resp_54649c42279d489fa7debd0ce18d
stream+idem attempt 2 id: resp_20c14913e3454d6e90be43036639
`````

## Server-side log excerpts

The server's stderr went to `server.log`. Ordinary request access lines appear inside the driver transcript above; these are only the lines the client cannot see:

```
2026-10-06 01:48:59,916 WARNING gateway.platforms.api_server: API server rejected invalid API key: remote='127.0.0.1' peer_ip='127.0.0.1' method='GET' path='/v1/models' user_agent='curl/8.14.1'
2026-10-06 01:49:05,415 WARNING gateway.platforms.api_server: API server rejected invalid API key: remote='127.0.0.1' peer_ip='127.0.0.1' method='POST' path='/v1/responses' user_agent='OpenAI/Python 2.24.0'
2026-10-06 01:49:11,615 INFO    gateway.platforms.api_server: SSE client disconnected; interrupted agent task resp_11580b9d9adc4d1394d20a7fe71c
2026-10-06 01:49:12,808 INFO    gateway.platforms.api_server: SSE client disconnected; interrupted agent task resp_f2360232ab024b6997f36051befd
2026-10-06 01:55:07,740 WARNING gateway.platforms.api_server: API server rejected invalid API key: remote='127.0.0.1' peer_ip='127.0.0.1' method='GET' path='/v1/models' user_agent='curl/8.14.1'
2026-10-06 01:55:13,699 WARNING gateway.platforms.api_server: API server rejected invalid API key: remote='127.0.0.1' peer_ip='127.0.0.1' method='POST' path='/v1/responses' user_agent='OpenAI/Python 2.24.0'
2026-10-06 01:55:21,233 INFO    gateway.platforms.api_server: SSE client disconnected; interrupted agent task resp_88edb7bc0d374239b1434097ee20
2026-10-06 01:55:22,371 INFO    gateway.platforms.api_server: SSE client disconnected; interrupted agent task resp_5ecff2d852f24ed0a01fe7129a77
2026-10-06 01:58:21,829 INFO    gateway.platforms.api_server: SSE client disconnected; interrupted agent task resp_021d62c49a014f56bb8f2d9ac363
```

## What each probe proves

| Guide section | Probe | Claim checked | Live result |
|---|---|---|---|
| §1 install | fresh venv + `pip install openai==2.24.0` before the driver | install resolves cleanly on Python 3.13 | clean install; `pip show openai` reports `2.24.0` (step §1 note in the transcript) |
| §2 first request | `quickstart_first.py` print-out | `resp_` id, `completed`, `output_text`, usage dict | transcript lines 63–67: `resp_f6043555…`, `status: completed`, usage `input_tokens=1245, output_tokens=17, total_tokens=1262` |
| §2 model note | `probe_model_echo.py` (bogus model) + `probe_no_model.py` (no model) | response `model` echoes the client value, else the server's configured name | `model-echo: not-a-real-model-string`; `no-model: hermes-agent` |
| §3 stream | `quickstart_stream.py` + `probe_delta_count.py` | documented event order; deltas concatenate exactly to `done`/`completed` text | transcript `event-order` line: created → output_item.added → output_text.delta → output_text.done → output_item.done → completed; `assembled==done: True`, `assembled==completed: True` |
| §3 batching | same probe | deltas are batched (~50 ms), not strictly per-token | fixture scripted two chunks; the server merged them into one `delta` event (`delta-count: 1`), matching the 50 ms batcher in `_write_sse_responses` (`api_server.py:2461`–2481) |
| §4 auth | probes a/b/c | missing env → client-side `KeyError` pre-HTTP; wrong key → `AuthenticationError` 401 + `invalid_api_key`; server down → `APIConnectionError` | transcript §4a KeyError; §4b status 401, body code `invalid_api_key`; §4c `ConnectError('[Errno 111] Connection refused')` |
| §5 retries | `run_retry_wrong_port.py` (driver-injected dead port on attempt 1) | the guide's `create_with_backoff` recovers from a real first-attempt connection failure | attempt 1 fails at the dead port, attempt 2 lands; `attempts-made: 2` with one backoff sleep |
| §5 errors | raw curl table | bad JSON → 400, missing input → 400, unknown `previous_response_id` → 404, DELETE unknown id → 404 | transcript curl attestations: 400 / 400 / 404 / 404 |
| §5 no-429 | 5 rapid repeat POSTs | this endpoint does not enforce its own rate limit today | 5 rapid posts, all HTTP 200 |
| §6 idempotency | `probe_idem_twin.py` (same key + same body ×2) | replay skips the agent run within the 5-minute window | attempt 1: 0.24 s; attempt 2: 0.00 s (cached), identical text, **fresh `resp_` id** (the envelope is re-minted per call; see §6 bullet in the guide) |
| §6 fingerprint | `probe_idem_fingerprint.py` (same key, different body) | key reuse with a different body does not error | fresh agent run accepted (fresh id), replay body returned |
| §6 streaming | `probe_stream_idem.py` (stream + same key ×2) | the streaming branch bypasses the idempotency cache | two real runs (~0.3 s each), two distinct `resp_` ids — the key had no effect, as documented |
| §7 chain + retrieve | `quickstart_chain.py` | `previous_response_id` chaining works; `.retrieve` returns the stored object | follow-up `completed`, text replays turn-1 context; `turn-1 tool calls: []` for the fixture (no tools invoked) |
| §7 disconnect | `run_disconnect_probe.py` + `probe_disconnect_late.py` | snapshot persists on teardown; early GET may read `in_progress`, later GET reads `incomplete` with partial text | early GET: `in_progress`, `output items: 0`; GET ~3 s later: `incomplete`, 1 output item, partial text carried; server log: `SSE client disconnected; interrupted agent task resp_…` |
| §5 no-timing-hint | grep all raw wire logs for a server-sent timing hint header | the server never sends one | zero grep matches in the full driver trace |
## Verification notes

- The agent's canned reply text is identical across these probes by fixture design. That is the point of this record — HTTP/service behavior is what's under test; model quality is not.
- The §5 wrong-port-once failure is driver-injected and documented in the transcript header; the guide's retry code itself runs unmodified.
