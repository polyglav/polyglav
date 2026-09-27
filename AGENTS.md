# Polyglav - Agent Guide

## Project

A terminal-based **agentic REPL core**. The model is the planner. The tool registry is how it acts. It is a zero-dependency Python app (`stdlib only`) built around a **single agent loop**: one SSE stream per turn where the model either emits content or requests tool calls, which the loop executes and feeds back until the model answers.

Multi-provider chat, web search, sessions, slash commands, machine access, roles and delegation, and plugins are all capabilities on top of that core.

## Tech Stack

- Python >=3.10, **stdlib only** (no external dependencies)
- `readline` - input history + tab completion for slash commands
- `urllib.request` - HTTP + SSE streaming
- `urllib.error` - HTTP error handling
- `json` / `pathlib` / `os` - config and session storage

## Architecture: Agentic Core

The agentic core has three layers:

1. **Agent loop** (`engine.py`) - the headless core. Each turn runs a single streaming request. The provider's `chat()` is a generator yielding events, and the engine reacts:
   - `thinking` / `token` - streamed to the sink (`UISink`), `ReplUI` renders ANSI thinking + optional markdown, `HeadlessUI` logs to stderr / buffers for JSON
   - `tool_calls` - append the assistant message, execute each call, append `tool` results, then continue the loop
   - `error` - record + print and bail
   - `done` - persist the assistant message (timestamp/duration/model) and stop

   One stream, one round trip when no tools are used. `chat_nonstreaming()` is reserved for query refinement, not the main path. The loop is front-end agnostic: `ChatLoop` (REPL), `polyglav run` (CLI), and `polyglav serve` (HTTP) all call `Engine.chat(text) -> TurnResult`. The `<thinking>` marker split lives in the engine so thinking stays separate from content.

2. **ToolRegistry** (`tools/registry.py`) - the **single dispatch point**. The model invokes tools via OpenAI function calling, slash commands are thin wrappers that call the same `execute()`. The loop never special-cases tool names - per-tool behavior comes from registration metadata (`refine`, `permission_fn`, `note`, later `confirm`). The `delegate` tool (`tools/delegate.py`) is a core tool that runs a task under a role by spawning an in-process sub-`Engine` (`Engine.run_subagent`) - the same agent loop, its own `sub_<ts>_<id>` session, a quiet `NullUI`. Its permission is a per-invocation `permission_fn` resolved per role. The `team` tool (`tools/team.py`) runs a named team pipeline (`Engine.run_team`) with the same per-stage permission resolution plus cycle and `max_team_depth` guards.

3. **Commands** (`commands/`) - user-facing affordances. A command either wraps a tool or performs a local action (`/model`, `/session`, `/sessions`).

Providers (`providers/`) keep the base classes and registry in the core (`BaseProvider`, `OpenAICompatibleProvider`, the `PROVIDERS` dict, host-pattern `detect_provider`). The vendor providers ship as bundled plugins that register through the `register_providers` hook. A fuller treatment of the core, UI sinks, and front-ends is in `docs/architecture.md`.

### Project Structure

