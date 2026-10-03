# Security

Polyglav is local-first and deliberately small. Its security posture rests on an explicit per-tool permission model, worktree-scoped file access, a config-driven surface, and complete session logs that double as an audit trail. This document covers the threat model and the controls in place today.

## Permission model

Every tool call is gated by `ToolPolicy` (`src/polyglav/tools/policy.py`) with three actions:

- **`allow`** - runs without prompting.
- **`ask`** - prompts Y/n in the loop.
- **`deny`** - the tool is filtered from the provider schema and refused on direct calls.

Resolution precedence (see [tools.md](tools.md) for the full flow):

1. Name-level `tools.deny` and the `tools.allow` allowlist. A `deny` here wins outright.
2. The category action from `tool_permission` (`bash` / `delegate` / `edit` / `list` / `read` / `vcs` / `web`). A `deny` here is final and skips the resolver.
3. A per-invocation resolver (`permission_fn`) that runs after the category action and overrides a non-`deny` one from the tool's current arguments, or returns `None` to defer to it. For example `delegate` resolves per role: a configured role uses its own `tool_permission` and a role outside the registry is denied (see [roles.md](roles.md)), and `git_commit` defers to `vcs` except for `all=true`, which asks.
4. Worktree escalation: `read` / `list` / `write` tools on paths outside the worktree escalate `allow` to `ask`.

The worktree is the directory holding the local `.polyglav/`, which is the launch directory or `--path`. A `file_read` / `list_dir` / `file_write` / `glob` / `grep` on a path outside it escalates to `ask`, so an agent cannot silently reach files beyond its scope. Launching from `~` makes home the worktree, so subdirectories do not escalate. Launch inside the project or pass `--path` for project-scoped prompting.

`bash` defaults to `ask`, so every `run_command` confirms unless `tool_permission.bash = "allow"` is set explicitly. `delegate` defaults to `allow`, refined per invocation by the target role's own permission (a role may set `delegate: "ask"` to confirm).

The `ask` tool is the explicit human-in-the-loop channel: it pauses the run and poses a question to the operator at the terminal (`target='human'`) or to the lead agent that delegated the run (`target='lead'`, a bounded model consultation). It is the only tool that deliberately talks to a person. In headless mode there is no terminal and a root engine has no lead, so `ask` returns an error result and the run continues without pausing. In unattended mode (`unattended: true`, `polyglav --unattended`, `/unattended`) the terminal UI is dropped at the root and never propagated to sub-agents, so no ask at any depth reads stdin: confirms auto-deny and human asks park as pending requests in `.polyglav/asks.json` (returned to the agent as `[parked] Ask #<id>`, answered later via `/asks` or the serve API). Agents that must not ask can be stripped of the tool with `tools.deny: ["ask"]`. The question and answer are persisted in the asking session's log, so what was asked and decided stays on the record.

`ask(kind="permission", permission=...)` is the escalation channel for a tool a sub-agent is not allowed to use. In `read` mode a write-category request is redirected to a mode switch. In `write` mode the request is routed by `ask_policy.permission` (`auto` = the lead decides, `human` = the operator, `deny` = disabled) and can never exceed the mode-derived ceiling. An approved request creates a one-shot grant on the asking sub-agent, consumed by the next matching call. The operator may grant `always` for the rest of that sub-agent's run, the lead only ever grants `once`. Grants are not inherited by grandchildren, and each grant and its use is recorded in the session `permissions` audit array.

## Headless agents are confined

In headless mode (`polyglav serve` / `polyglav run`), `ask`-gated tools are denied outright, and the headless UI auto-answers with the configured `--yes` / `--no` policy. An agent's reachable surface is exactly its `allow` tools on paths inside its worktree. This isolation boundary makes one-agent-per-process fleets safe: a crash or misbehaving agent cannot touch another agent's folder or run commands it was not given. See [fleet.md](fleet.md).

## Delegation

The `delegate` tool runs a task under a role as an in-process sub-agent. A sub-agent shares the caller's worktree and tool policy, narrowed by the role's `tool_permission` carve and capped by the mode-derived ceiling, so it can never exceed what the caller is authorized to delegate and cannot escalate the mode. Ask-gated tools are auto-denied inside a sub-agent (no interactive confirm), so its effective permissions are the categories its carve allows. A denied call returns an explicit `permission denied` result instead of a user-decline marker, the sub-agent prompt names the auto-denied categories and tells it not to retry, and the loop stops after a few consecutive denials so it escalates through `ask` or finishes rather than looping. An approved `ask(kind="permission")` request adds a one-shot grant capped by the ceiling. The permission resolves per invocation from the target role: a configured role uses its own `tool_permission` (category `delegate` defaults to `allow`, set `ask` on a role to confirm each delegation), and a role outside the registry is denied outright. Delegation is recorded in the session `permissions` audit array like any tool call, and each sub-agent's work persists as its own `sub_<ts>_<id>` session log (the calling session is recorded as `parent_id`). For delegation across trust boundaries, run separate `polyglav serve` processes scoped to their own folders and delegate over the API instead. See [fleet.md](fleet.md).

