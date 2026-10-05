# Tools

Tools are how the model acts. The `ToolRegistry` (`src/polyglav/tools/registry.py`) is the single dispatch point: the model invokes tools via OpenAI-compatible function calling, slash commands are thin wrappers over the same `execute()`, and the loop never special-cases tool names, because per-tool behavior comes from registration metadata.

This page is the reference: what the registry supports, the bundled tools, and the policy that gates them. Tool definitions follow the OpenAI function calling JSON schema format. The model sees the schema (filtered by policy), requests a tool call, and the loop executes it and feeds the result back. For how to design, name, and describe a new tool so agents use it well, see [writing-tools.md](writing-tools.md).

## Bundled tools

The built-in web and machine tools ship as bundled plugins, loaded out of the box:

| Tool | Plugin | Category | Permission | Purpose |
|------|--------|----------|------------|---------|
| `ask` | core | `ask` | `ask` | Ask the user or the caller agent for a decision, pausing until answered |
| `call` | core | `call` | `call` | Run a task under a named role as a sub-agent |
| `catalog` | core | `catalog` | `catalog` | Manage roles, teams, and skills: list/show/save/remove, plus reload |
| `code_format` | polyglav-core-dev | `exec` | `bash` | Run the project formatter (`dev.format_cmd`, default `ruff format .`) |
| `code_lint` | polyglav-core-dev | `exec` | `bash` | Run the project linter (`dev.lint_cmd`, default `ruff check .`) |
| `code_test` | polyglav-core-dev | `exec` | `bash` | Run the project test suite (`dev.test_cmd`, default `python -m unittest discover`, resolved to the current interpreter) |
| `delegate` | core | `delegate` | `delegate` | Run a named team (an ordered chain of role stages) and return the final stage's answer |
| `file_edit` | polyglav-core-edit | `write` | `edit` | Targeted search-and-replace in a file with a diff preview (`count` occurrences, `0` = all, alias `edit`) |
| `file_read` | polyglav-core-fs | `read` | `read` | Read a file with numbered lines (aliases `read_file`, `read`, `view`) |
| `file_write` | polyglav-core-fs | `write` | `edit` | Create/overwrite/append a file (aliases `write_file`, `write`) |
| `git` | polyglav-core-git | `read` | `read` | Read-only git: status/diff/log/branch/show/rev_parse (aliases `git_status`, `git_diff`, `git_log`, ...) |
| `git_commit` | polyglav-core-git | `write` | `vcs` | Stage/commit git changes, confirm-gated unless the `vcs` carve is `allow` (`all=true` always asks). Alias `commit` |
| `glob` | polyglav-core-fs | `search` | `read` | Recursive pattern lookup |
| `grep` | polyglav-core-fs | `search` | `read` | Regex content search (`file:line:` results, alias `find`) |
| `handoff` | core | `handoff` | `handoff` | Pause or finish this run and hand control to a parent/sibling/child/root/run id |
| `list_dir` | polyglav-core-fs | `read` | `list` | List a directory (`depth` for trees, alias `ls`) |
| `offload` | core | `offload` | `offload` | Hand a self-contained sub-task to an anonymous read-only sibling |
| `run_command` | polyglav-core-exec | `exec` | `bash` | Run a shell command with timeout (aliases `bash`, `exec`). Restricted by `tool_permission.bash_allow` |
| `web_fetch` | polyglav-core-web | `read` | `read` | Fetch a page by URL or by `web_search` result `id` (aliases `open`, `fetch_page`) |
| `web_search` | polyglav-core-web | `search` | `web` | Web search (aliases `search`, `web`) |

Plugins register additional tools the same way and automatically inherit tool policy, `/tool`, `/help`, query refinement, `noise_tools`, and session logging. See [plugins.md](plugins.md).

## Asking the user or the caller

The `ask` tool (core, like `call`) pauses the run and routes a decision or permission request to an answerer, so a sub-agent or team stage gets a decision mid-run instead of returning open questions at the end. Schema: `question` (required), `context`, `options` (suggested answers), `target`, `kind` (`permission`/`direction`, default `direction`), and `permission` (the tool or category for a permission request):