```
Polyglav/
├── pyproject.toml
├── AGENTS.md
├── README.md
├── TODO.md
├── CHANGELOG.md
├── tests/
│   └── test_tool_calling.py   # Mock tests (no network/API key needed)
├── src/polyglav/
│   ├── __init__.py
│   ├── __main__.py          # python -m polyglav
│   ├── main.py              # CLI arg parsing + bootstrap (default REPL, run, serve)
│   ├── cli.py               # `polyglav run` / `polyglav serve` / `polyglav eval` headless entry points
│   ├── config.py            # JSON config (global + local merge)
│   ├── models.py            # global model registry - models.json (connections + keys)
│   ├── roles.py             # RoleRegistry - bundled/global/local roles.json merge + tags
│   ├── bundled_roles.json  # bundled default roles (9, leader + two pre-carved teams)
│   ├── engine.py            # Headless agent core - Engine + TurnResult + run_subagent
│   ├── chat.py              # ChatLoop(Engine) - REPL shell with readline
│   ├── jobs.py              # Scheduled jobs - Job/JobRun model, registry, cron parser
│   ├── memory.py            # Bounded role/team/job memory under .polyglav/memory/
│   ├── scheduler.py         # JobScheduler - durable job daemon (retries, approvals, auto-compact)
│   ├── fleet.py             # Fleet supervisor - AgentDef manifest, FleetController (ports, health, restart)
│   ├── ui.py                # UISink - ReplUI / HeadlessUI / BufferUI / NullUI renderers
│   ├── eval.py              # Tool-use eval harness - fixtures, runner, metrics (polyglav eval)
│   ├── server.py            # stdlib HTTP JSON API (POST /chat, GET /sessions, GET /health, GET /version)
│   ├── providers/
│   │   ├── __init__.py      # PROVIDERS registry + detect_provider (host-pattern) + merged_providers
│   │   ├── base.py          # BaseProvider + OpenAICompatibleProvider (HOST_PATTERNS)
│   │   └── registry.py      # ProviderRegistry - providers.json (keys + custom base URLs)
│   ├── sessions/
│   │   ├── __init__.py
│   │   ├── manager.py       # Session CRUD (turn/part JSON files)
│   │   ├── render.py        # Session -> Markdown transcript
│   │   └── turns.py         # Turn/part model + provider-context reconstruction
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── registry.py      # Command registration + dispatch
│   │   └── builtins.py      # /help, /connect, /model, /session, /sessions, /plugins, etc.
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py      # Tool registration + dispatch (OpenAI function calling)
│   │   ├── policy.py        # ToolPolicy - allow/ask/deny permissions + path scoping
│   │   ├── delegate.py      # Core delegate tool - role sub-agents via per-invocation policy
│   │   ├── team.py          # Core team tool - run a named team pipeline, ceiling + depth guards
│   │   └── ask.py           # Core ask tool - human/lead mid-run questions
│   ├── plugins/
│   │   ├── __init__.py
│   │   └── manager.py       # PluginManager - discovery, manifest/compat, install/update/uninstall
│   └── utils/
│       ├── __init__.py
│       └── http.py          # urllib-based SSE streaming
└── plugins/                 # bundled plugins (shipped as polyglav.plugins.bundled), each is {src/, tests/}
├── polyglav-core-edit/        # file_edit
    ├── polyglav-core-anthropic/   # AnthropicProvider
    ├── polyglav-core-dev/         # code_test, code_lint, code_format
    ├── polyglav-core-eval/        # eval fixture catalog for polyglav eval
    ├── polyglav-core-exec/        # run_command
    ├── polyglav-core-fs/          # file_read, list_dir, file_write, glob, grep
    ├── polyglav-core-git/         # git, git_commit
    ├── polyglav-core-groq/        # GroqProvider
    ├── polyglav-core-ollama/      # OllamaProvider
    ├── polyglav-core-openai/      # OpenAIProvider
    ├── polyglav-core-opencode/    # OpenCodeProvider + OpenCodeGoProvider (session-id base)
    ├── polyglav-core-web/         # web_search, web_fetch + search service
    └── polyglav-core-webhook/     # report-back connector (job run reports)
```

## Conventions

### Code Style
- No external dependencies, stdlib only. Plugins may opt into third-party deps via their manifest, but the core never depends on them
- No comments in code
- Type hints required for all function signatures
- Use `from __future__ import annotations` if needed for `|` syntax
- Prefer `pathlib.Path` over `os.path`
- ANSI escape codes for terminal coloring (no `rich`/`colorama`)
- `\001` / `\002` readline markers around ANSI codes in prompts

### Architecture Rules
- One agent loop, one SSE stream per turn, with no separate non-streaming decision round
- `ToolRegistry` is the single dispatch point: commands call tools, they never reimplement them
- No tool-name special-casing in the loop. Use registration metadata instead
- `BaseProvider.chat()` is a generator yielding events: `thinking`, `token`, `tool_calls`, `error`, `done`
- `BaseProvider` uses OpenAI-compatible `/v1/chat/completions` format
- Config: global (`~/.config/polyglav/config.json`) > local (`.polyglav/config.json`) merge, local wins
- Sessions stored as `.polyglav/sessions/<name>.json`
- Slash commands registered via `@registry.register()` decorator
- Tools registered via `@tool_registry.register()` decorator (OpenAI function calling format)

