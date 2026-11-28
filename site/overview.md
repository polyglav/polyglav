# Polyglav

**One agent, many heads**

![Polyglav terminal session](polyglav.svg)

Current version: **v0.57.0** (Python >= 3.11, MIT, zero external dependencies)

An agent is a model plus a harness. Polyglav is the harness: a deliberately small, auditable, zero-dependency agentic core. The model plans, the tool registry acts, and a single streaming loop powers an interactive REPL, a headless CLI, and an HTTP API.

Use it at the prompt when you want. Put it on a server and let it work. There is no dashboard to watch and no chat window to keep open. The UI is optional: a terminal, an IDE, a web UI, or another agent can drive it over the CLI, HTTP API, or MCP. Polyglav can create its own roles, teams, and skills, or the caller can define them through the same catalog. Each process is a self-contained agent scoped to one folder, with its own config, model, and tool permissions. Agents compose into larger systems through three orchestration layers. Swarm covers roles, skills, teams, and delegation. Jobs cover scheduled, durable work. Fleet provides a supervisor for many agents. MCP adds cross-tool interoperability.

## Vision

**One runtime, many agents**

Polyglav assembles five replaceable layers around a thin core: access, orchestration, capability, model, and storage. The direction is everything is a plugin: models, tools, skills, sessions, sandboxes, storage, loops, scheduling, and the UI become replaceable plugins, and the REPL itself moves to a plugin. The operator can stay at one prompt when the work needs a person, or leave recurring work running on a server. The `assistant` agent greets you, answers small tasks inline, delegates bigger work to sub-agents or teams, runs recurring work unattended, watches your agents for health, and reports back.

For bigger work the flow is ask, compose, run, continue, operate. The assistant composes a team, runs it stage by stage, and each stage continues from the previous result with its own session. When the work is set up, put it on a server with a schedule and check in later. You can inspect live state with `/status`, the durable tree with `/history --tree`, or pause the active turn with Ctrl-C. Control never jumps into a live run. See [Workflows and usage](reference/usage/workflow.md).

Read the full vision, decisions, and context economics in [Vision](vision.md).

## Current state

- **Core** - one SSE-stream agent loop, multi-provider (Ollama, OpenAI, Groq, Anthropic, OpenCode Zen/Go, any OpenAI-compatible endpoint), tool calling with per-tool permissions and an audit trail, read (plan) and write (work) modes with a durable internal plan and todo, complete append-only session logs, plugins, `polyglav run` + `polyglav serve`
- **Orchestration** - roles, skills, named teams, the `call` tool for a role, a team, or a role-less sibling, the review loop, jobs (cron, interval, one-shot, retries, approvals, run memory, supervisor recipe), fleet (supervisor with ports, health, restart), MCP client and server
- **Sessions** - turn and part logs, `/history` and `/print`, durable history trees, stable per-session ids, `/compact`, Markdown export
- **Latest** - v0.57.0: MCP tool calls now honor per-invocation policy, and `plan_write` labels its activity line with the plan title. The landing page and this overview now share the operating model: a terminal-native worker you can leave running. See [Changelog](changelog.md)
- **Tooling** - bundled plugins for web search, filesystem, shell, edit, git, dev wrappers (test, lint, format), and MCP, all with path-scoped policies. `polyglav eval` runs fixtures through the headless loop and reports tool-use metrics

## Features

- **One agent, many heads** - split an outcome across roles, run them in order, and loop a producer against a reviewer when the work needs it
- **Unattended by design** - run it headless from the CLI, over the HTTP API, on a cron schedule, or as a fleet. Results land in append-only logs and optional webhook reports, with no dashboard to watch
- **The UI is optional** - the REPL, CLI, HTTP API, and MCP expose the same runtime. A web UI, an IDE, or another agent can be the front end while the work keeps running
- **Zero dependencies** - everything is Python standard library. Nothing to audit, no supply chain, no lockfile churn
- **One agent loop** - a single SSE stream per turn powers the REPL, the CLI, and the API
- **Sequential by design** - one context runs at a time. Sub-agents and stages finish in order, and the durable history tree is read-only
- **Local-first** - config and session logs live on your disk. Bring your own provider key, or run fully local
- **Agentic REPL** - a plain `>` input prompt, a mode-colored submitted line, streaming output, dimmed thinking, hidden tool bodies with one-line summaries, markdown-aware rendering, readline history, and tab completion
- **Long-run memory** - read mode writes a durable internal plan and todo under `.polyglav/`, injected every turn, with the plan passed to sub-runs, so a long task keeps its instructions, decisions, role split, and current work across compaction and role switches
- **Permissions** - every tool is gated by `allow` / `ask` / `deny`, with path-scoped confirmation outside your worktree, a bearer token on a non-loopback API bind, and an audit trail in session logs
- **Sessions** - complete append-only turn and part logs, `/history` and `/print`, `/compact`, and Markdown export
- **Roles, skills, and teams** - reusable agents with per-invocation skills, and named pipelines with shared memory and a review loop
- **Plugins** - external repositories register tools, providers, slash commands, services, roles, teams, skills, report delivery, and eval fixtures. Bundled jobs, fleet, and MCP stay opt-in. The core stays zero-dependency

## Development plan

The work packages and milestones live in [Roadmap](roadmap.md). The full task backlog (open work, newest first) is in [Backlog](backlog.md). The current focus is the sequential run control, first-run onboarding, assistant roles, bounded memory, and the fleet control surface. The roadmap is re-ranked against the backlog before each step.

## Reference docs

The detailed reference is organized in the [Reference index](reference/index.md), covering architecture, commands, configuration, providers, tools, security, sessions, jobs, fleet, swarm, plugins, and more.

## Getting started

```bash
curl -fsSL https://raw.githubusercontent.com/polyglav/polyglav/refs/heads/main/install.sh | sh
polyglav
```

The script installs with uv or pipx when available, otherwise pip, and adds pip or Windows readline support when missing. Or use `pipx install polyglav`, then `polyglav`.

On first run, Polyglav welcomes you and asks for your provider, model, mode, project purpose, assistant persona, and whether to keep an output log. Press Enter to accept a default. After that, it can run without you. You can rerun onboarding with `/onboard`, or change the connection later with `/connect` and `/model`.

Or from source:

```bash
git clone https://github.com/polyglav/polyglav.git
cd polyglav
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/polyglav
```

## License

Polyglav is MIT licensed (see the LICENSE file in the repository).
