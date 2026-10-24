# Configuration

Config is a single JSON object read from two files and merged per key, with project-local values winning:

1. **Global** - `~/.config/polyglav/config.json` (user-wide defaults, credentials).
2. **Local** - `.polyglav/config.json` in the project path (project overrides).

Every process merges them in memory. The merge descends into nested objects, so a local nested object overrides only the keys it names and keeps the default (or global) values for the rest. Lists and scalars replace wholesale, they never merge. Nothing is distributed to folders. Writes default to the **local** file and hold only the keys you selected, so a save never re-writes the merged config. API keys live outside the config, in the global provider registry (`~/.config/polyglav/providers.json`), managed through `/connect` (see [Models](#model-registry-not-config)).

```bash
# inspect in the REPL (alphabetical, key/value/source columns)
/config
# one key with its description and default
/config temperature
# every key with its default and description on an indented line
/config --verbose
# a value too long for the value column prints as an indented value/source block
# set a value (project-local, Git-like default)
/config temperature 0.3
# set a structured value
/config tools.deny ["run_command", "web_search"]
# set a single line in the global config
/config --global temperature 0.2
# remove a project-local value, falling back to global/default
/config unset temperature
# remove a value from the global config
/config --global unset temperature
# reload from disk
/config reload
```

The `polyglav config` CLI does the same headlessly and is fully scriptable:

```bash
polyglav config get max_tokens --show-origin     # one or more values + where they come from
polyglav config set max_tokens 0                 # project-local
polyglav config set max_tokens 0 --global        # global file
polyglav config unset max_tokens                 # remove from project-local
```

Deleting a project's `.polyglav/config.json` reverts it to the global and built-in defaults. To keep settings across local deletions, set them globally with `--global` (accepted by both the REPL `/config` and the CLI), e.g. `/config --global provider ollama`, `/config --global model <model>`.

## Schema

| Key                         | Default                | Description                                                            |
|-----------------------------|------------------------|------------------------------------------------------------------------|
| `access`                    | `{"read_tools": [...]}` | Read-class permission keys (`read`, `list`, `web`, `catalog`, `ask`, `delegate`). Any key not listed is write-class, and unknown/new plugin keys default write (fail-closed). See [modes.md](modes.md) |
| `ask_min_question_chars`    | `8`                    | Minimum length of a `kind='direction'` ask question when it has no `context` and no `options`. A shorter question is rejected with an error so the model asks a self-contained question. `0` disables the guard |
| `ask_policy`                | *(see below)*          | Routing for the `ask` tool by kind (`permission`/`direction`)          |
| `auto_continue`             | `true`                 | On truncation (`finish_reason=length`) with a partial answer, re-request with a "continue" instruction and stitch the parts into one message |
| `auto_continue_max`         | `2`                    | Max continuation rounds per turn before reporting truncation     |
| `base_url`                  | `"https://api.ollama.com"` | Provider endpoint                                                  |
| `clear_screen`              | `true`                 | Clear the screen before the REPL banner                                |
| `compact_keep`              | `4`                    | Turns to keep when compacting the provider context                     |
| `confirm_timeout`           | `0`                    | Seconds a REPL confirm/ask prompt waits for input before auto-denying (`0` = wait forever). Applies at any depth, so an unattended-but-watched run still cannot freeze on a prompt. See [Unattended mode](#unattended-mode) |
| `connect_check`             | `true`                 | Test the provider connection on config changes: `/connect` probes before saving (broken values rejected unless confirmed), `/provider` warns on a failed probe. `false` skips all probes |
| `delegate_depth`            | `1`                    | Maximum nested `delegate` siblings. `0` = unlimited. A sibling cannot spawn another until the user raises this. See [modes.md](modes.md) |
| `footer_tokens`             | `["context"]`          | Token counts the footer shows, in order, joined by `/`. `context` = `<n> tokens` (context/input size, chars/4 fallback), `in`/`out`/`thinking` = `<n>t` from provider usage (unavailable counts skipped). Empty list hides the section |
| `glyphs`                    | `{}`                   | Glyph overrides by meaning (`read`, `write`, `search`, `exec`, `ask`, `todo`, `call`, `delegate`, `enter`, `return`, `warning`, `question`, `default`, `spinner`), or `"ascii"` for the ASCII preset. No runtime detection |
| `grant_permission`          | `{}`                   | Optional narrowing of the mode-derived delegation ceiling. In `write` mode the mode itself grants write keys, in `read` mode grants are denied, and this key can only narrow the result (for example `{"bash": "ask"}`). See [Permission authority](#permission-authority) |
| `hide_confirm_input`        | `true`                 | Hide the typed input for the REPL `[Y/n]` tool confirm prompt (the answer is not echoed). Free-text `ask` answers stay visible |
| `list_dir_max_entries`      | `200`                  | Cap entries `list_dir` returns (`... (showing first N of M entries)` appended). `0` = unlimited |
| `markdown_streaming`        | `false`                | Basic markdown-aware streaming                                         |
| `max_team_depth`            | `2`                    | Maximum nested team runs (a `call` stage that itself runs a team). `0` = unlimited. Cycles are refused regardless. See [teams.md](teams.md#the-team-tool) |
| `max_tokens`                | `8192`                 | Output token cap sent to the provider. `0` = unset (provider default applies, e.g. Ollama caps at 2048). The default overrides low provider defaults |
| `mcp.servers`               | `[]`                   | MCP client server definitions (see [mcp.md](mcp.md) for the schema)     |
| `mcp_server.allow_ask`      | `true`                 | When serving MCP, run `ask`-policy tools (deferred to the client) vs refuse them |
| `memory`                    | `true`                 | Enable bounded memory summaries under `.polyglav/memory/`: role memory injected into sub-agent prompts, team/job memory into briefs, each refreshed after a run. `false` disables every scope |
| `memory_max_chars`          | `2000`                 | Cap characters of a memory summary injected into a prompt or brief (`... (truncated)` appended). `0` = unlimited |
| `memory_scopes`             | `{"role": true, "team": true, "job": true}` | Per-scope memory toggles, applied on top of `memory` |
| `mode`                      | `"read"`               | Active agent mode: `read` (default, plan) or `write` (work). `read` adds the bookkeeping tools `plan_write` and `todo`. Any unknown value falls back to `read` with a warning. Switch the session with `/mode <name>` or persist with `/config mode <value>`. See [modes.md](modes.md) |
| `model`                     | `"llama3.2"`           | Model name. A `provider/model` ref (e.g. `opencode-go/deepseek-v4-flash`) unfolds to that provider and model. `/model <ref>` persists only the ref, so a project config can be just `{"model": "provider/model"}`, while `provider`/`base_url` remain explicit overrides for `openai-compatible` and custom URL providers. An unfolded model must be approved (see [Model refs and approval](providers.md#model-refs-and-approval)) |
| `output_log`                | `false`                | Write everything the REPL prints to a file, plain text (ANSI stripped), so a mis-rendered line can be inspected later. Spinner repaints are skipped. Off by default, and the onboarding asks about it (default off) |
| `output_log_ansi`           | `false`                | Write the raw stream to the output log (ANSI colors and control characters kept) instead of plain text, for manual inspection |
| `output_log_dir`            | `".polyglav/output"`     | Directory for the output log, relative to the worktree (or absolute). One file per session, named after it |
| `plan`                      | `{"dir": ".polyglav/plans"}` | Plan file directory, relative to the worktree or absolute. Plans are local by default and ignored by the `.polyglav/*` rule. See [modes.md](modes.md) |
| `plugins`                   | *(bundled)*            | Plugins to load. Empty = all discovered plugins load                   |
| `print_max_chars`           | `4000`                 | Cap characters `/print` shows per part (`... (N more chars, use --full)` appended). `0` = unlimited, `--full` overrides for one call |
| `project_instructions`     | `"AGENTS.md"`          | Per-worktree instructions file auto-loaded into the system prompt (e.g. `AGENTS.md`, `CLAUDE.md`). `""` disables. Absent files skipped, content capped at 20000 chars |
| `provider`                  | `"ollama"`             | Provider name. Bundled provider plugins (`polyglav-core-ollama`, `-openai`, `-groq`, `-anthropic`, `-opencode`) register `ollama`, `openai`, `groq`, `anthropic`, `opencode`, `opencode-go`. `openai-compatible` is the generic fallback. External plugins can register more |
| `query_refine`              | `false`                | Auto-refine short web-search queries via a lightweight model call      |
| `query_refine_context`      | `4`                    | Recent-message context to inject into refinement                       |
| `query_refine_min_words`    | `3`                    | Minimum query length before refinement applies                         |
| `reasoning`                 | `"auto"`               | Request reasoning and control its token budget: `false`/`"off"` = none, `true`/`"on"`/`"auto"` = provider default, `"low"`/`"medium"`/`"high"` = explicit budget hint. Mapping is provider-specific (OpenAI `reasoning_effort`, Claude `thinking.budget_tokens`, Qwen `enable_thinking`) |
| `report.webhook`            | `""`                   | URL the bundled `polyglav-core-webhook` report connector POSTs a completed job run to (JSON). Empty = no out-of-band report. See [jobs.md](jobs.md#report-back) |
| `search_results`            | `5`                    | Number of search results to fetch                                      |
| `show_version`              | `true`                 | Show the version in the REPL banner                                    |
| `stream_retries`            | `2`                    | Extra attempts (after the first) when a provider stream ends before a completion event without content |
| `stream_retry_delay`        | `0.5`                  | Seconds to wait between stream retries                                  |
| `system_prompt`             | `""`                   | The root instruction, injected for every front-end (REPL, `run`, `serve`) and composed with the active mode. Onboarding sets it later, and empty means no root persona |
| `temperature`               | `0.7`                  | Sampling temperature                                                   |
| `tool_analysis`             | `false`                | Model-generated one-line analysis of each tool result (log-only)      |
| `tool_calling`              | `true`                 | Enable OpenAI-compatible function calling                              |
| `tool_max_result_chars`     | `100000`               | Cap tool-result content returned to the model (`... (truncated)` appended). `0` = unlimited. With the default, the model sizes files via the `file_read` header and pages with `offset`/`limit` |
| `tool_permission`           | *(see below)*          | Category permission actions                                            |
| `tools.allow`               | `[]`                   | Name-level allowlist. Empty means no restriction                       |
| `tools.deny`                | `[]`                   | Name-level deny list (takes precedence over allow)                     |
| `tools_output_drop`         | `["web_fetch", "open", "fetch_page"]` | Tool results replaced by a marker with the ref in persisted sessions |
| `tools_output_dir`          | `".polyglav/tmp/"`     | Persistent tool output folder used when `tools_output_spill` is on, relative to the worktree or absolute |
| `tools_output_max_chars`    | `0`                    | `0` = unlimited. Caps the inline persisted tool-result content, while the full text stays at the ref |
| `tools_output_spill`        | `false`                | Persist every tool result under `tools_output_dir` instead of the system temp directory. Every part records a `ref` |
| `tools_output_tmp_max_bytes` | `50000000`            | Cap on the total size of the spill roots. Oldest files are removed past the cap. `0` = unlimited |
| `unattended`                | `false`                | Unattended mode: no stdin is read at any depth. Confirms auto-deny and `ask target='user'` parks as a pending request (`.polyglav/asks.json`) instead of prompting. See [Unattended mode](#unattended-mode) |
| `verbosity`                 | `"normal"`             | Display volume: `quiet`, `normal`, or `verbose`                         |
| `verbosity.footer`          | `"inherit"`            | Footer detail: `off`, `summary`, `full`, or `inherit`                   |
| `verbosity.subruns`         | `"inherit"`            | Sub-run detail: `off`, `summary`, `full`, or `inherit`                  |
| `verbosity.thinking`        | `"inherit"`            | Thinking detail: `off`, `summary`, `full`, or `inherit`                 |
| `verbosity.tools`           | `"inherit"`            | Tool detail: `off`, `summary`, `full`, or `inherit`                     |
| `web_search`                | `false`                | Auto-search mode: search the web before answering                       |
| `word_streaming`            | `true`                 | Buffer REPL output to word boundaries so words render fully formed (no mid-word pauses). `false` streams character-by-character |

### `modes`

There are two modes: `read` (default, described as **plan**) and `write` (described as **work**). `read` allows read-class permission keys plus the bookkeeping tools `plan_write` and `todo`, and denies every workspace write key. `write` leaves write keys to `tool_permission`. A mode may set a `cap`, a description, an instruction block, and a submitted-line color:

```json
{
  "mode": "read",
  "modes": {
    "read": {
      "cap": "read",
      "description": "Plan: investigate, write the plan, track the todo",
      "system_prompt": "You are in read mode. Plan: ...",
      "color": "cyan"
    },
    "write": {
      "cap": "write",
      "description": "Work: execute the plan, update the todo",
      "system_prompt": "You are in write mode. Work: ...",
      "color": "orange"
    }
  },
  "plan": { "dir": ".polyglav/plans" },
  "access": {
    "read_tools": ["read", "list", "web", "catalog", "ask", "delegate"]
  }
}
```

`cap` is `read` or `write` and defaults from the mode name, so a custom mode named `read` is read-capped and any other name is write-capped. `description` is optional and shown by `/modes --verbose`. Access is classified by permission key. Any key not in `access.read_tools` is write-class, and an unknown key (a new plugin permission) defaults write, so read mode is fail-closed. The read cap is applied last, after grants and per-invocation resolvers, so a grant cannot widen past it. The mode instruction and `system_prompt` are injected as a system message, and the active mode is recorded on each turn. Switch the current session with `/mode <name>` and persist with `/config mode <value>`. An unknown `mode` falls back to `read` with a warning. Full detail in [modes.md](modes.md).

### `plan`

```json
{
  "plan": {
    "dir": ".polyglav/plans"
  }
}
```

`plan.dir` is the plan file directory, relative to the worktree or absolute. The default is local and ignored by the `.polyglav/*` rule. Set it to a committed path, for example `docs/plans`, to keep plans in the repository. `plan_write` uses the `read` permission key, so it is available in both modes and needs no new permission. See [modes.md](modes.md).

### `tool_permission`

```json
{
  "ask": "allow",
  "bash": "ask",
  "bash_allow": ["pytest", "python -m unittest", "ruff", "git"],
  "call": "allow",
  "catalog": "allow",
  "delegate": "allow",
  "edit": "allow",
  "list": "allow",
  "mcp": "ask",
  "read": "allow",
  "vcs": "ask",
  "web": "allow"
}
```

Actions are `allow` (no prompt), `ask` (Y/n confirm), `deny` (tool hidden/refused). Read/write/list outside the worktree escalate to `ask` automatically. The `call` category gates the `call` tool. On top of the category action, a call resolves its permission from the target: a role uses its own `tool_permission.call` and a team uses its stage roles' `call` actions. A role not in the registry defaults to `deny` (see [roles.md](roles.md)). The `delegate` category gates the read-class sibling. The `ask` category gates the `ask` tool (default `allow`, the interaction itself, answered by the user, see [tools.md](tools.md)). The `catalog` category gates the `catalog` tool (default `allow`). It writes only to the project catalog in `.polyglav/`, so a team-composing agent can manage roles, teams, and skills without general file edits. Set it to `ask` to confirm every catalog change. The `vcs` category gates the `git_commit` tool (default `ask`): a role whose carve sets `vcs: allow` (an unattended committer, granted by its role) commits without a prompt, every other role confirms, and the broad staging form (`all=true`) always asks so an unattended commit never sweeps unrelated work. The never-push rule is unaffected, `git_commit` does not push, merge, checkout, or rewrite history.

### `ask_policy`

Routes the `ask` tool by kind:

```json
{
  "ask_policy": {
    "permission": "auto",
    "direction": ""
  }
}
```

`permission` is `auto` (ask the user) or `deny` (disable permission asks). `direction` always asks the user; `caller` and `auto` are accepted as `user` for one version. A sub-agent inherits the root `ReplUI` as `_ask_ui`, so its asks reach the terminal; under unattended mode they park instead.

- `permission` - a sub-agent's request for a tool or write category it is not allowed to use (`ask(kind="permission", permission="bash")`). The user answers at the terminal. In `read` mode a request for a write key or for a category with declared write actions (for example `catalog save`) is redirected to a mode switch, since the action cannot take effect under the read cap (attended: the user is asked to switch, headless: the agent is told to use `ask(kind="direction")`). In `write` mode `auto` prompts the user, `deny` disables grants. A request above the mode-derived ceiling is always denied. The user may grant `always` (reusable for the rest of that sub-agent's run) or `once`. A user-routed ask offers `Approve once` / `Approve always` / `Deny`.
- `direction` - a decision or scope change. It always asks the user; `caller` and `auto` are accepted as `user` for one version. An explicit `target` is no longer part of the schema.

### Permission authority

Every engine has two permission axes:

- `tool_permission` - what the engine itself may use.
- `grant_permission` - the ceiling on what it may hand down to sub-agents.

Both take permission keys, not tool categories: `ask`, `bash`, `call`, `catalog`, `delegate`, `edit`, `list`, `mcp`, `read`, `vcs`, `web`. A `catalog` save normalizes a category name (`write` -> `edit`, `exec`/`shell`/`cmd` -> `bash`, `search` -> `web`), rejects an unknown key with the valid list, and accepts an action of `allow`/`ask`/`deny` (`true`/`false` are accepted as `allow`/`deny`).

A sub-agent's effective permissions are the parent's `tool_permission`, narrowed by the role's `tool_permission` carve and capped by the mode-derived ceiling. The mode sets that ceiling: `write` makes write keys grantable, `read` denies them, and `grant_permission` (role or config) can only narrow the result. A role can never widen a category above the ceiling, so a sub-agent cannot gain a permission its caller was not authorized to delegate, and a sub-agent cannot escalate its mode past the caller's.

A role that sets `grant_permission` may delegate categories it does not use itself. For example, a supervisor with `edit`/`bash` denied for itself but allowed in its ceiling can hand them to an `implementer` while never running them, as long as the session is in `write` mode.

An approved permission request creates a one-shot grant on the asking sub-agent (`once`), consumed by the next matching call. The user may grant `always`, reusable for the rest of that sub-agent's run. Grants are never inherited by grandchildren and are recorded in the session `permissions` audit array.

### Unattended mode

`unattended: true` guarantees that nothing in a turn reads stdin, at any depth, so an overnight REPL run cannot freeze on a prompt. It applies to the whole sub-agent tree:

- **Confirms auto-deny.** A tool whose policy action is `ask` (e.g. `run_command` with `bash: ask`) returns `[cancelled] User declined the <name> call` instead of prompting.
- **`ask target='user'` parks instead of prompting.** The root engine drops its terminal UI (`_ask_ui` is not propagated down the tree), and any user-routed ask becomes a pending request persisted in `.polyglav/asks.json`, returned to the agent as `[parked] Ask #<id> ...` so it continues or finishes. A sub-agent's user ask parks rather than consulting a caller, so the user decides. Permission asks park the same way.
- **Model approval is not prompted.** An unapproved role/team model is denied (the run reports the error) unless the headless `approve_models` flag was passed. Launch with `--approve-model` if the run needs to approve one itself.

Enable it per run with `polyglav --unattended` (not persisted), in config with `unattended: true`, or live with `/unattended`. Parked asks are listed and answered with `/asks` or the serve API (`GET /asks`, `POST /asks/<id>/answer`). Answering marks the ask answered and injects the answer into the origin session, so the next turn on that session resumes with the user's decision in context. Scheduled/durable job engines run unattended, so a job parks its user asks the same way. `confirm_timeout` (seconds, default `0` = forever) additionally makes attended confirm/ask prompts self-limiting, so a prompt left unanswered auto-denies instead of hanging.

### `bash_allow` - command allowlist for `run_command`

`tool_permission.bash_allow` (list, default `[]`) restricts `run_command` to commands whose first token matches an allowed prefix. Empty or unset means unrestricted (the `bash` action applies to every command). When set:

- Commands split into chained segments over `&&`, `||`, `;`, `|`, and `&`. Every segment must start with an allowed prefix (e.g. `pytest -q && ruff check .` needs both `pytest` and `ruff`).
- Shell-script forms are rejected outright: multi-line commands and heredocs (`<<`) always return `deny`.
- A matching command falls through to the normal `bash` action (`ask` by default, `allow`/`deny` per config). A non-matching command is `deny`.

The check runs through the per-invocation policy resolver, so it composes with modes, name-level `tools.deny`/`tools.allow`, and the worktree escalation. `bash_allow` gives a coding agent a safe default set (tests, linters, git) without opening up arbitrary shell.

## Model registry (not config)

Two global files live separately from config in `~/.config/polyglav/`. Neither is part of the config merge: `/config` never lists or writes them, and neither has a local scope.

### Provider registry (`providers.json`)

`~/.config/polyglav/providers.json` (written `0600` when it holds keys) stores the active connections, keyed by provider name:

```json
{
  "ollama": {
    "base_url": "https://custom.example/v1",
    "api_key": "...",
    "added_at": "...",
    "last_used": "..."
  }
}
```

- `api_key` lives here, one per provider, and is the only place API keys live.
- `base_url` is the effective base URL of the connection: the preset provider default (e.g. `/connect ollama`) or a custom URL (`/connect <url>`). The engine falls back to it when the config leaves `base_url` empty.
- Managed through `/connect` (writes the key and any custom base URL). Re-running it re-enters a missing or stale key.
- The engine resolves the active provider's API key from this file (matching entry or `""`), falling back to a stored custom `base_url` when the config has none. There is no `api_key` config key anymore, and `polyglav config set api_key` would store an unused ordinary value. Deleting a project config cannot lose the registry, which is global by design.

### Model registry (`models.json`)

`~/.config/polyglav/models.json` is the history of approved models. Entries are `{provider, model, added_at, last_used}` with no API keys (those live in `providers.json`). It records every model you connect or switch to, so `/models` shows what has been used per provider with `>` marking the active one. The active model still comes from `config.model`.

- `/connect` records the model for the connection it just saved.
- `/models` shows approved models grouped by provider, the active one marked `>`, plus `(key)` when that provider has a stored key. Each entry carries `ok_at` (last successful run) and `last_error` (last failure), so `/models` marks a model `(unused)` when it never completed a run and `(failed)` when its last run errored.
- `/models list [provider]` probes a provider's advertised models live (default: current provider).
