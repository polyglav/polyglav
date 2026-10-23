# Installing and running Polyglav

Polyglav is a terminal AI agent. This guide covers installation, first-run setup, and the command surfaces. See the [README](README.md) for the overview and features, and [docs/index.md](docs/index.md) for the full reference.

## Requirements

- Python >= 3.11
- No external dependencies (pure standard library)

## Install

With pipx:

```bash
pipx install polyglav
polyglav
```

From source:

```bash
git clone https://github.com/polyglav/polyglav.git && cd polyglav
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/polyglav
```

With pip:

```bash
pip install polyglav
polyglav
```

## First run

On first run, Polyglav welcomes you and asks for the provider, model, mode, project purpose, assistant persona, and whether to keep an output log. Press Enter to accept a default. You can rerun it later with `/onboard`, and change the connection with `/connect` or `/model`.

Tab-complete `/` commands and session names, and navigate history with arrow keys. Open a `"""` or `'''` block to type a multi-line prompt, close it with a matching delimiter on its own line or a blank line, or end a line with `\` to continue on the next line. The framing is stripped and the whole message is sent as one turn. Ctrl-C exits the REPL from anywhere, even inside an open block.

```
Welcome to Polyglav. Let's set up this project together.
...
/ connect ollama
...
/ model gpt-oss:20b-cloud
> Hi
Hello! How can I help you today?
```

## Usage

Polyglav runs the same loop in three ways: interactively in the REPL, headlessly from the CLI, and as an HTTP service. For bigger work the flow is ask, compose, run, remember, report. The assistant composes a team and runs it stage by stage, with each stage continuing from the previous result in its own session. See [docs/usage/workflow.md](docs/usage/workflow.md) for the workflows and patterns.

### REPL

Run `polyglav` with no arguments. Setup and interaction are described in [First run](#first-run).

### CLI

Stream plain text with `--output text` or return JSON. Log tool status and diagnostics to stderr with `--verbose`. Address a persistent session by name with `--session-id <name>`. Tools that require confirmation auto-deny by default. Pass `--yes` to approve them.

```bash
polyglav run --prompt "Hi"
{
  "content": "Hello! How can I help you today?",
  "duration": 7.0,
  "errors": [],
  "model": "gpt-oss:20b-cloud",
  "provider": "ollama",
  "session": "ses_20260814_192251_ab12cd",
  "status": "ok"
  "thinking": null,
  "tool_calls": [],
  "usage": null,
}
```

### API

`polyglav serve` exposes JSON endpoints. `POST /chat {"prompt": "..."}` (optionally with `"session"` to load or create a session by name) returns the same turn result as the CLI.

```bash
polyglav serve &
curl localhost:8787/chat -X POST -d '{"prompt": "Hi"}'
{"content": "Hello! How can I help you today?", "thinking": null, "tool_calls": [], "errors": [], "duration": 7.0, "usage": null, "model": "gpt-oss:20b-cloud", "provider": "ollama", "session": "ses_20260814_192711_ab12cd", "status": "ok"}
```

### Swarm - roles, skills, and teams

A caller agent (or you) hands a task to a specialized role, or runs a named team stage-by-stage. Each sub-agent runs in-process, writes its own session log, and returns its final answer. The REPL shows its dimmed activity and a duration footer while it works. Roles are model- and permission-scoped: a researcher is read-only, a programmer may run shell. A team adds order, per-stage skills, a shared memory file, and an optional review loop.

```
>>> /roles list
>>> /tool call {"target": "researcher", "task": "Summarize docs/ and cite sources"}
[call researcher] <final answer of the research sub-agent, sources cited>
>>> /tool call {"target": "writing", "kind": "team", "task": "Draft the release notes"}
[call writing] <final stage answer>
```

See [docs/swarm.md](docs/swarm.md), [docs/teams.md](docs/teams.md), and [docs/roles.md](docs/roles.md).

### Jobs - scheduled durable work

Jobs are user-gated workflows: `add` proposes, `approve` arms it, and the daemon fires it on schedule. The task lives in a Markdown file edited in `$EDITOR`. A rolling memory summary carries context between runs.

```bash
polyglav jobs add nightly --file tasks/nightly.md --cron "0 2 * * *"
polyglav jobs approve nightly
polyglav jobs daemon            # polls on --tick 15s, Ctrl-C to stop
polyglav jobs status
```

See [docs/jobs.md](docs/jobs.md).

### Fleet - supervised agents

One agent per folder, each a `polyglav serve` process with its own config, permissions, and sessions.

```bash
polyglav fleet init                                              # scan existing agent folders
polyglav fleet config docs-agent --role researcher --port 8781
polyglav fleet up                                                # Ctrl-C = graceful down, or --detach
polyglav fleet status
polyglav fleet logs docs-agent -f
```

See [docs/fleet.md](docs/fleet.md).

### MCP - interop with other AI tools

```bash
polyglav mcp    # stdio MCP server: serve Polyglav's tools/sessions or import another server's tools, e.g. point Claude or opencode at it
```

On `polyglav serve`, the same is available at `POST /mcp`. See [docs/mcp.md](docs/mcp.md).

## Docker

The repo ships a `Dockerfile`, `polyglav-entrypoint.sh`, and a `docker-compose.yml.example` for running one container per agent. The image runs `polyglav serve` and reads `POLYGLAV_HOST`, `POLYGLAV_PORT`, and `POLYGLAV_PATH` from the environment.

```bash
docker build -t polyglav .
```

See [docs/deploy.md](docs/deploy.md) for the full deployment guide and the Compose fleet template.

## Plugins

External repositories register tools, providers, slash commands, services, roles, teams, skills, and eval fixtures without changing the core. Install with `/plugins install <git-url|path>` or `polyglav plugins install`. Bundled plugins cover web search, filesystem, shell, edit, git, dev wrappers, and the vendor providers. See [docs/plugins.md](docs/plugins.md).

## Troubleshooting

### tmux shows `python` in the window name

tmux reads the foreground process name, and an installed console script still runs the Python interpreter, so the window can show `python` instead of `polyglav`. Until a process-title fix lands, rename the window with `Ctrl-b ,` or turn off automatic renaming for that window with `set-window-option automatic-rename off`.