### Doc Conventions
- Four planning files with distinct roles, kept in sync with actual project state:
  - `VISION.md` - the **why**: vision, decisions, and architecture (stable, changes rarely and deliberately). The assistant track is planned there, including its context economics and out-of-scope list.
  - `PLAN.md` - the **what**: the structured mapping of open TODO tasks into work packages. Each package is a table (`Task | Effort | Provides`, effort S < M < L), packages ordered top-to-bottom by urgency and importance, re-ranked against the backlog before each next step. **Finished tasks are removed from `PLAN.md`** and live as one-liners in `TODO.md` `## Done` and in detail in `CHANGELOG.md`.
  - `TODO.md` - the **backlog**: ideas at the very top (plain bullets, no header, no checkbox, since they evolve over time), `## Open` (defined `[ ]` tasks), `## Done` (`[x]` items, separated by `---`). Within `## Open` and `## Done`, items are sorted newest-first so new tasks are added at the top of their zone without reorganizing, nested sub-bullets are preserved (e.g. machine tools, tool policy). Completed items stay in `## Done` and are never moved to an archive. `## Done` entries are short one-liners, and detailed change descriptions live in `CHANGELOG.md` under the matching version. As a soft rule, keep each `## Done` entry to a single line of at most 100 characters (shorter is better, so trim detail rather than wrap or exceed).
  - `CHANGELOG.md` - the **history**: grouped by versions, newest at the top, so new `## vX.Y.Z - YYYY-MM-DD` sections go above previous ones and the latest changes are readable with `head`. Entries under each version form a **single flat bullet list, newest first** (no `### Added`/`### Changed`/`### Removed` grouping).
- After completing a planned task: mark it `[x]` in `TODO.md` (it stays as a one-liner in `## Done`), add entries under the current version section at the top of `CHANGELOG.md` (start a new version section first if none exists), and remove the task from `PLAN.md` so the execution plan only ever lists open work.
- Do not mention work-package labels (e.g. `WP0`) or test-case counts (e.g. `(28 cases)`) in planning docs or `CHANGELOG.md`. Describe the task or change itself. `PLAN.md` packages are identified by capability, not numbers, and test coverage lives in the suite and `docs/testing.md`.
- Documentation-only changes (adding/rewriting docs, planning-file restructures) get no `CHANGELOG.md` entry, since they are visible in git history. `CHANGELOG.md` records code and behavior changes. Docs delivered as part of a code feature are mentioned inside that feature's entry.
- Keep the four files in sync with actual project state.
- Keep `version` in `pyproject.toml` in sync with the current version in `CHANGELOG.md`, and bump it whenever a release section is started or finalized.
- Use only ASCII punctuation and glyphs in docs. Avoid typographic Unicode characters: em-dashes (`—`), en-dashes (`–`), smart/curly quotes (`‘ ’ “ ”`), the single-character ellipsis (`…`), non-breaking spaces, and similar substitutes. Use plain hyphens (`-`) or ASCII three dots (`...`) instead. Inline code and quoted strings may keep non-ASCII only when they reproduce literal runtime output (e.g. the `…` truncation marker).
- Split clauses with periods or commas rather than semicolons (`;`).
- Do not break a sentence with a dash-set-aside clause (for example `layers - swarm, jobs - with MCP`). Let the sentence flow as one statement, using commas, parentheses, or a separate sentence instead. Reserve the hyphen for compound words, list markers, bullet-list convention, and version separators. The dash-aside construction reads as machine-generated.
- Sort enumerated lists alphanumerically: file trees, command and subcommand tables, tool/provider/role rosters, doc indexes, config key tables, and test coverage maps. New entries slot into their sorted position, never appended.

### Commits
- One line only: no body, no trailers, no conventional-commit prefixes (`feat:`, `fix:`, `chore:`), no scope, no emoji, no issue numbers.
- Start with a capital letter and a past-tense verb: `Added`, `Changed`, `Fixed`, `Removed`, `Renamed`, `Updated`, `Moved`.
- Mirror the matching `TODO.md` `## Done` one-liner and trim it to a single line, so the log and the backlog read the same.
- No trailing period, and ASCII punctuation only, per `### Doc Conventions`.
- Commit each finished step as part of the work, without waiting for a per-commit request.
- Never push. `git push` is never run, and commits stay local.

## Extension Points

