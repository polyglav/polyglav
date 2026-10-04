# Architecture

Polyglav is a terminal-based agentic REPL core: the model is the planner, the tool registry is how it acts. It is a zero-dependency Python app (stdlib only) built around a **single agent loop**: one SSE stream per turn where the model emits content or requests tool calls, which the loop executes and feeds back until the model answers.

## The three core layers

1. **Agent loop** (`src/polyglav/engine.py`) - the headless core. Each turn runs a single streaming request. The provider's `chat()` is a generator yielding events the engine reacts to:
   - `thinking` / `token` - streamed to the sink (`UISink`)
   - `tool_calls` - appends a `tool` part per call (name/input), executes each call, fills in its result, then continues the loop
   - `error` - records and prints, then bails
   - `done` - closes the turn (status, end timestamp) and stops

2. **ToolRegistry** (`src/polyglav/tools/registry.py`) - the single dispatch point. The model invokes tools via OpenAI function calling, slash commands are thin wrappers calling the same `execute()`. The loop never special-cases tool names - per-tool behavior comes from registration metadata. See [tools.md](tools.md).

3. **Commands** (`src/polyglav/commands/`) - user-facing affordances. A command either wraps a tool or performs a local action (`/model`, `/session`, `/sessions`).

Providers (`src/polyglav/providers/`) are OpenAI-compatible `/v1/chat/completions` backends implementing the event-generator `chat()` contract. See [providers.md](providers.md).

## Engine and TurnResult

`Engine.chat(text) -> TurnResult` is the front-end-agnostic entry point, called by the REPL (`ChatLoop`), the headless CLI (`polyglav run`), and the HTTP API (`polyglav serve`). A `TurnResult` carries:

```python
{content, thinking, tool_calls, errors, duration, usage,
 model, provider, session, status}
```

`status` is `ok`, `error`, `empty`, `truncated`, or `cancelled`. Any front-end addresses sessions via `Engine.load_or_create_session(name)`. `Engine.chat_tool(name, args)` runs a `loop`-registered tool (e.g. `delegate`) as a persisted agent-loop turn: the tool call and result land in the session, then the model streams its final answer.

## Runs

Every engine instance is a run, tracked in a process-local `RunRegistry` (`src/polyglav/runs.py`) shared across the delegation tree. A run records a numeric `id`, the agent `role`, the `session`, the `session_id` (a durable six-character handle, empty for explicit names), the `parent` run id and its ordered `children`, a `status` (`running`, `done`, or `error`), the `task` brief, and timestamps. Delegated and team-stage engines register as children of the caller (`_new_sub_engine` passes the registry and parent id) and are finished when their `chat` returns, and the registry keeps the engine so a run can be re-entered. `RunRegistry.runs()` is the flat creation-order call log, and `children(id)` walks the tree. Every run also carries a plain-text `buffer` (capped by `run_buffer_max_lines`, default 2000, `0` = unlimited): a sub-engine's UI is a `BufferUI`, so its streamed output, tool lines, and footer land in the run instead of the terminal, while a focused run rebuilt for the REPL keeps the terminal UI. `/focus log [n]` prints the focused run's buffer. This is the data model the focus and handoff command surface builds on.

## Focus

`FocusManager` (`src/polyglav/focus.py`) owns the REPL's focus stack, keyed by run id. `ChatLoop.active()` returns the engine for the focused run and `ChatLoop.run()` routes turns and slash commands to it, so the operator talks to whichever agent is in focus. Focus only navigates: a run with a retained engine is attached directly, and a past run is rebuilt by `Engine.run_engine`, which resumes the run's own session and role instead of minting a name. `FocusManager.back()` walks the stack back and `reset()` returns to the root run, repointing `ReplUI._loop` so rendering and confirms follow the active engine. The `prompt_role` config (default false) prefixes the prompt with the active role (e.g. `Assistant >>>`). The `/focus` command surfaces the same model: no args prints the current run, the run tree (each run showing its id, session, and session id, with a `↔ Switch to <role>` marker), and the call log, and it attaches or moves by `#run`, `#session_id`, `session:`, `root`, `parent`, `child`, `sibling`, `next`, `prev`, or `back`. The `handoff` tool lets an agent do the same at run time: it marks its own run `paused` or `done`, resolves `parent`/`child`/`sibling`/`root`/`#run`/`#session_id`/session name against the registry, and records a pending handoff that `ChatLoop` applies after the turn, so focus follows the target run once the model stops. The `focus_on_delegate` config (`off`, `ask`, `on`, default `on`) does the same for an ordinary `delegate` call or a team run: when it fires, the `delegate`/`team` tool records a pending focus on the child run (`TurnResult.run_id`, the last stage for a team) and the turn still finishes, so the REPL follows the sub-agent while the caller's answer completes.

## Memory