## Modes

The mode ([modes.md](modes.md)) is the outermost bound. `read` (default) allows only read-class permission keys and denies every write-class key, so write, exec, commit, MCP, and delegation tools are filtered from the provider schema and refused on direct calls. `write` leaves write keys to `tool_permission`, still bounded by each key's action. Access is classified by permission key in config `access.read_tools`, and any key not listed (including a new plugin key) defaults write, so read mode is fail-closed. The cap is applied last, after grants and per-invocation resolvers, so a grant cannot widen past it. The active mode is stored on the session and recorded on each turn, so the posture in effect for every turn is auditable. An unknown `mode` value falls back to `read` with a warning.

## Config-driven surface

The model only sees tools whose schema passes policy filtering (`tools.allow` / `tools.deny` / `tool_permission`), and plugin activation is an explicit `plugins` list. The surface area (providers, tools, plugins, permissions) is configuration, not convention. Tool status lines are ephemeral UI, never persisted to session files. Permission decisions (each `allow` / `ask` / `deny` resolution and its outcome) are recorded in the session `permissions` array as an audit trail. Gaps against a full audit trail: session files are not hash-chained or tamper-evident (append-only by convention, not by construction), tool-result content can be redacted by `noise_tools` / `session_tool_max_chars`, and tool `analysis` is off by default (`tool_analysis`).

## Audit trail

Sessions are complete, append-only logs: every message, tool call with arguments and result, reasoning, and error is recorded with timestamps. Compaction only trims the provider context, never the log, so any action can be reconstructed later. See [session.md](session.md). For enterprise deployments this is the base for compliance and forensics, with central aggregation and tamper-evidence as additive hardening (see [use-cases/enterprise.md](use-cases/enterprise.md)).

## Data posture

- **Local-first** - config and session logs live on your disk. All provider traffic is outbound. No external telemetry or logging service holds enterprise data.
- **Zero dependencies** - the core is Python stdlib only, so there is no supply chain to audit and no lockfile churn. Plugins may add third-party deps, imported lazily and only when the plugin is used.
- **API keys** - stored in the global provider registry (`~/.config/polyglav/providers.json`, one key per provider, written `0600` when it holds keys), never in config or a session log by hand. Keep keys out of repositories.

## Plugins

Plugins are arbitrary Python code that run with your user's privileges. Install only plugins you trust. A plugin's `register_providers` hook runs at load, and its tools run on demand like any built-in tool. The manifest declares `polyglav_version` and `python` compatibility ranges, and incompatible plugins are skipped at load. See [plugins.md](plugins.md) for management and the security notes.

## Prompt injection

Tool results and fetched content are untrusted input returned to the model. Defense in depth today: tools are whitelisted by policy, `ToolRegistry.execute()` drops undeclared and `null` arguments (so a hallucinated parameter cannot reach a handler), results are bounded (`session_tool_max_chars`, `noise_tools`), and `run_command` requires confirmation by default. Worktree escalation keeps file access scoped.

## Threat model at a glance

| Asset | Control |
|-------|---------|
| Filesystem | Worktree-scoped `allow`/`ask`/`deny`, escalation outside the worktree |
| Shell | `run_command` gated by `bash: ask` by default, headless auto-deny |
| Delegation | Per-role per-invocation resolution (`delegate: allow` default, set `ask` per role, non-registry roles denied), sub-agents auto-deny `ask` and share only the caller's carve, own `sub_*` session logs |
| Network | Explicit tools (`web_search`, `web_fetch`), `web` permission |
| Provider context | Policy-filtered tool schema, argument cleaning, bounded tool results |
| Session data | Append-only local logs, local file ownership |
| Model | Config-driven provider/model selection, no autonomous self-modification |

## Planned hardening

Sandboxed exec (namespace/container isolation for `run_command`) and per-plugin virtualenv isolation are planned future work (see [TODO.md](../TODO.md) and [plugins.md](plugins.md)).