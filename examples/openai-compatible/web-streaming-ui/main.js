/**
 * Streaming web UI against any OpenAI-compatible endpoint.
 *
 * Config lives in a settings panel (base URL, API key, model) persisted in
 * localStorage — the browser twin of the samples' env-var contract
 * (OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL). Mock mode (`?mock=1` or
 * the settings toggle) substitutes a local SSE generator emitting the exact
 * wire envelope a real server sends, so the parser path is identical with or
 * without a network call.
 *
 * Pure helpers (frame parsing, metrics, mock decision) are exported so a Node
 * test can import them; DOM wiring is guarded and only runs in a browser.
 */

/** @typedef {{ role: 'user' | 'assistant', content: string }} ChatMessage */

/**
 * Incremental SSE frame parser: feed it decoded text chunks, get back the
 * data-payload strings of complete `data:` frames. Handles frames split
 * across chunk boundaries and the CRLF variant some servers send.
 *
 * @param {() => void} [onDone] invoked exactly once when a `data: [DONE]` sentinel is seen
 * @returns {{ feed(text: string): string[], isDone(): boolean }}
 */
export function createSSEFrameParser(onDone) {
  let buffer = "";
  let done = false;
  return {
    /**
     * @param {string} text decoded chunk from the response stream
     * @returns {string[]} complete data-frame payloads (JSON strings or `[DONE]`)
     */
    feed(text) {
      buffer += text.replace(/\r\n/g, "\n");
      /** @type {string[]} */
      const payloads = [];
      let sep;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const dataLines = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim());
        if (dataLines.length === 0) continue; // ignore comments/keep-alives
        const payload = dataLines.join("\n");
        if (payload === "[DONE]") {
          if (!done) {
            done = true;
            if (onDone) onDone();
          }
          continue;
        }
        payloads.push(payload);
      }
      return payloads;
    },
    /** @returns {boolean} whether the [DONE] sentinel has been seen */
    isDone() {
      return done;
    },
  };
}

/**
 * Extract the assistant delta text from one chat-completions chunk.
 * Returns the empty string for non-content frames (role-only, usage, etc.).
 *
 * @param {string} payload JSON string of one SSE data frame
 * @returns {string} delta content, possibly empty
 */
export function extractDeltaText(payload) {
  try {
    const chunk = JSON.parse(payload);
    return chunk?.choices?.[0]?.delta?.content ?? "";
  } catch {
    return ""; // a malformed frame is skipped, not fatal — real streams can contain keep-alives
  }
}

/**
 * Tokens (delta frames) per second, from the first delta's arrival time.
 *
 * @param {number} deltaCount number of delta frames received
 * @param {number} startMs performance.now() timestamp when streaming began
 * @param {number} nowMs performance.now() timestamp at measurement
 * @returns {number} tokens per second, or 0 when the stream just started
 */
export function computeTokensPerSecond(deltaCount, startMs, nowMs) {
  const elapsed = nowMs - startMs;
  if (deltaCount === 0 || elapsed <= 0) return 0;
  return Math.round((deltaCount / elapsed) * 1000);
}

/**
 * Format a milliseconds value for the metrics header.
 *
 * @param {number} ms
 * @returns {string} e.g. "412 ms"
 */
export function formatMs(ms) {
  return `${Math.round(ms)} ms`;
}

/**
 * Decide whether the UI runs in mock mode: explicit `?mock=1` wins; the
 * stored preference is honored otherwise. Only ?mock=0 forces it off.
 *
 * @param {string} query search string, e.g. "?mock=1"
 * @param {boolean} storedPreference the "mockStream" localStorage flag
 * @returns {boolean}
 */
export function shouldUseMock(query, storedPreference) {
  const params = new URLSearchParams(query);
  if (params.has("mock")) return params.get("mock") !== "0";
  return storedPreference;
}

/**
 * Local SSE generator standing in for the network. Emits the identical
 * envelope the UI's fetch path consumes: `data: {chunk}` frames with
 * `choices[0].delta.content`, then `data: [DONE]`, spread over ~2s.
 *
 * @param {string} prompt the user's message (echoed back token-by-token)
 * @returns {AsyncIterable<string>} SSE frames as decoded text chunks
 */
export async function* mockSSEStream(prompt) {
  const reply = `Hello! You said: "${prompt}". This reply streams from a local mock generator — no network calls are made. The SSE envelope is identical to a real OpenAI-compatible server, so the same parser renders it token by token.`;
  const words = reply.split(" ");
  const frameDelayMs = 2000 / words.length;
  for (const word of words) {
    const chunk = {
      id: "chatcmpl-mock",
      object: "chat.completion.chunk",
      created: 0,
      model: "mock",
      choices: [{ index: 0, delta: { content: `${word} ` }, finish_reason: null }],
    };
    yield `data: ${JSON.stringify(chunk)}\n\n`;
    await new Promise((resolve) => setTimeout(resolve, frameDelayMs));
  }
  yield "data: [DONE]\n\n";
}

/**
 * Open the completion stream: real fetch or the mock generator. Both return
 * an async iterable of decoded text chunks, so the consumer is identical.
 *
 * @param {{ baseUrl: string, apiKey: string, model: string }} config
 * @param {ChatMessage[]} history full conversation, newest message last
 * @param {boolean} mock when true, never touches the network
 * @returns {AsyncIterable<string>}
 */