### Adding a Tool
1. Use the `@registry.register(name, description, parameters)` decorator in the plugin/module where the tool belongs
2. `parameters` follow the OpenAI function calling JSON schema format. The handler receives keyword arguments matching the schema and returns a string (the tool result injected into the conversation)
3. Add optional metadata for loop behavior and permissions: `refine`, `category`, `permission`, `path_arg`, `key_arg`, `glyph`/`verb`, `status`, `echo`, `permission_fn`, `aliases`, `param_aliases`, `note`, `loop`, with the full reference in `docs/tools.md`. `loop=True` makes `/tool <name>` run a persisted agent-loop turn (`Engine.chat_tool`) instead of a one-shot direct call. It is used by `delegate` so the plan/result/answer land in the session
4. `ToolRegistry.execute()` passes only args declared in the tool's schema. Undeclared and `null`-valued args (e.g. a hallucinated `recursive`, or `depth: null`) are dropped, never forwarded to the handler
5. `aliases` (extra tool names resolving to this tool, e.g. `read`/`view` for `file_read`, `open`/`fetch_page` for `web_fetch`) and `param_aliases` (caller-side param synonyms mapped onto declared params, e.g. `{'cursor': 'offset'}`) let the registry absorb model-dialect tool and argument names without advertising them in the schema. `/tool`, `/help`, policy, confirm, and glyphs work through aliases unchanged