- `target='user'` - the user answers at the terminal. The root loop prompts directly. A sub-agent's ask is prefixed with its `sub_<...>` session name so the user knows who is asking (delegation and team stages run synchronously in-process, so the terminal is free while a sub-agent runs). The answer feeds back into the asking agent's context and the run continues. When `target` is omitted, `ask_policy` decides the route. A delegated run defaults to its caller, so a running team stays automated and only reaches you when a role sets `ask_policy.direction='user'` or the ask passes `target='user'`. The root falls back to the terminal user when there is no caller to consult.
- `target='caller'` - the role or engine that delegated this run decides. The caller answers through a lightweight non-streaming consultation (a bounded prompt with the question, context, options, and the sub-agent's delegated task), not a full parent turn. A root engine has no caller, so `target='caller'` falls back to `user`, and `user` falls back to `caller` when no terminal is reachable.
- `kind='permission'` - a request for a tool or category the sub-agent is not allowed to use. Naming a category (`edit`, `bash`, `read`) grants the whole category, so every tool in it is covered, while naming a specific tool (`file_write`) grants only that tool. Routing follows `ask_policy.permission` (`auto` = the caller decides and grants one use, `user` = the user, `deny` = disabled), capped by the caller's `grant_permission` ceiling. An approval creates a one-shot grant on the asking sub-agent, consumed by the next matching call. The user may answer `always` to make it reusable for the rest of that sub-agent's run. The caller only ever grants `once`. See [config.md](config.md#permission-authority).
- A `kind='direction'` ask must be self-contained. A question shorter than `ask_min_question_chars` with no `context` and no `options` is rejected with an error, so a placeholder such as `probe` cannot reach a person. `0` disables the guard.
- Options render inline after the question when the line fits `ask_options_inline_chars` (for example `which?  (a) a  (b) b`), otherwise the question prints first and each option follows on its own line as `1) opt`. The answer accepts a number, a letter (`a`, `b`), or the option text, and any other input is a free-text answer. Only `? Answer: ` is the input prompt, so the question and options stay in the transcript.
- When no one can answer (headless `run`/`serve`/jobs: no terminal and no caller at the root), `ask` returns an `Error: ask has no one to answer ...` result and the run continues autonomously. It never blocks on stdin outside the REPL. The asynchronous "pause a job and wait for a user reply over a connector" variant is tracked separately (see [jobs.md](jobs.md)).

The ask is not additionally gated: `tool_permission.ask` defaults to `allow`, since the question and answer are the point. Users can block it with `tools.deny: ["ask"]`. The question (tool arguments) and answer (tool result) persist in the asking session's log, and the call is recorded in the session `permissions` audit array like any tool call. A permission grant adds `scope` and `granted_by` fields to that audit entry.

## Handing off control

The `handoff` tool (core) pauses or finishes the current run and hands control to another run, with the user's focus following the target. Schema: `target` (required) and `done` (default false). Targets resolve against the run registry: `parent`, `child`, `sibling`, `root`, a run id (`3` or `#3`), a session id (`#ab12cd`), or a session name. The tool marks the current run `done` (when `done=true`) or `paused`, then records a pending handoff on the focus root. The turn ends immediately, because the loop does not stream another round after the tool batch, and `ChatLoop` applies the pending handoff once the turn returns, focusing the target run (a root-run target resets to the assistant). It is REPL-only: a delegated sub-agent has no focus manager and gets an `Error: handoff is only available in the REPL focus session ...` result. Gated by `tool_permission.handoff` (default `allow`).

## The tool loop

1. The provider's `chat()` stream yields a `tool_calls` event with the requested function calls.
2. The loop appends an `assistant` message with the `tool_calls` and `thinking`.
3. Each call is checked against the tool policy, then executed through `ToolRegistry.execute()`.
4. Each result is appended as a `tool` message (with `tool_call_id` and the tool name), plus a one-line `analysis` when `tool_analysis` is enabled.
5. The loop continues with the enriched context until the model answers.

Ctrl-C in the REPL cancels the running turn: streaming and any in-flight tool execution are aborted, partial output is persisted, a `(cancelled)` note prints, and the prompt returns. At a Y/n confirm prompt it cancels the whole turn too (`n` still declines just that tool). Headless behavior mirrors this, and `polyglav run` exits non-zero on a cancelled turn.

## Running a tool directly

`/tool <name> {"key": "value"}` runs any registered tool from the REPL, routed through the same policy. `/help <tool>` shows a tool's description, parameters, category, and permission.

## Registration metadata

Tools are registered with `@registry.register(name, description, parameters)` plus optional metadata that shapes loop behavior:

| Key | Description |
|-----|-------------|
| `refine` | Auto-refine short `query` args via a lightweight model call, gated by `query_refine` |
| `category` | `ask` / `call` / `catalog` / `delegate` / `exec` / `handoff` / `mcp` / `offload` / `read` / `search` / `todo` / `write` - drives the default activity glyph and verb |
| `permission` | The `tool_permission` key that gates the tool: `bash` / `call` / `catalog` / `delegate` / `edit` / `handoff` / `list` / `mcp` / `offload` / `read` / `vcs` / `web` |
| `permission_fn` | Optional `Callable[[dict], str]` resolving the action (`allow`/`ask`/`deny`) from the current arguments - refines a non-`deny` base action at call time, or returns `None` to defer to the category action (see `call`, `git_commit`) |
| `write_actions` | Optional list of argument-level actions that count as write-class even under a read-class `permission` key (for example the `catalog` tool's `save`/`remove`/`reload`), so a read-mode permission ask is redirected to a mode switch |
| `path_arg` | Which parameter is a filesystem path, for worktree scope checks |
| `key_arg` | Which argument appears in status/confirm labels and glyph activity lines |
| `glyph` / `verb` | Per-tool activity-line overrides (e.g. `glob` uses `* Glob`, `web_fetch` uses `↓ Fetch`) |
| `status` | A `Callable[[dict], str]` receiving the cleaned args, returning a block whose first line becomes the `[tool: <value>]` oneliner and the rest render as dimmed detail lines (used by `file_write` to preview/diff the written text) |
| `echo` | When true, the tool result is printed dimmed below the status oneliner (used by `run_command`) |
| `short` | Short label for `/help` listing (defaults to the description truncated) |
| `aliases` | Extra tool names resolving to this tool (e.g. `read`/`view` for `file_read`, `open`/`fetch_page` for `web_fetch`) - absorbed at call time, never advertised |
| `param_aliases` | Caller-side parameter synonyms mapped onto declared parameters (e.g. `cursor` -> `offset`, `query` -> `pattern`) |
| `loop` | When true, `/tool <name>` runs the tool as a real agent-loop turn (`Engine.chat_tool`) - the tool call and result persist, then the model streams its final answer. Used by `call` so a `/tool call` plan, results, and answer land in the session and a later prompt can continue the work. Direct `ToolRegistry.execute()` calls are unaffected |
| `confirm` | When false, the tool is never Y/n confirm-gated even when its category action is `ask`, so the call proceeds and the permission audit records it as granted. Used by `ask` so a question is never blocked by the prompt it needs |
| `error` | A `Callable[[str], bool]` predicate over the raw result. When true, the echoed result renders red instead of dim, so a failed command is visible. Used by `run_command` and the dev wrappers, which read the `exit N` line |

`ToolRegistry.execute()` passes only arguments declared in the tool's schema. Undeclared and `null`-valued arguments (e.g. a hallucinated `recursive`, or `depth: null`) are dropped. It also passes the engine `Config` to handlers that declare a `_config` keyword argument (e.g. `def file_read(path, offset=1, limit=500, _config=None)`), so a tool can read config keys like `tool_max_result_chars` without exposing them to the model.

Models often guess tool and argument names instead of reading the schema (`search` for `web_search`, `find` for `grep`, `cursor` for `offset`). `aliases` (extra tool names resolving to a tool, e.g. `search`/`find`) and `param_aliases` (caller-side parameter synonyms, e.g. `cursor -> offset`, `query -> pattern`) let the registry absorb that dialect without advertising it in the schema. An unregistered tool call returns `Error: unknown tool "<name>. Available tools: <...>"`, and the loop lists the registered tools so the model can pick a real one. `open` also tolerates a URL string in its `id` argument by treating it as the URL.

## Adding a tool

1. Open the plugin or module where the tool belongs.
2. Use the `@registry.register(name, description, parameters)` decorator.
3. `parameters` follow the OpenAI function calling JSON schema format.
4. The handler receives keyword arguments matching the schema.
5. Return a string - the tool result injected into the conversation.
6. Add the optional metadata above for loop behavior, permissions, and display.

Example:

```python
@registry.register(
    name='pdf2text',
    description='Extract text from a PDF',
    parameters={'type': 'object',
                'properties': {'path': {'type': 'string'}},
                'required': ['path']},
    permission='read',
    path_arg='path',
    key_arg='path',
)
def pdf2text(path):
    return extract(path)
```

## Result size and large files

Tool results are sent to the model verbatim, up to the `tool_max_result_chars` cap (default `100000`, `0` = unlimited). A result over the cap is cut at a line boundary with a trailing `... (truncated)` marker. `list_dir` also caps returned entries (`list_dir_max_entries`, default `200`) with a `... (showing first N of M entries)` marker, so a large tree stays bounded regardless of name lengths.

`file_read` helps the model page through large files without hitting a cap:

- Every result header reports the total size: `# <path> - <N> lines, <M> chars` (plus `(showing a-b)` for partial windows), so the model learns a file's size from the first read.
- `limit=0` returns just the header as a size probe, so the model can check size before committing to a read.
- A large file is read in windows via `offset` / `limit` arguments (`file_read(path, offset=1, limit=200)`, then `offset=201`, ...).

## Tool policy

Every tool call is gated by `ToolPolicy` (`src/polyglav/tools/policy.py`), the single permission resolution point. The loop and `/tool` both route through it, so never special-case tool names for permission logic.

Actions are `allow` (no prompt), `ask` (Y/n confirm in the loop), or `deny` (tool filtered from the provider schema and refused on direct calls).

Every resolution and its outcome (granted / declined / denied) is recorded to the session `permissions` array as an append-only audit trail. See [session.md](session.md).

Resolution precedence:

1. **Name-level** - `tools.deny` (always denied) and `tools.allow` (when non-empty, it is an allowlist, so everything else is denied).
2. **Category action** - the `tool_permission.<key>` action for the tool's `permission` key. `deny` here is final, skips the resolver, and filters the tool from the provider schema and from tool listings, not just direct calls.
3. **Per-invocation resolver** - a tool may declare a `permission_fn` that overrides a non-`deny` base action from its current arguments, and returning `None` defers to the category action. It is skipped when the base action is `deny` and when no arguments are available, so schema filtering (`allowed()`) keeps the tool visible for `ask`/`allow` categories. `call` resolves per role: a configured role uses its own `tool_permission` with `call` defaulting to `allow`, a role outside the registry is `deny`. `git_commit` defers to the `vcs` category except for `all=true`, which asks.
4. **Worktree escalation** - `read` / `list` / `write` tools pointing outside the project worktree escalate from `allow` to `ask`.

The mode ([modes.md](modes.md)) is the outermost bound, applied last, after grants and per-invocation resolvers. `read` (default) denies every permission key not listed in config `access.read_tools`, so write, exec, commit, MCP, and delegation tools are filtered from the schema and refused on direct calls. `write` leaves write keys to `tool_permission`, still bounded by each key's action. A mode may also set `system_prompt`/`color` and append `tools.deny` or replace `tools.allow` in its spec. An unknown `mode` falls back to `read`. Switch with `/mode <name>` in the REPL or `--mode <name>` on `polyglav run` / `polyglav serve`.

### Worktree

The worktree is the directory holding the local `.polyglav/`, which is the launch directory, or `--path`. Launching from `~` makes the whole home directory the worktree, so subdirectories (including other projects) do not escalate. Launch inside the project or pass `--path` for project-scoped prompting. `bash` defaults to `ask`, so every `run_command` confirms unless `tool_permission.bash = "allow"`.

In headless mode (`run` / `serve`), `ask`-gated tools are denied outright (`--yes` / `--no` override), so an agent's reachable surface is exactly its `allow` tools on paths inside its worktree.

## Configuration

Tool behavior is controlled by config keys (see [config.md](config.md) for the full schema and defaults):

| Key | Default | Controls |
|-----|---------|----------|
| `tool_calling` | `true` | Enable OpenAI-compatible function calling |
| `tools.allow` | `[]` | Name-level allowlist. When non-empty, only these tools are callable |
| `tools.deny` | `[]` | Name-level deny list (takes precedence over allow) |
| `tool_permission` | *(see config.md)* | Category actions - `read`/`list`/`edit`/`bash`/`web`/`mcp` -> `allow`/`ask`/`deny` |
| `tool_permission.bash_allow` | `[]` | `run_command` allowlist - every chained segment must start with an allowed prefix, heredocs/multi-line rejected (see [config.md](config.md)) |
| `project_instructions` | `"AGENTS.md"` | Per-worktree instructions file auto-loaded into the system prompt, `""` disables |
| `tool_status_visible` | `true` | Show dimmed tool status in the REPL |
| `glyph_lines` | `true` | Typed activity lines for mapped categories, else the `[tool: arg]` oneliner |
| `tool_analysis` | `false` | Model-generated one-line analysis of each tool result (log-only) |
| `tool_max_result_chars` | `100000` | Cap every tool result at N chars (`0` = unlimited) |
| `list_dir_max_entries` | `200` | Cap the number of entries `list_dir` returns (`0` = unlimited) |
| `session_tool_max_chars` | `0` | Cap persisted tool-result content in session files (`0` = unlimited) |
| `noise_tools` | `["web_fetch", "open", "fetch_page"]` | Tool results replaced by a marker in persisted sessions |
| `query_refine` | `false` | Auto-refine short `query` args via a lightweight model call |
| `query_refine_min_words` | `3` | Minimum query length before refinement applies |
| `query_refine_context` | `4` | Recent-message context injected into refinement |
| `search_results` | `5` | Number of results `web_search` returns |

Handlers read config at runtime via the `_config` keyword argument, passed only when declared.

See [config.md](config.md) for the `tools.allow`, `tools.deny`, and `tool_permission` keys, and [security.md](security.md) for the threat model.

## Status and activity lines

Tool status is ephemeral REPL/CLI UI, never persisted to session files (tool calls and results are already recorded there). Registered tools render a typed activity line, `<glyph> <verb> <key_arg>` (e.g. `← Read README.md`, `→ Write test.md`, `$ Run pytest`), gated by `glyph_lines` (default `true`). Category defaults map to glyphs: read `←` Read, write `→` Write, search `%` Search, exec `$` Run, ask `~` Ask, todo `-` Todo, call `↳` Call, delegate `↳` Delegate, offload `↳` Offload. Unmapped categories fall back to the `[tool: key_arg]` oneliner plus any `status` detail lines. Filesystem tools use the `*` glyph with distinct verbs: `* Glob`, `* List`, `* Grep`.

When `glyph_params` is on (default `true`), the parameters the model passed (excluding the one already shown in the label) are appended: `← Read engine.py [offset=299, limit=85]`, `$ Run pytest [cwd=/workspace, timeout=600]`. Confirm prompts show the same suffix so cwd, timeout, and other arguments are visible before approving.

When a tool call fails, the first line of its `Error:` result is echoed as a dimmed `! Error: ...` line under the activity line (gated by `show_errors`, default `true`). This applies to every tool through the shared dispatch point: the agent loop, `/tool`, and policy-denied calls alike.

Soft tool results (short one-line informational notes a tool returns instead of content, like `(empty file)`, `(empty directory)`, `(no matches for "x")`, `(end of content)`, or `No search results found.`) surface as a dimmed info line under the activity line (gated by `show_notes`, default `true`). A tool opts in by declaring a `note` predicate (a callable taking the raw result and returning whether it is a note) in its registration metadata. The result itself is unchanged and still fed to the model.