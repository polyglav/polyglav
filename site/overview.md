# Polyglav

**One agent, many heads**

Current version: **v0.37.0** (Python >= 3.10, MIT, zero external dependencies)

An agent is a model plus a harness. Polyglav is the harness: a deliberately small, auditable, zero-dependency agentic core. The model plans, the tool registry acts, and a single streaming loop powers an interactive REPL, a headless CLI, and an HTTP API. Each process is a self-contained agent scoped to one folder, with its own config, model, and tool permissions. Agents compose into larger systems through three orchestration layers. Swarm covers types, skills, teams, and delegation. Jobs cover scheduled, durable work. Fleet provides a supervisor for many agents. MCP adds cross-tool interoperability.

## Vision

**One runtime, many agents**

Polyglav assembles five replaceable layers around a thin core: access, orchestration, capability, model, and storage. The direction is everything is a plugin: models, tools, skills, sessions, sandboxes, storage, loops, scheduling, and the UI become replaceable plugins, and the REPL itself moves to a plugin. The operator sees one window: the `assistant` agent greets you, answers small tasks inline, delegates bigger work to sub-agents or teams, runs recurring work in the background, watches your agents for health, and reports back.

For bigger work the flow is ask, compose, run, hand off, remember, report. The assistant composes a team, runs it stage by stage, and hands control between agents as phases change, while you watch, stay out, or jump into any run. See [Workflows and usage](reference/usage/workflow.md).

Read the full vision, decisions, and context economics in [Vision](vision.md).

## Current state

- **Core** - one SSE-stream agent loop, multi-provider (Ollama, OpenAI, Groq, Anthropic, OpenCode Zen/Go, any OpenAI-compatible endpoint), tool calling with per-tool permissions and an audit trail, plan/build modes, complete append-only session logs, plugins, `polyglav run` + `polyglav serve`
- **Orchestration** - swarm (types, skills, named teams, the `team` tool, the review loop, the `assistant` root and `composer`), jobs (cron/interval/one-shot, retries, approvals, run memory, supervisor recipe), fleet (supervisor with ports, health, restart), MCP client and server
- **Sessions** - turn/part logs, `/history` and `/print`, stable per-session ids, `/compact`, Markdown export
- **Latest** - v0.33: the session turn cutover, `/history` and `/print`, stable session ids and coded session names, `/focus` and `handoff`, `focus_on_delegate`. See [Changelog](changelog.md)
- **Tooling** - bundled plugins for web search, filesystem, shell, edit, git, and dev wrappers (test/lint/format), all with path-scoped policies. `polyglav eval` runs fixtures through the headless loop and reports tool-use metrics

## Features

- **Zero dependencies** - everything is Python standard library. Nothing to audit, no supply chain, no lockfile churn
- **One agent loop** - a single SSE stream per turn powers the REPL, the CLI, and the API
- **Local-first** - config and session logs live on your disk. Bring your own provider key, or run fully local
- **Agentic REPL** - streaming output, dimmed thinking, markdown-aware rendering, readline history, tab completion
- **Permissions** - every tool is gated by `allow` / `ask` / `deny`, with path-scoped confirmation outside your worktree and an audit trail in session logs
- **Sessions** - complete append-only turn/part logs, `/history` and `/print`, `/compact`, and Markdown export
- **Roles, skills, and teams** - reusable agents with per-invocation skills, and named pipelines with shared memory and a review loop
- **Plugins** - external repositories register tools, providers, slash commands, services, types, teams, skills, and eval fixtures. The core stays zero-dependency

## Development plan

The work packages and milestones live in [Roadmap](roadmap.md). The full task backlog (open work, newest first) is in [Backlog](backlog.md). The current priority is the runs, focus, and memory redesign: run-owned sessions, focus that only navigates, handoff between runs, bounded memory per role/team/job, and non-blocking runs with live focus. The assistant governance track follows.

## Reference docs

The detailed reference is organized in the [Reference index](reference/index.md), covering architecture, commands, configuration, providers, tools, security, sessions, jobs, fleet, swarm, plugins, and more.

## Getting started

```bash
pipx install polyglav
polyglav
```

Or from source: `git clone https://github.com/polyglav/polyglav.git && cd polyglav`, then `python3 -m venv .venv && .venv/bin/pip install -e . && .venv/bin/polyglav`. First-time setup with `/connect`, then type any message.

## License

Polyglav is MIT licensed (see the LICENSE file in the repository).
