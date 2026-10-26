# Commands & CLI

## Slash commands

Run `polyglav` and type `/` to tab-complete commands. Use `/help` or `/help <cmd>` for details.

| Command                 | Aliases        | Description                                                    |
|-------------------------|----------------|----------------------------------------------------------------|
| `/asks`                 |                | List and answer parked asks from unattended runs (`/asks answer <id> <text>`, `/asks list [all|pending|answered]`, `/asks show <id>`). Answering resumes the origin session. See [config.md](config.md#unattended-mode) |
| `/compact`              | `/c`           | Summarize the conversation and trim the provider context       |
| `/config`              |                | Show, get, set, or unset config values (`/config <key> <value>`, `/config unset <key>`, `/config --global <key> <value>` for a global line). The default listing is alphabetical with `key`, `value`, and origin columns (`(default)`, `(global)`, or `(local)`) and hides descriptions. `/config <key>` shows the value, origin, default, and description, and `/config --verbose` (or `-v`) adds every default and description on an indented line. A value too long for the value column prints as an indented `value`/`source` block |
| `/connect`              |                | Connect a provider. `/connect` picks interactively from the known providers. `/connect <name>` presets a known provider's defaults and (re)enters its API key. `/connect <url>` detects a known host or creates a named custom provider (derived from the host, or `/connect <url> <name>` to name it). Tests the connection before saving, stores the API key + base URL in global `providers.json`, and writes `provider`/`base_url` into config - the model is picked separately with `/model` |
| `/exit`                 | `/quit`, `/q`  | Save and exit                                                  |
| `/help`                 | `/h`           | Show available commands and tools (`/help <cmd|tool>` for detail) |
| `/history`              |                | List the active session's turns as a numbered index: `/history [n|all] [--thoughts [all]] [--run <target>] [--tree]`. Default last 10, `--thoughts` adds a dim thinking excerpt (`all` prints it in full), `--run` reads another run's session, and `--tree` lists the root and its sub-runs. Turn lines include the turn's total tokens when the provider reported usage. See [session.md](session.md) |
| `/jobs`                 |                | Manage scheduled and durable jobs: `add`, `add-supervisor`, `approve`, `disable`, `enable`, `list`, `reject`, `remove`, `run`, `show`, `status`, `stop`. See [jobs.md](jobs.md) |
| `/mcp`                  |                | Manage MCP servers: `connect` (all if no name), `disconnect` (all if no name), `list`. See [mcp.md](mcp.md) |
| `/memorize`             |                | Summarize the active run into bounded memory: `/memorize` (active role), or `/memorize <role\|team\|job> <name>`. Writes `.polyglav/memory/<scopes>/<name>.md`. See [config.md](config.md) |
| `/mode`                 |                | Show the current agent mode, or switch it (`/mode <name>`). See [modes.md](modes.md) |
| `/model`                 |                | Show or switch the active model. `/model <name>` sets it on the current provider. `/model <provider>/<model>` switches provider and model together, approving the model on confirm |
| `/models`                |                | List configured models, or probe a provider's available models. `/models` shows the approved-model history grouped by provider (`(key)` when the provider has a stored key), marking `(unused)` when a model never completed a run and `(failed)` when its last run errored. `/models list [provider]` probes a provider's advertised models live (default: current provider), and `/models remove <provider>/<model>` drops a model from the registry, asking first when it is the active one |
| `/modes`                |                | List the available agent modes, marking the current one. `/modes --verbose` adds each mode's description, and `/modes <name>` prints that mode's instruction. See [modes.md](modes.md) |
| `/onboard`              |                | Set up this project (provider, model, mode, purpose, assistant, output log). See [plugins.md](plugins.md) |
| `/pause`                |                | Hold the next turn at the turn boundary; `/resume` clears it. State prints as `@ Paused #n` and `@ Resumed #n` |
| `/plan`                 |                | Show the current run's internal plan, attach one (`use <path>`), or detach it (`off`). See [modes.md](modes.md) |
| `/plans`                |                | List every stored plan, marking the attached one. `/plans <id>` prints one by plan id or session id. See [modes.md](modes.md) |
| `/plugins`              | `/plugin`      | Manage plugins: `disable`, `enable`, `install`, `list`, `uninstall`, `update` |
| `/print`                |                | Reprint a turn (or one part) in full: `/print <n>[.<m>] [--full] [--run <target>] [--tree]`. Shows the turn metadata, prompt, thinking, each tool call with input/output, and the answer. Tool output is read from its stored `ref` when the inline copy was dropped or capped. Each part is capped by `print_max_chars`, and `--full` drops the cap. `--tree` renders the root and its sub-runs. See [session.md](session.md) |
| `/provider`              |                | Show or switch the active provider                             |
| `/providers`             |                | List provider connections, alphabetical, with the active one marked and `(key)` when a key is stored, and `(custom)` for a provider with no built-in factory |
| `/resume`               |                | Clear a paused run and continue at the next turn |
| `/role`                 |                | Show the active run's role and session. See [roles.md](roles.md) |
| `/roles`                |                | Manage roles: `list` (`list <tag>` filters), `new <name> [prompt]`, `remove <name>`, `show <name>`. See [roles.md](roles.md) |
| `/runs`                 |                | Show the run tree read-only: run id, role, status, session, session id, duration, and own/tree tokens. Use `/print --run <target>` for a run's output. See [session.md](session.md) |
| `/session`              |                | Show or switch the active session: `/session new`, `/session load <name>`, `/session save`. Saved-session catalog operations live under `/sessions` |
| `/sessions`             |                | Manage the saved-session catalog: `delete`, `export <name> [out] [--json] [--tree]`, `import <file> [name] [--force]`, `list` (roots only), `preview` (see [session.md](session.md)) |
| `/skills`               |                | Manage skills: `list`, `new <name>`, `remove <name>`, `show <name>`. See [skills.md](skills.md) |
| `/teams`                |                | Manage teams: `list` (`list <tag>` filters), `new <name> [description]`, `remove <name>`, `run <name> <task>`, `show <name>`. See [teams.md](teams.md) |
| `/thinking`             | `/reasoning`   | Show or set the reasoning scope: `off`, `assistant`, `agent`, or `all` (`/thinking on` = `all`, `off` = `off`). Prints `@ Thinking: <scope>` |
| `/verbosity`            | `/verbose`     | Show or set display scopes: `/verbosity`, `/verbosity <scope>`, `/verbosity <scope> <value>`, `/verbosity preset quiet\|normal\|verbose`, `/verbosity reset [scope]` |
| `/todo`                 |                | Show or edit the current run's internal todo: `add <title>`, `start <id>`, `done <id>`, `block <id> [note]`, `remove <id>`, `list`. See [modes.md](modes.md) |
| `/todos`                |                | List every stored todo, marking the current one. `/todos <id>` prints one by session id or name. See [modes.md](modes.md) |
| `/tool`                 |                | Run a tool directly (`/tool <name> {"key": "value"}`)          |
| `/unattended`           |                | Show or toggle unattended mode (`/unattended on`/`off`): no stdin at any depth, confirms auto-deny, user asks park or return without pausing. See [config.md](config.md#unattended-mode) |
| `/version`              | `/v`           | Show the Polyglav version                                       |

`/help` renders commands with subcommands indented below and lists the allowed tools (policy- and mode-filtered, so read mode hides write and exec tools) the same way under `/tool`. `/tool` with no arguments lists the same tools with their short descriptions. Providers and models complete at the prompt: `/connect`, `/provider`, `/providers`, and `/models list` complete provider names, and `/model` completes a provider then its known models (from `models.json` and a cached live probe).

Delegation is a normal tool: the caller agent proposes it, or you run it directly, and `/tool call {"target": "researcher", "task": "..."}` routes through the same tool policy. A configured role is called without prompting (`call` defaults to `allow`. Set a role's `call` to `ask` to confirm), and a role outside the registry is denied. A named team runs with `/tool call {"target": "...", "kind": "team", "task": "..."}`. Anonymous read-only help runs with `/tool delegate {"task": "..."}`. See [roles.md](roles.md) and [swarm.md](swarm.md).

## CLI

```
usage: polyglav [-h] [--path PATH] [-v] {config,eval,export,fleet,jobs,mcp,models,plugins,run,serve} ...
```

Global:

| Flag          | Description                                      |
|---------------|--------------------------------------------------|
| `--path`      | Project path (default: current directory)        |
| `--version`, `-v` | Print the installed version and exit         |

### `polyglav run`

One-shot headless chat.

| Flag                 | Description                                                  |
|----------------------|--------------------------------------------------------------|
| `--prompt`, `-p`     | **Required.** The prompt to send                              |
| `--provider`         | Provider override (e.g. `ollama`, `openai`, `groq`)           |
| `--model`            | Model override (accepts a `provider/model` ref. Explicit `--model` auto-approves) |
| `--approve-model`    | Approve the configured model ref without prompting             |
| `--base-url`         | Base URL override                                            |
| `--mode`             | Agent mode override (`read` or `write`)                      |
| `--output`           | `json` (default) or `text`                                   |
| `--verbose`          | Print tool status and diagnostics to stderr                   |
| `--session-id`       | Persistent session name (load or create)                     |
| `--yes`              | Auto-approve tools that require confirmation                 |
| `--no`               | Auto-deny tools that require confirmation (default)          |
| `--path`             | Project path                                                 |

### `polyglav export`

Export a saved session to Markdown or JSON (see [session.md](session.md)).

| Flag             | Default                      | Description                       |
|------------------|------------------------------|-----------------------------------|
| `name`           | **Required**                 | Session name to export            |
| `--out`          | `.polyglav/exports/<name>.md`  | Output file, `-` for stdout       |
| `--json`         | off                          | Export JSON instead of Markdown (default `.polyglav/exports/<name>.json`) |
| `--path`         |                              | Project path                      |

### `polyglav import`

Import a session from a JSON export (see [session.md](session.md)).

| Flag             | Default                      | Description                       |
|------------------|------------------------------|-----------------------------------|
| `file`           | **Required**                 | JSON export to import             |
| `--name`         | the file's session name      | Session name to import as         |
| `--force`        | off                          | Overwrite an existing session with that name |
| `--path`         |                              | Project path                      |

### `polyglav models`

List configured models, or probe a provider's available models (mirrors `/models`).

```bash
polyglav models                          # approved-model history grouped by provider, `>` marks the active model, `(key)` a stored key
polyglav models list [provider]          # probe a provider's advertised models (default: current), exit 1 on failure
```

| Flag             | Default                      | Description                       |
|------------------|------------------------------|-----------------------------------|
| `--path`         |                              | Project path                      |

### `polyglav eval`

Tool-use evaluation harness: run task fixtures through the agent loop and report metrics. See [eval.md](eval.md).

```bash
polyglav eval --path <project> list              # list discovered fixtures
polyglav eval --path <project> run [--fixture <id>] [--provider P] [--model M]
polyglav eval --path <project> run --compare ollama,openai --output json
```

| Flag             | Default                      | Description                       |
|------------------|------------------------------|-----------------------------------|
| `--fixture`      |                              | Fixture id or substring (default: all) |
| `--provider`     |                              | Provider override                 |
| `--model`        |                              | Model override                    |
| `--base-url`     |                              | Base URL override                 |
| `--compare`      |                              | Comma-separated providers to compare |
| `--output`       | `table`                      | `table` or `json`                 |

### `polyglav config`

Scoped, scriptable config management, with the same layers as `/config` (see [config.md](config.md)).

```bash
polyglav config get [key ...] [--show-origin]   # effective values, default all keys
polyglav config set <key> <value> [--global]    # JSON-parseable value, default local
polyglav config unset <key> [--global]          # drop a value from the selected scope
polyglav config reload                          # re-read the config files from disk
```

| Flag             | Default                      | Description                       |
|------------------|------------------------------|-----------------------------------|
| `--global`       |                              | Operate on `~/.config/polyglav/config.json` |
| `--local`        | (default)                    | Operate on the project `.polyglav/config.json` |
| `--path`         |                              | Project path                      |
| `--show-origin`  |                              | `get` only - append default/global/local |

### `polyglav serve`

HTTP JSON API server. See [api.md](api.md). Also serves `POST /mcp` (MCP server) when the `polyglav-core-mcp` plugin is loaded.

| Flag          | Default      | Description                  |
|---------------|--------------|------------------------------|
| `--host`      | `127.0.0.1`  | Bind address                 |
| `--port`      | `8787`       | Bind port                    |
| `--path`      |              | Project path                 |
| `--mode`      |              | Agent mode override (`read` or `write`)               |

### `polyglav mcp`

Run polyglav as an MCP server over stdio (newline-delimited JSON-RPC). See [mcp.md](mcp.md). Requires the `polyglav-core-mcp` plugin.

| Flag          | Default      | Description                  |
|---------------|--------------|------------------------------|
| `--path`      |              | Project path                 |

### `polyglav jobs`

Scheduled and durable jobs (cron / interval / one-shot), with retries, backoff, a user-in-the-loop approval gate, and recorded run history. See [jobs.md](jobs.md).

| Subcommand    | Description                                                              |
|---------------|--------------------------------------------------------------------------|
| `add`         | `polyglav jobs add <name> --file jobs/<name>.md --cron "0 2 * * *"` (or `--interval N` / `--at ISO`, with `--prompt` optional when `--file` given), plus `--mode`, `--provider`/`--model`, `--role`, `--system-prompt`, `--tools-deny`, `--tool-permission`, `--retries`, `--backoff`, `--timeout`, `--require-approval`, `--approve-model`, `--approval auto` |
| `add-supervisor` | `polyglav jobs add-supervisor <name> [--interval N | --at ISO | --cron "expr"] [--task "text" | --file path]` - scaffold an approved `leader`-typed supervisor job from the supervisor task template |
| `approve`     | `approve <name>` - activate a job (or arm the next run for `--require-approval` jobs) |
| `daemon`      | `daemon [--tick 15] [--quiet]` - scheduler loop, Ctrl-C to stop           |
| `edit`        | `edit <name>` - open the job's linked task file in `$EDITOR` (creates the template first) |
| `enable` / `disable` / `stop` | Toggle the enabled gate (`stop` = `disable`)                     |
| `list`        | Table of jobs: schedule, status, next and last run                       |
| `reject`      | `reject <name>` - send back to proposed and disable                       |
| `remove`      | `remove <name>` - drop the definition (sessions are kept)                 |
| `run`         | `run <name> [--no-retry] [--verbose]` - run now, apply retries, print the answer. `--verbose` streams the live turn. Exit `0` verified / `1` failed |
| `show`        | `polyglav jobs show <name>` - definition plus full run history + last output|
| `status`      | Runtime summary per job: fired count, last error, uptime, approval state |

### `polyglav fleet`

Supervise a fleet of scoped `polyglav serve` agents: ports, health checks, restart policy, config generation. See [fleet.md](fleet.md).

| Subcommand    | Description                                                                     |
|---------------|---------------------------------------------------------------------------------|
| `add`         | `add <name> [--dir] [--port N] [--max-restarts N]` - add an agent                |
| `config`      | `config <name> --provider/--model/--role/--system-prompt/--mode/--tools-deny/--tool-permission` - write only those keys into `<dir>/.polyglav/config.json` |
| `down`        | Stop the supervised agents and the daemon if running                             |
| `init`        | Scan immediate subdirectories holding `.polyglav/config.json` into the manifest    |
| `logs`        | `logs <name> [n] [--follow]` - tail an agent's `.polyglav/logs/<name>.log`         |
| `remove`      | `remove <name>` - remove an agent (stops it if running)                          |
| `restart`     | `restart [name|all]` - stop, reset restart backoff, relaunch (default: all)     |
| `status`      | Live table: agent, enabled, port, pid, state, restarts, last error               |
| `up`          | `up [--detach]` - start agents. Ctrl-C = graceful down, `--detach` = background daemon |

`--path` may be given before the subcommand (`polyglav --path X fleet status`) or after it (`polyglav fleet --path X status`).

### `polyglav plugins`

Manage plugins headlessly. See [plugins.md](plugins.md).

| Subcommand    | Description                                                     |
|---------------|-----------------------------------------------------------------|
| `disable`     | `polyglav plugins disable <name>` - remove a plugin from the plugins list (applies on next start) |
| `enable`      | `polyglav plugins enable <name>` - add a plugin to the plugins list (applies on next start) |
| `install`     | `polyglav plugins install <git-url\|path> [--global] [--deps]` - install a plugin |
| `list`        | List installed plugins and their load status                    |
| `uninstall`   | `polyglav plugins uninstall <name>` - remove a plugin             |
| `update`      | `polyglav plugins update <name>` - re-fetch from the recorded source |

`--path` may be given before the subcommand (`polyglav --path X plugins list`) or after it (`polyglav plugins --path X list`).