export async function openCompletionStream(config, history, mock) {
  if (mock) {
    const last = history[history.length - 1];
    return mockSSEStream(last?.content ?? "");
  }
  const response = await fetch(`${config.baseUrl.replace(/\/$/, "")}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.apiKey}`,
    },
    body: JSON.stringify({ model: config.model, messages: history, stream: true }),
  });
  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => "");
    throw new Error(`Endpoint returned ${response.status}: ${detail.slice(0, 300)}`);
  }
  const decoder = new TextDecoder();
  const reader = response.body.getReader();
  return (async function* () {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      yield decoder.decode(value, { stream: true });
    }
  })();
}

// ---------------------------------------------------------------------------
// Browser wiring — everything below only runs when a DOM is present.
// ---------------------------------------------------------------------------

const STORAGE_KEY = "web-streaming-ui.settings";

const DEFAULTS = Object.freeze({
  baseUrl: "https://api.openai.com/v1",
  apiKey: "",
  model: "gpt-4o-mini",
});

function loadSettings() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") };
  } catch {
    return { ...DEFAULTS };
  }
}

function saveSettings(settings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

function main() {
  const el = {
    badge: document.getElementById("mock-badge"),
    ttft: document.getElementById("ttft"),
    tps: document.getElementById("tps"),
    settings: document.getElementById("settings"),
    settingsToggle: document.getElementById("settings-toggle"),
    baseUrl: document.getElementById("base-url"),
    apiKey: document.getElementById("api-key"),
    model: document.getElementById("model"),
    mockToggle: document.getElementById("mock-toggle"),
    chat: document.getElementById("chat"),
    error: document.getElementById("error"),
    composer: document.getElementById("composer"),
    prompt: document.getElementById("prompt"),
    send: document.getElementById("send"),
  };

  /** @type {ChatMessage[]} */
  const history = [];
  let mock = shouldUseMock(window.location.search, loadSettings().mock === true);

  function syncSettingsUI() {
    const settings = loadSettings();
    el.baseUrl.value = settings.baseUrl;
    el.apiKey.value = settings.apiKey;
    el.model.value = settings.model;
    el.mockToggle.checked = mock;
    el.badge.classList.toggle("visible", mock);
    if (mock) {
      el.apiKey.disabled = true;
      el.baseUrl.disabled = true;
    } else {
      el.apiKey.disabled = false;
      el.baseUrl.disabled = false;
    }
  }

  el.settingsToggle.addEventListener("click", () => el.settings.classList.toggle("open"));

  el.mockToggle.addEventListener("change", () => {
    mock = el.mockToggle.checked;
    saveSettings({ ...loadSettings(), mock });
    if (window.location.search.includes("mock=")) {
      const url = new URL(window.location.href);
      mock && url.searchParams.get("mock") !== "1"
        ? url.searchParams.set("mock", "1")
        : url.searchParams.delete("mock");
      window.history.replaceState(null, "", url);
    }
    syncSettingsUI();
  });

  el.composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = el.prompt.value.trim();
    if (!text) return;
    el.error.classList.remove("visible");
    const settings = loadSettings();
    if (!mock && (!settings.apiKey || !settings.baseUrl)) {
      el.error.textContent = "Set an API key and base URL in Settings, or enable Mock stream.";
      el.error.classList.add("visible");
      return;
    }

    history.push({ role: "user", content: text });
    const userMsg = document.createElement("div");
    userMsg.className = "msg user";
    userMsg.textContent = text;
    el.chat.appendChild(userMsg);

    const reply = document.createElement("div");
    reply.className = "msg assistant";
    const cursor = document.createElement("span");
    cursor.className = "cursor";
    cursor.textContent = "▍";
    reply.appendChild(cursor);
    el.chat.appendChild(reply);
    el.prompt.value = "";
    el.send.disabled = true;

    const start = performance.now();
    let ttftMs = null;
    let deltaCount = 0;
    let lastTpsUpdate = 0;

    try {
      const stream = await openCompletionStream(
        { baseUrl: settings.baseUrl, apiKey: settings.apiKey, model: settings.model },
        history,
        mock,
      );
      const parser = createSSEFrameParser();
      for await (const chunk of stream) {
        for (const payload of parser.feed(chunk)) {
          const text = extractDeltaText(payload);
          if (!text) continue;
          if (ttftMs === null) {
            ttftMs = performance.now() - start;
            el.ttft.textContent = formatMs(ttftMs);
          }
          deltaCount += 1;
          cursor.before(document.createTextNode(text));
          // Throttle the per-second readout; the final value is written after the loop.
          const now = performance.now();
          if (now - lastTpsUpdate > 100) {
            lastTpsUpdate = now;
            el.tps.textContent = computeTokensPerSecond(deltaCount, start, now).toString();
          }
        }
      }
      history.push({ role: "assistant", content: reply.textContent ?? "" });
      el.tps.textContent = computeTokensPerSecond(deltaCount, start, performance.now()).toString();
    } catch (err) {
      el.error.textContent = err instanceof Error ? err.message : String(err);
      el.error.classList.add("visible");
    } finally {
      cursor.remove();
      el.send.disabled = false;
      el.prompt.focus();
    }
  });

  syncSettingsUI();
  el.prompt.focus();
}

if (typeof document !== "undefined" && document.getElementById("composer")) {
  main();
}
