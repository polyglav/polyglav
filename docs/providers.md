# Providers

Providers are the model backends. Polyglav speaks OpenAI-compatible `/v1/chat/completions` to every provider. They differ only in base URL, default model, and occasionally auth or payload details. Each implements the event-generator `chat()` contract the agent loop consumes.

## Bundled provider plugins

The vendor providers ship as bundled plugins. The core keeps the base classes (`BaseProvider`, `OpenAICompatibleProvider`), the generic `openai-compatible` fallback, and the detection/registry mechanisms, so any external plugin can add providers through the same `register_providers` hook. The bundled plugins are in the default `plugins` config and load like any other plugin, so a disabled or removed one drops that provider.

| Plugin | Provider | Default base URL | Default model |
|--------|----------|------------------|----------------|
| `polyglav-core-anthropic` | `anthropic` | `https://api.anthropic.com/v1` | `claude-sonnet-4-20250514` |
| `polyglav-core-groq` | `groq` | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| `polyglav-core-ollama` | `ollama` | `https://api.ollama.com` | `llama3.2` |
| `polyglav-core-openai` | `openai` | `https://api.openai.com/v1` | `gpt-4o-mini` |
| `polyglav-core-opencode` | `opencode` | `https://opencode.ai/zen/v1` | `kimi-k3` |
| `polyglav-core-opencode` | `opencode-go` | `https://opencode.ai/zen/go/v1` | `deepseek-v4-flash` |

`openai-compatible` is the generic fallback in the core for any other OpenAI-compatible endpoint, for local models, gateways, or self-hosted servers.

`opencode` (Zen) and `opencode-go` (Go) are the two hosted catalogs at `opencode.ai`. Both share one OpenCode API key, stored with `/connect` in the provider registry like any other provider (no environment variable is consulted). Zen is the curated multi-model gateway. Go is the low-cost subscription for open coding models. Model refs accept the `opencode/<model-id>` and `opencode-go/<model-id>` conventions as well as bare model ids, and the prefix is stripped before the request. A successful model listing is an inventory, not an entitlement check: inference still requires the matching subscription. Fetch the current lineup from `https://opencode.ai/zen/v1/models` and `https://opencode.ai/zen/go/v1/models`. These endpoints sit behind Cloudflare bot protection, which rejects urllib's default `Python-urllib/<ver>` user agent with `HTTP 403: error code: 1010`. Provider requests send an identifying `polyglav/<version>` `User-Agent` and an `x-opencode-session` header bound to the run's own session id (OpenCode uses it for routing and prompt caching, and Go rejects requests without it), so `/connect`, `/models list`, and chat work, and a resumed run reuses its provider-side session.

## Configuration

`provider`, `base_url`, `model`, `temperature`, and `max_tokens` are configured in the global or local config (see [config.md](config.md)). The API key is **not** a config value. It lives in the global provider registry (`~/.config/polyglav/providers.json`, one key per provider) and is managed through `/connect`:

```json
{
  "provider": "openai",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o-mini",
  "temperature": 0.7
}
```

The engine resolves the API key for the active provider from the provider registry (a `(key)` entry from `/connect`), falling back to `""`, and no environment variable is consulted. A custom `base_url` stored there is used when the config leaves it empty. The approved-model history (`~/.config/polyglav/models.json`) records every model used for `/models`.

## Model refs and approval

