# Modes and access

An agent has one posture at a time: `read` or `write`. `read` is the default and is described as **plan**. `write` is described as **work**. The mode decides which tools the model can call, so a plain chat is read-only until the user switches to `write`.

## Read and write

- `read` (plan) allows read-class tools plus the bookkeeping tools `plan_write` and `todo`. It denies workspace writes, edits, shell commands, commits, MCP tools, and `call`.
- `write` (work) leaves write-class tools to `tool_permission`, so each write key is still bounded by its own `allow`/`ask`/`deny` action.
- `/modes --verbose` prints each mode's description. The defaults are `Plan: assistant, chat, and planning tasks` and `Work: working tasks, tools, edits, commands, roles, and teams`.
- Any value other than `read` or `write` resolves to `read` and prints a warning.

The submitted-line color signals the posture: cyan for `read`, orange for `write`. The live prompt is a plain `_ `, and the line reprints in that color after Enter. The banner shows the current mode, for example `@ Read mode`.

## Plan and todo bookkeeping

`plan_write` and `todo` use the `read` permission key. They write only `.polyglav/plans/` and `.polyglav/todos/`, never the workspace, so read can carry them without weakening the read cap.

- Plan: `.polyglav/plans/plan_<ts>_<session_id>.md`, path configurable with `plan.dir`.
- Todo: `.polyglav/todos/<session>.json`.
- Both are optional and model-initiated. The engine never creates a plan or a todo. A short task needs neither.
- The plan is the long-run memory: the user's or caller's instructions and constraints, findings, decisions, steps, role and team split, verification, open questions, and next.
- The todo is the current work state: a short list of tasks and statuses.
- The plan is injected as a bounded system block every turn. The todo is injected as a compact current-work block. Both survive compaction and are passed to sub-runs and team briefs.
- `/plan` shows the current plan, `/plan use <path>` attaches one, `/plan off` detaches it, `/plans` lists every stored plan, and `/plans <id>` shows one.
- `/todo` shows the current todo, `/todo add <title>` and `/todo done <id>` edit it, `/todos` lists every stored todo, and `/todos <id>` shows one.
- Creating or updating either prints a system note. The tool call and result stay in the session log.

## Access classification

Tools are classed by permission key, not by tool name. Config `access.read_tools` lists the read-class keys:

```json
{
  "access": {
    "read_tools": ["read", "list", "web", "catalog", "ask", "delegate"]
  }
}
```

Any key not listed is write-class, and an unknown key (for example a permission a new plugin introduces) defaults to write. This is fail-closed: a plugin cannot make a write tool readable by accident, the user has to add its key to `read_tools`.

Default write keys include `edit`, `bash`, `vcs`, `mcp`, and `call`. The `call` tool resolves a role or team per target. The `delegate` tool is the read-class sibling. Mixed tools gate per action: `catalog` allows `list`/`show` in read mode and denies `save`/`remove`/`reload`, `git` is read while `git_commit` is write (`vcs`), and the MCP management tools allow `mcp_list` in read mode while `mcp_connect`/`mcp_disconnect` and the imported remote tools are write (`mcp`).

## The mode cap

The mode is the outermost bound, applied last. It is enforced in `ToolPolicy` after grants and per-invocation resolvers, so neither a grant nor a role carve can widen past it. A sub-agent inherits its caller's mode, and `read` clamps the delegation ceiling, so a granted `bash` still cannot run in read mode.

A request in `read` mode for a write key, or for a read-class category with declared write actions such as `catalog save`, is redirected to a mode switch, because the action cannot take effect under the read cap.

## Switching

- `/mode` shows the current mode.
- `/modes` lists the available names, marking the current one. `/modes --verbose` adds each mode's description, and `/modes <name>` prints a mode's instruction.
- `/mode <name>` switches the mode for the current session. It does not write the config.
- `/config mode <value>` persists the mode to the local config.
- `--mode <name>` sets the mode for `polyglav run` and `polyglav serve`.
- `polyglav jobs add` records an explicit mode in the job definition.

The active mode is stored on the session and recorded on every turn, so a loaded session keeps its mode and the session log shows which posture produced each turn. The only permission widening is `read` to `write`, and the model asks for it through the `ask` tool.

## Roles

A role carve only needs to declare write keys, because read keys are allowed by default. Use the permission key (`bash`, `edit`, `read`, `vcs`), not the tool name. A role can narrow a read key, but it can never widen past the mode cap.

A leader can set `grant_permission` to hand down a category it denies itself, so one supervisor can authorize an implementer without using the tool itself. The mode sets the outer ceiling: write keys are grantable in `write`, and denied in `read`.

## Consequences

- Read mode cannot run tests or lint (`run_command` and `code_test` are `bash`), commit (`vcs`), or use MCP until the user switches to `write`.
- Read mode can still write the plan and the todo, because those tools write only `.polyglav/plans/` and `.polyglav/todos/`.
- Existing configs and scripts that relied on the old `build` default now run read-only until they set `mode: "write"`.
- A new plugin write key stays denied in read mode until it is added to `access.read_tools`.

## Lineage

Read mode descends from OpenCode's planning posture. Polyglav shipped `plan`/`build` modes, replaced them with `read`/`write`, and now names planning in read and working in write. The durable plan and todo are the long-run memory that the earlier posture did not have.