A run's own session is the context within a run. Across runs, continuity is bounded memory owned by `src/polyglav/memory.py`, one compacted Markdown summary per scope under `.polyglav/memory/` (`roles/<role>.md`, `teams/<name>.md`, `jobs/<name>.md`). Role memory is injected into a sub-agent's system prompt and refreshed after its run, and team/job memory is injected into briefs and refreshed after their runs, all through the same compaction summarizer with the previous memory as a seed. `memory`, `memory_scopes`, and `memory_max_chars` gate and cap it, and `/memorize` writes a scope on demand. See [memory.md](memory.md).

## One stream, one round trip

When no tools are used, a turn is a single streaming request, with no separate non-streaming decision round. `chat_nonstreaming()` is reserved for auxiliary decisions: query refinement, tool-result analysis, compaction. The `<thinking>` marker split lives in the engine so thinking stays separate from content in JSON results and session logs.

## UI sinks

The loop renders through a `UISink`, an interface of methods the loop calls as events happen (`token`, `thinking`, `tool_status`, `activity`, `footer`, `confirm`, `error`, ...):

| Sink | Purpose |
|------|---------|
| `ReplUI` | Terminal REPL: ANSI streaming with a color language (orange actions/asks, red errors, blue thinking headers, dim reasoning and output), optional markdown, `[Y/n]` confirm prompts, footer stats |
| `HeadlessUI` | `run` / `serve`: stderr diagnostics, auto-approve/deny confirm policy, never blocks on stdin |
| `BufferUI` | Writes plain-text event lines into a run's buffer, for per-run logs read back with `/focus log`. No terminal, `confirm` denies and `ask` returns `None` |
| `NullUI` | Silent, for tests |

`ReplUI`'s markdown rendering (code blocks, inline code, bold) is a lightweight token-level state machine in `src/polyglav/ui.py`, gated by the `markdown_streaming` config.

## Front-ends

| Front-end | Entry | Mode |
|-----------|-------|------|
| REPL | `polyglav` | Interactive shell with readline history, tab completion, slash commands |
| CLI | `polyglav run` | One-shot headless chat, JSON or text output, for scripting and CI/CD |
| HTTP | `polyglav serve` | Stdlib `ThreadingHTTPServer` JSON API over the same engine |

Agents talk to each other over the same `POST /chat` API that `polyglav serve` exposes, which is how fleets and swarms compose. See [fleet.md](fleet.md), [swarm.md](swarm.md), [api.md](api.md).

## Sessions

Every turn appends to a session, a complete append-only JSON log of messages, tool calls and results, reasoning, and errors. The provider payload is prepared from the log by `_provider_messages()`. See [session.md](session.md).

## Plugins

Plugins extend the core with tools, providers, commands, and services without changing it. `PluginManager` discovers plugins in the bundled, global, and local roots, validates manifests, and hooks them into the live registries. The core stays stdlib-only, and plugin dependencies are imported lazily. See [plugins.md](plugins.md).

## Source layout

```
src/polyglav/
├── __main__.py          # python -m polyglav
├── chat.py              # ChatLoop(Engine) - REPL shell with readline
├── cli.py               # headless entry points
├── commands/            # command registry + builtins
├── config.py            # JSON config (global + local merge)
├── engine.py            # headless agent core - Engine, TurnResult, chat_tool, run_subagent, run_team
├── eval.py              # tool-use eval harness (polyglav eval)
├── fleet.py             # FleetController - supervised serve agents
├── jobs.py              # Job/JobRun model + registry
├── main.py              # CLI arg parsing + bootstrap (REPL, run, serve, ...)
├── modes.py             # named modes (plan/build/custom) merged into tool policy
├── models.py            # global approved-model registry (models.json)
├── plugins/             # plugin manager
├── providers/
│   ├── __init__.py      # PROVIDERS registry + detect_provider (host patterns)
│   ├── base.py          # BaseProvider + OpenAICompatibleProvider
│   └── registry.py      # ProviderRegistry (providers.json - keys + base URLs)
├── scheduler.py         # JobScheduler - durable job daemon
├── server.py            # stdlib HTTP JSON API
├── sessions/            # session CRUD + markdown render
├── skills.py            # SkillRegistry (per-role instructions)
├── teams.py             # TeamRegistry (named team pipelines) + team memory helpers
├── tools/               # tool registry, tool policy, delegate, ask
├── roles.py             # RoleRegistry (roles, plugin/global/local)
├── ui.py                # UISink - ReplUI / HeadlessUI / BufferUI / NullUI
└── utils/               # urllib-based SSE streaming
```

## Extension points

- **Adding a tool** - see [tools.md](tools.md)
- **Adding a provider** - see [providers.md](providers.md)
- **Adding a command** - registered via `@registry.register()`. A command performing a tool action calls the tool registry rather than reimplementing it
- **Adding a plugin** - see [plugins.md](plugins.md)
