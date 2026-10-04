# Agent fleets

Polyglav composes into fleets of single-purpose agents, each a full Polyglav process scoped to a directory. A documentation agent owns a folder of PDFs, a code agent stays inside one repository, and a web-research agent has no filesystem access. The zero-dependency core keeps each process small, so many can run on one machine, and thin process and permission boundaries keep them apart.

## One agent = one process = one folder

An agent is `polyglav serve` pointed at a project directory:

```bash
polyglav serve --path docs --port 8781 &
polyglav serve --path src --port 8782 &
```

Each process reads its own `.polyglav/config.json` (provider, model, system prompt, tool permissions, plugins) and writes its own sessions under `.polyglav/sessions/`. Nothing is shared at runtime, so a crash in one agent cannot take down the others and configuration drift stays isolated per agent.

## Responsibilities and permissions

An agent's responsibility comes from its config, namely which tools are registered, and its permission is enforced by the worktree and tool policy, not convention.

- **Worktree scoping**: the tool policy treats the launch directory (`--path`, or the current directory) as the worktree. `file_read` / `list_dir` / `file_write` / `glob` / `grep` on a path outside it escalate from `allow` to `ask` (tools/policy.py:35). A doc agent cannot touch files in another agent's folder unless its config says so.
- **Headless auto-deny**: in `serve`/`run` mode, `ask`-gated tools are denied outright (ui.py `HeadlessUI.confirm` answers `auto == 'allow'`). An agent's reachable surface is exactly `allow` tools on paths inside its worktree, plus `--yes` approvals.
- **Tool allow/deny**: `tools.allow` (whitelist mode) and `tools.deny` narrow the registered schema the model sees. A web agent sets `tools.deny: [run_command, file_write]`, a code agent denies `web_search, web_fetch`.
- **Category permissions**: `tool_permission` (`read`/`list`/`edit`/`bash`/`web` > `allow`/`ask`/`deny`) is per-agent. `bash` defaults to `ask` everywhere, so set `tool_permission.bash: allow` only for agents that may run shell commands.
- **Plugins per agent**: the `plugins` config list controls which plugin set loads in each process. Capabilities needing external dependencies (PDF extraction, MCP, vector search) are external plugins. Scoped ones (folder watching, text indexing) are bundled.

## Example: a documentation agent

A doc agent watches a folder of PDFs, converts new ones to text, indexes them, and answers peers over the API. Decomposed:

| Capability | Home | Dependency |
|---|---|---|
| Folder watching (new-file detection) | internal bundled plugin | stdlib `threading` + `pathlib` |
| Text index over converted files | internal bundled plugin | stdlib |
| PDF > text extraction | external plugin | `pypdf` (lazy import) |
| Vector store / embeddings | external plugin | FAISS/Weaviate (later) |
| MCP server for peer agents | external plugin (planned) | `mcp` (lazy import) |

A minimal agent config (`.polyglav/config.json` in its own directory):

```json
{
  "provider": "ollama",
  "model": "llama3.2",
  "system_prompt": "You are the documentation agent. Convert PDFs to text, keep the index current, and answer questions from the stored docs.",
  "tools.allow": ["glob", "file_read", "file_write", "run_command", "pdf2text", "watch_folder", "search_index"],
  "tool_permission": { "read": "allow", "list": "allow", "edit": "allow", "bash": "allow", "web": "allow" },
  "plugins": ["polyglav-core-fs", "polyglav-core-exec", "polyglav-core-doc-agent"]
}
```

Launch it, and peers talk to it over the same `POST /chat` API used everywhere:

```bash
polyglav serve --path agents/docs --port 8781 &
curl localhost:8781/chat -X POST -d '{"prompt": "What does spec-42.pdf say?", "session": "docs-pool"}'
```

## Supervisor

`polyglav fleet` supervises the agents from the terminal: port allocation, health checks, a restart policy, and per-agent config generation. It is the systemd/Compose-shaped layer for a single host, so Docker is not needed. A fleet root is a directory holding the agents, typically one folder each, with two files in its `.polyglav/`:

- `.polyglav/fleet.json` - the declarative roster. One `AgentDef` per agent: `name`, `dir`, `enabled`, `prefer_port`, `max_restarts` (0 = unlimited), and an optional `command` override (the test seam, real agents use the default `polyglav serve` command)
- `.polyglav/fleet.state.json` - runtime state only (pids, ports, status, restart counts, last error), a snapshot the supervisor writes, never edited by hand

Build and run a fleet:

```bash
polyglav fleet init                    # scan subdirectories holding .polyglav/config.json
polyglav fleet config docs-agent --role research-agent    # generate a config
polyglav fleet add code-agent --dir ../repo --port 8782
polyglav fleet up                      # foreground, Ctrl-C = graceful down
polyglav fleet up --detach             # background daemon (polyglav fleet down stops it)
polyglav fleet status                  # agent/enabled/port/pid/state/restarts/error table
polyglav fleet restart code-agent      # stop, reset backoff, relaunch on next sweep
polyglav fleet logs docs-agent -f      # tail an agent's .polyglav/logs/<name>.log
```

While `up` runs, every sweep (default 2s) the supervisor does:

- **Port allocation** - agents get a free port by bind probe, preferring `prefer_port`, scanning 8780-8890. Edited while running, `add`/`init` take effect on the next sweep
- **Health checks** - a `GET /health` probe (2s timeout). A running agent that fails `unhealthy_threshold` checks (default 2) or whose process exits is treated as a failure
- **Restart policy** - a failed agent is respawned after a backoff that starts at 5s and doubles to a 60s cap. Past `max_restarts` (default 10) the agent goes `crashed` and the supervisor stops touching it until `polyglav fleet restart <name>` (or `enable`, which resets the counter and re-arms it). Setting `enabled: false` in the manifest stops supervision and the agent
- **Graceful down** - Ctrl-C, `polyglav fleet down`, or a `SIGTERM` to the detached daemon sends `SIGINT` to each child (the server's own graceful shutdown), then escalates to `SIGKILL` after a grace period

### Per-agent config generation

`polyglav fleet config <name>` writes only the keys you pass into `<dir>/.polyglav/config.json`, leaving existing keys intact, so an agent gets its personality before its first launch:

```bash
polyglav fleet config code-agent \
  --provider ollama --model llama3.2 --mode write \
  --system-prompt "You implement code." \
  --tools-deny web_search \
  --tool-permission "bash=allow" \
  --role programmer
```

`--role` resolves the role (bundled + global + local registry) and inlines its `system_prompt`, `model`, and `tool_permission` into the generated keys, so the running agent needs no roles registry of its own. An unknown role aborts the write. `--approve-model` pre-approves the model referenced by `--role` or `--model` in the global models registry, so the headless serve agent can use it without prompting. Agent config is user-managed: `polyglav fleet config` is the only intended writer, and a `serve` process has no config-write CLI path today. An engine-level guard making served agents immutable is an open TODO (see TODO).

### Deployment

For a fleet you supervise each `polyglav serve` process with Docker Compose, scaling one service per agent from the repo's `docker-compose.yml.example`. Each service mounts the agent folder, publishes a host-local port, and carries `restart: unless-stopped`, so Compose restarts agents on failure and every agent exposes `GET /health` for monitoring. Full setup is in [deploy.md](deploy.md).
