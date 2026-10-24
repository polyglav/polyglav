# Polyglav

**One agent, many heads**

![Polyglav terminal session](polyglav.svg)

Current version: **v0.48.0** (Python >= 3.11, MIT, zero external dependencies)

An agent is a model plus a harness. Polyglav is the harness: a deliberately small, auditable, zero-dependency agentic core. The model plans, the tool registry acts, and a single streaming loop powers an interactive REPL, a headless CLI, and an HTTP API. Each process is a self-contained agent scoped to one folder, with its own config, model, and tool permissions. Agents compose into larger systems through three orchestration layers. Swarm covers roles, skills, teams, and delegation. Jobs cover scheduled, durable work. Fleet provides a supervisor for many agents. MCP adds cross-tool interoperability.

## Vision

**One runtime, many agents**

Polyglav assembles five replaceable layers around a thin core: access, orchestration, capability, model, and storage. The direction is everything is a plugin: models, tools, skills, sessions, sandboxes, storage, loops, scheduling, and the UI become replaceable plugins, and the REPL itself moves to a plugin. The operator sees one window: the `assistant` agent greets you, answers small tasks inline, delegates bigger work to sub-agents or teams, runs recurring work unattended, watches your agents for health, and reports back.

For bigger work the flow is ask, compose, run, remember, report. The assistant composes a team, runs it stage by stage, and each stage continues from the previous result with its own session. You can watch, read the run tree with `/runs`, or pause and resume at the next turn boundary. Control never jumps into a live run. See [Workflows and usage](reference/usage/workflow.md).

Read the full vision, decisions, and context economics in [Vision](vision.md).

## Current state

- **Core** - one SSE-stream agent loop, multi-provider (Ollama, OpenAI, Groq, Anthropic, OpenCode Zen/Go, any OpenAI-compatible endpoint), tool calling with per-tool permissions and an audit trail, read (plan) and write (work) modes with a durable internal plan and todo, complete append-only session logs, plugins, `polyglav run` + `polyglav serve`
- **Orchestration** - roles, skills, named teams, the `call` tool for a role, a team, or a role-less sibling, the review loop, jobs (cron, interval, one-shot, retries, approvals, run memory, supervisor recipe), fleet (supervisor with ports, health, restart), MCP client and server
- **Sessions** - turn and part logs, `/history` and `/print`, `/runs` tree and buffers, stable per-session ids, `/compact`, Markdown export
- **Latest** - v0.48.0: plan and todo bookkeeping in read mode with a durable plan under `.polyglav/plans/`, a current-work todo under `.polyglav/todos/`, `/plan`, `/plans`, `/todo`, and `/todos`, bounded injection across turns and sub-runs, and plan and work mode descriptions with `/modes --verbose`. See [Changelog](changelog.md)
- **Tooling** - bundled plugins for web search, filesystem, shell, edit, git, dev wrappers (test, lint, format), and MCP, all with path-scoped policies. `polyglav eval` runs fixtures through the headless loop and reports tool-use metrics

## Features

- **Zero dependencies** - everything is Python standard library. Nothing to audit, no supply chain, no lockfile churn
- **One agent loop** - a single SSE stream per turn powers the REPL, the CLI, and the API
- **Sequential by design** - one context runs at a time. Sub-agents and stages finish in order, and `/runs` is a read-only history tree
- **Local-first** - config and session logs live on your disk. Bring your own provider key, or run fully local
- **Agentic REPL** - a plain `_` input prompt, a mode-colored `>` or magenta `/` submitted line, streaming output, dimmed thinking, hidden tool bodies with one-line summaries, markdown-aware rendering, readline history, and tab completion
- **Long-run memory** - read mode writes a durable internal plan and todo under `.polyglav/`, injected every turn and passed to sub-runs, so a long task keeps its instructions, decisions, role split, and current work across compaction and role switches
- **Permissions** - every tool is gated by `allow` / `ask` / `deny`, with path-scoped confirmation outside your worktree and an audit trail in session logs
- **Sessions** - complete append-only turn and part logs, `/history` and `/print`, `/compact`, and Markdown export
- **Roles, skills, and teams** - reusable agents with per-invocation skills, and named pipelines with shared memory and a review loop
- **Plugins** - external repositories register tools, providers, slash commands, services, roles, teams, skills, and eval fixtures. The core stays zero-dependency

## Development plan

The work packages and milestones live in [Roadmap](roadmap.md). The full task backlog (open work, newest first) is in [Backlog](backlog.md). The current focus is the sequential run control, first-run onboarding, assistant roles, bounded memory, and the fleet control surface. The roadmap is re-ranked against the backlog before each step.

## Reference docs

The detailed reference is organized in the [Reference index](reference/index.md), covering architecture, commands, configuration, providers, tools, security, sessions, jobs, fleet, swarm, plugins, and more.

## Getting started

```bash
pipx install polyglav
polyglav
```

On first run, Polyglav welcomes you and asks for your provider, model, mode, project purpose, assistant persona, and whether to keep an output log. Press Enter to accept a default. You can rerun it with `/onboard`, or change the connection later with `/connect` and `/model`.

Or from source: `git clone https://github.com/polyglav/polyglav.git && cd polyglav`, then `python3 -m venv .venv && .venv/bin/pip install -e . && .venv/bin/polyglav`.

## License

Polyglav is MIT licensed (see the LICENSE file in the repository).