### Machine Access & Permissions
- `ToolPolicy` (`tools/policy.py`) is the single permission resolution point. The loop and `/tool` both route through it, so never special-case tool names for permission logic
- Actions: `allow` (no prompt), `ask` (y/N confirm in the loop via `_confirm_tool`), `deny` (tool filtered from the provider schema and refused on direct calls)
- Precedence: a name-level `deny`, the `tools.allow` allowlist, and a category `deny` win outright and skip the resolver. Otherwise the category action from `tool_permission` applies (default `ask`), and the per-invocation resolver (`permission_fn`, resolved from the tool's current arguments, e.g. `delegate` per role or `git_commit` except for `all=true`) may override a non-`deny` category action or return `None` to keep it. Worktree escalation turns an `allow` into `ask` for read/write/list outside the worktree
- The worktree is the directory holding the local `.polyglav/`, i.e. the launch directory, or `--path`. Launching from `~` makes the whole home directory the worktree, so subdirectories (including other projects) do **not** escalate. Launch inside the project or pass `--path` for project-scoped prompting
- `bash: ask` by default, so every `run_command` confirms. Set `tool_permission.bash = "allow"` to disable prompting. `delegate` defaults to `allow` (runs without a prompt), refined per role: a configured role uses its own `tool_permission` (set `delegate: "ask"` on a role to confirm), a role outside the registry is denied. `git_commit` is gated by `vcs` (default `ask`): a role whose carve sets `vcs: allow` commits without a prompt while every other role confirms, and `all=true` always asks
- Delegation (`run_subagent`) builds an in-process sub-`Engine` with the role's prompt, model override, and merged `tool_permission`, forces mode `build`, shares the caller's provider/plugin manager/worktree, and runs with `NullUI`, where ask-gated tools auto-deny, so a sub-agent's effective permissions are exactly its carve. Sub-agent results echo via `delegate_echo` (default on). Each sub-agent persists its own `sub_<ts>_<id>` session. The `ask` tool (core) is the explicit human-in-the-loop channel: `target='human'` routes to the operator at the terminal (via the root `ReplUI`, inherited by sub-engines as `_ask_ui`), `target='lead'` routes to the delegating engine's model (bounded `chat_nonstreaming` consultation via the sub-engine's `_lead` reference), and headless roots with neither return an error result without blocking
- Confirm prompts and tool status are ephemeral REPL UI, never persisted to session files. The permission decision itself (granted / declined / denied) is recorded in the session `permissions` audit array
- Full policy flow and registration metadata in `docs/tools.md`. Threat model in `docs/security.md`
- Sandboxed exec (namespace/container isolation) is planned future work (see TODO). Per-agent permission profiles landed with roles (`tool_permission` on each role)

### Adding a Provider
1. Subclass `OpenAICompatibleProvider` (core, in `src/polyglav/providers/base.py`) and set `DEFAULT_BASE_URL` / `DEFAULT_MODEL` (override `_headers()`/`_payload()` only for non-standard auth or bodies)
2. Declare `HOST_PATTERNS` (URL substrings that identify the provider) so `/connect <url>` auto-detects it (longest pattern wins for shared hosts, e.g. `opencode.ai/zen` vs `opencode.ai/zen/go`)
3. Register it via a plugin's `register_providers(providers)` hook (`providers[name] = ProviderClass`) and list the name in the manifest's `provides.providers`. Vendor providers ship as bundled plugins in `plugins/`. The core `PROVIDERS` registry stays `openai-compatible` only and wins on name conflicts with plugin registrations

The chat() event contract and full provider reference are in `docs/providers.md`.

### Adding a Slash Command
1. Open `commands/builtins.py`
2. Use `@registry.register('name', aliases=['a1', 'a2'])` decorator
3. Handler receives one string argument (the text after the command name)
4. If the command performs a tool action, call `chat_loop._tool_registry.execute(name, args)` rather than reimplementing it

### Adding a Plugin
Plugins are external repositories, so never modify the core to add optional functionality:
1. Create a plugin directory with a `manifest.json` (`name`, `version`, `polyglav_version` semver range, `python` range, `entry` default `plugin.py` (may point into `src/`), `requires` third-party deps, `provides`), an entry module under `src/`, and an optional `tests/` unit suite (stdlib `unittest`, found by `polyglav plugins test` and the core suite)
2. The entry module may define `register_tools(registry)`, `register_providers(providers: dict)`, `register_commands(commands)`, `register_services(services)`, `register_roles`/`register_teams`/`register_skills`, and `register_fixtures(fixtures)` (eval fixture catalog, see `docs/eval.md`), using the same decorators as core builtins
3. Import third-party deps lazily **inside** tool functions, the core never imports them
4. Install via `/plugins install <git-url|path>` or `polyglav plugins install`. Activation is the `plugins` config list (empty = all), and `install`/`uninstall`/`enable`/`disable` maintain it automatically
5. See `docs/plugins.md` for the full manifest schema, compatibility contract, and management commands
6. Bundled plugins live in the repo `plugins/` dir (shipped as `polyglav.plugins.bundled`), so add a new bundled plugin there + to the `plugins` config default, never to the core

### Future: Plugin sources
Plugins currently install from git URLs or local paths into the plugin roots. Shared/per-plugin virtualenv dependency isolation and a PyPI entry-point source are planned future work (see TODO).

## Config Schema

Full schema and defaults are in `docs/config.md`. Notable edge cases:

- `max_tokens` defaults to `8192`, the cap sent to the provider, which overrides low provider-side defaults (e.g. Ollama's 2048). Set it to `0` to omit it from the provider payload, so the provider's own default applies. Hitting the limit prints a warning (distinguishing a configured cap from the provider's default) and logs a session `errors` entry.
- `unattended: true` (or `polyglav --unattended` / `/unattended`) guarantees no stdin is read at any depth: confirms auto-deny, and `ask target='human'` parks as a pending request in `.polyglav/asks.json` (returned as `[parked] Ask #<id>`, answered via `/asks` or the serve API. The answer injects into the origin session). `confirm_timeout` (seconds, default `0` = forever) makes attended confirm/ask prompts self-deny after a timeout instead of hanging.
- `report.webhook` (default `""`) is the URL the bundled `polyglav-core-webhook` connector POSTs a completed job run to (the scheduler dispatches one `job.run.completed` event per run to the registered `report` service). Empty disables out-of-band reporting.
- `plugins` lists the plugins to load, and the bundled plugins are in the default. An empty list loads all discovered plugins. `plugins.enabled`/`plugins.deny` from earlier versions are migrated automatically.

## Testing

Run tests before committing changes to verify core logic isn't broken. The suite is stdlib `unittest` with mock providers (no network, no API key). The canonical setup installs the package (`pip install -e .`). On a source checkout without installing, point `PYTHONPATH` at the absolute `src` path, since a bare `python -m unittest` raises `ModuleNotFoundError: No module named 'polyglav'`:

```bash
PYTHONPATH=$PWD/src python -m unittest discover tests
```

Single-file runs use the same prefix (`PYTHONPATH=$PWD/src python -m unittest tests.test_turns`). The per-file coverage map is in `docs/testing.md`.

Test incrementally. Before each commit run only the tests for the code just changed, as a single file or single class. After the last commit of a series, run the full suite (`discover tests`) and fix anything it finds.

## Sessions

Sessions are complete, append-only logs: every turn (the operator prompt, thinking, each tool call with its result, and the answer) and every error is persisted, and entries are **never removed** (compaction only trims the provider context). The full schema (file location, turn and part fields, `errors`, serialization-time transforms (`noise_tools`, `session_tool_max_chars`), provider-context preparation, and compaction) is in `docs/session.md`. Files written before the turn format (flat `messages`) and before the `session_name`/`session_id` rename are left untouched and no longer load.
