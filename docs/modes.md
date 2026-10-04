# Modes and access

An agent has one posture at a time: `read` or `write`. `read` is the default. The mode decides which tools the model can call, so a plain chat is read-only until the user switches to `write`.

## Read and write

- `read` allows read-class tools only. Writes, edits, shell commands, commits, MCP tools, and delegation are denied.
- `write` leaves write-class tools to `tool_permission`, so each write key is still bounded by its own `allow`/`ask`/`deny` action.
- Any value other than `read` or `write` resolves to `read` and prints a warning.

The prompt color signals the posture: cyan for `read`, orange for `write`. The banner shows a `[read mode]` label.

## Access classification

Tools are classed by permission key, not by tool name. Config `access.read_tools` lists the read-class keys:

```json
{
  "access": {
    "read_tools": ["read", "list", "web", "catalog", "ask", "handoff", "offload"]
  }
}
```

Any key not listed is write-class, and an unknown key (for example a permission a new plugin introduces) defaults to write. This is fail-closed: a plugin cannot make a write tool readable by accident, the user has to add its key to `read_tools`.

Default write keys include `edit`, `bash`, `vcs`, `mcp`, `call`, and `delegate`. Mixed tools gate per action: `catalog` allows `list`/`show` in read mode and denies `save`/`remove`/`reload`, `git` is read while `git_commit` is write (`vcs`), and the MCP management tools allow `mcp_list` in read mode while `mcp_connect`/`mcp_disconnect` and the imported remote tools are write (`mcp`).

## The mode cap

The mode is the outermost bound, applied last. It is enforced in `ToolPolicy` after grants and per-invocation resolvers, so neither a grant nor a role carve can widen past it. A sub-agent inherits its caller's mode, and `read` clamps the delegation ceiling, so a granted `bash` still cannot run in read mode.

## Switching

- `/mode` shows the current mode and the available names.
- `/mode <name>` switches the mode for the current session. It does not write the config.
- `/config mode <value>` persists the mode to the local config.
- `--mode <name>` sets the mode for `polyglav run` and `polyglav serve`.
- `polyglav jobs add` records an explicit mode in the job definition.

The active mode is stored on the session and recorded on every turn, so a loaded session keeps its mode and the session log shows which posture produced each turn.

## Roles

A role carve only needs to declare write keys, because read keys are allowed by default. Use the permission key (`bash`, `edit`, `read`, `vcs`), not the tool name. A role can narrow a read key, but it can never widen past the mode cap.

## Consequences

- Read mode cannot run tests or lint (`run_command` and `code_test` are `bash`), commit (`vcs`), or use MCP until the user switches to `write`.
- Existing configs and scripts that relied on the old `build` default now run read-only until they set `mode: "write"`.
- A new plugin write key stays denied in read mode until it is added to `access.read_tools`.