A **model ref** `provider/model` (e.g. `opencode-go/deepseek-v4-flash`, `ollama/gpt-oss:20b-cloud`) unfolds to the provider, its default base URL, and the bare model. It is accepted wherever a model is set (`/model <ref>`, `--model <ref>`, a config `model`, and a role's `model` field), so a type or team can pin provider and model together. Only a known provider (core or plugin) with a default base URL unfolds. Anything else is treated as a bare model id. Using an unfolded model is **gated on approval**: the model must appear in `models.json`, otherwise the engine prompts to approve it. The surfaces:

- **Interactive** - the REPL asks on load for an unapproved configured ref, `/model <ref>` asks before switching, and `/teams run` pre-checks the stages' type models and asks once for unapproved ones.
- **Headless** - an explicit `--model` auto-approves (records into `models.json`). A model referenced by a role or team is denied unless `--approve-model` is passed (`polyglav run --approve-model`, `polyglav jobs add --approve-model`, `polyglav fleet config --approve-model`). A denied run stops with a clear "model not approved" error.

A ref naming a provider with no stored key still switches to it but prints `run /connect <provider>` (the request then surfaces the auth error until you connect).

## Auto-detection

When the configured provider name is unknown, or when `base_url` matches a known host, the provider is detected from the URL. Each provider class declares `HOST_PATTERNS`, the substrings of the base URL that identify it (e.g. `openai.com`, `groq.com`, `anthropic.com`, `ollama.com` / `ollama.ai`, and `opencode.ai/zen` for Zen, `opencode.ai/zen/go` for Go). `detect_provider()` scans the merged provider set (core `PROVIDERS` plus plugin providers) and returns the provider whose pattern matches, preferring the longest match so path-distinguishing hosts like Zen vs Go resolve correctly. It falls back to `openai-compatible` for anything else. `/connect` uses the same detection, so passing a base URL switches the provider automatically. A URL equal to a plugin provider's default base URL selects that plugin provider even without a host pattern (see [plugins.md](plugins.md)). A registry-named custom provider (one created by `/connect <url>`) resolves as an OpenAI-compatible connection.

## Setting up

`/connect` connects a provider and stores its API key (and any custom base URL) in the global `providers.json` registry. It never touches the model, which is picked separately with `/model`:

- `/connect` - interactive picker: a numbered list of known providers (core + plugins) with a `(key)` marker when a key is stored. The prompt accepts a number, a provider name, or a URL.
- `/connect <name>` - connect a known provider by name (e.g. `ollama`, `openai`, `groq`, `anthropic`, `opencode`, `opencode-go`). The provider's default base URL is preset. You only enter the API key. A stored key is shown as the default, so press Enter to keep it or type to replace it (re-enter a missing or stale key).
- `/connect <url>` - connect by URL. A known host (or a plugin provider's default URL) selects that provider with the URL as its base URL. Anything else creates a named custom provider, with the name derived from the host (e.g. `https://llm.acme.example/v1` -> `acme-example`).
- `/connect <url> <name>` - custom provider with an explicit name instead of the derived one.

All forms **test the connection** (a `GET <base_url>/v1/models` probe) before saving: broken values are rejected unless you confirm `Save anyway?`. A successful connect prints `Connected to <provider> (<base_url>)`, records the entry in `providers.json`, writes `provider`/`base_url` into the config, and points you at `/models list <provider>` to pick a model. Related surfaces: `/model <name>` shows or switches the active model (a `provider/model` ref switches provider and model together, approving the model), `/models` lists the configured/approved models, `/models list [provider]` probes a provider's advertised models, `/provider <name>` shows or switches the active provider, and `polyglav run --provider ... --model ... --base-url ...` provides headless overrides. Connection probing is gated by the `connect_check` config (default `true`). Set it to `false` to skip the probes (e.g. offline or flaky networks). `OpenAICompatibleProvider.check_connection()` returns `(ok, message)` by reusing `_fetch_models()`, the shared `GET /v1/models` helper that `list_models()` also uses.

## The `chat()` contract

`BaseProvider.chat(messages, stream=True, tools=None)` is a generator yielding events that the agent loop reacts to:

| Event | Payload | Meaning |
|-------|---------|---------|
| `thinking` | `content` | Reasoning tokens (from `reasoning_content` or `reasoning` deltas - some OpenAI-compatible endpoints such as ollama.com use `reasoning`) |
| `token` | `content` | Streamed content token(s) |
| `tool_calls` | `tool_calls` | Completed function-call objects requested by the model |
| `error` | `code`, `message` | Provider/network/HTTP error |
| `done` | `reason`, `usage` | Stream finished. `reason` is the finish reason, `usage` token counts when reported |

The loop runs one SSE stream per turn. Content-only output is a single round trip. `tool_calls` events append messages, execute the calls, and continue the loop until the model answers. The `<thinking>` marker split for reasoning embedded in content lives in the engine, so thinking stays separate from content. `chat_nonstreaming(messages, tools=None)` is the non-streaming companion, used only for auxiliary decisions (query refinement, tool-result analysis, and compaction), never the main path.

## How the provider works

`OpenAICompatibleProvider` (`src/polyglav/providers/base.py`) builds an OpenAI-format payload (`model`, `messages`, `temperature`, optional `max_tokens`, optional `tools`, `stream`), POSTs it to `<base_url>/v1/chat/completions`, and streams the SSE response line by line. Deltas accumulate: `reasoning_content` (or `reasoning` on endpoints such as ollama.com) becomes `thinking` events, `content` becomes `token` events, and fragmented `tool_calls` deltas are reassembled by index into complete function-call objects. HTTP and network errors are returned as `error` events. `max_tokens` defaults to `8192` (sent to the provider, overriding low provider-side defaults like Ollama's 2048 cap). Set it to `0` to omit it from the payload, so the provider's own default applies. Hitting the limit prints a warning and logs a session `errors` entry, and the warning text distinguishes a configured cap from the provider's default.

## Session binding

A provider carries a `session_id` bound to the run's own session. The engine sets it when it builds its own provider (the root, or a sub-agent whose type pins a model) and rebinds it whenever `load_or_create_session` switches sessions, so a resumed or focused run reuses the same provider-side session. Shared providers (a sub-agent without its own model reuses the caller's) keep the caller's binding. Vendors that support server-side sessions read the attribute (for example the OpenCode providers send it as `x-opencode-session`), and a provider that mints its own id uses it unless one is passed in.

## Requesting reasoning

The `reasoning` config (default `"auto"`) tells the model reasoning is desired and controls its token budget. It is orthogonal to `show_thinking`, which only controls display. Values: `false`/`"off"` = do not request, `true`/`"on"`/`"auto"` = request with the provider default, `"low"`/`"medium"`/`"high"` = explicit budget hint. The provider maps it to its own parameter:

| Provider | off / false | low / medium / high | on / auto |
|----------|-------------|----------------------|-----------|
| `openai` | no `reasoning_effort` | `reasoning_effort = "low"\|"medium"\|"high"` | `reasoning_effort = "medium"` |
| `anthropic` | `thinking: {type: "disabled"}` | `thinking: {type: "enabled", budget_tokens: 1024\|2048\|4096}` | `thinking: {type: "enabled", budget_tokens: 2048}` |
| `ollama` (Qwen) | `enable_thinking: false` | `enable_thinking: true` (`chat_template_kwargs.thinking: true`) | `enable_thinking: true` |
| other / `openai-compatible` / `opencode` / `opencode-go` | nothing | `reasoning_effort` pass-through | nothing (provider default) |

The `opencode` and `opencode-go` providers echo captured reasoning back to the API: the assistant `thinking` from an earlier turn is sent as `reasoning_content`, which Console Go requires in thinking mode when a turn continues after tool calls. Every other provider drops the internal `thinking` field, since some OpenAI-compatible endpoints (the official DeepSeek reasoner among them) reject `reasoning_content` in the input. The behavior is a provider class attribute (`ECHO_REASONING`, default `false`), so a new provider can opt in the same way.

## Adding a provider

The core substrate (`BaseProvider`, `OpenAICompatibleProvider`, the `PROVIDERS` registry, and `detect_provider`) stays in `src/polyglav/providers/`. Vendor providers ship as bundled plugins under `plugins/`, and any external plugin can register providers too:

1. Subclass `OpenAICompatibleProvider` and set `DEFAULT_BASE_URL` / `DEFAULT_MODEL`. Override `_headers()` / `_payload()` only for non-standard auth or request bodies.
2. Declare `HOST_PATTERNS`, the URL substrings that identify the provider, so `/connect <url>` auto-selects it. Make patterns specific enough to disambiguate providers sharing a host (e.g. `opencode.ai/zen` vs `opencode.ai/zen/go`).
3. Implement `register_providers(providers)` in the plugin entry module, adding `providers[name] = ProviderClass`.
4. Declare the provider names in the manifest's `provides.providers` list for `/plugins` display.

An external plugin registering a provider with the same name as a bundled one does not override it, because the core `PROVIDERS` registry wins on name conflicts. Plugins that want a different default can use their own provider name. Full plugin layout and manifest fields in [plugins.md](plugins.md).

## Streaming contract

The underlying SSE utility (`src/polyglav/utils/http.py`) reads the stream line by line with byte-buffered decoding, so multi-byte UTF-8 split across read chunks is handled correctly. Keep-alive and mid-stream errors surface as `error` events. A stream that ends without a completion event and with no streamed content is re-requested up to `1 + stream_retries` times (default 3 total attempts) with `stream_retry_delay` seconds between attempts before the "Stream ended before a completion event" error is reported. When tool calls have already run in the turn, the warning notes that the tool results are saved and the answer can be retried with a follow-up message.
