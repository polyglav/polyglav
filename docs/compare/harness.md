# Harness

An **agent harness** is the runtime that turns a language model into an agent that can act: the execution loop, tool dispatch, context management, state and memory, permissions, and observability. You bring a model and instructions, and the harness runs the loop. This is the category Polyglav belongs to.

## Polyglav is a complete harness

Polyglav covers the whole harness in one small, self-contained package. It has the loop, a rich tool set, path-scoped permissions, complete session logs, delegation, teams, scheduled jobs, and a fleet supervisor, all in the Python standard library. There is nothing to compile and nothing to install beyond Python itself, so Polyglav runs anywhere Python runs, from a workstation to a small edge device.

Polyglav is also extensively configurable without code changes. Models, tools, providers, roles, teams, skills, and eval fixtures are all data, registered through files and plugins. You can reshape the agent, its tools, its permissions, and its orchestration from configuration, and keep every change in version control.

## Representatives

| Project | Language | License | Native tools | Multi-agent | Scheduling | Channels |
|---------|----------|---------|--------------|-------------|------------|----------|
| Aider | Python | Apache-2.0 | File edit, git-native | No | No | Terminal |
| Claude Code | TypeScript | Source-available | Read, write, edit, bash, web | Subagents | Routines, desktop tasks | Terminal, IDE, desktop, web, mobile |
| Cline | TypeScript | Apache-2.0 | Plan/Act, checkpoints | Parallel agents | No | IDE, CLI, SDK |
| Codex | Rust | Apache-2.0 | Terminal-native, sandboxed exec | Limited | No | Terminal, cloud |
| Hermes | Python + Node.js | Open source | Broad tool set, memory, skills | Isolated subagents | Cron with delivery | Many messaging channels, desktop, web |
| OpenClaw | TypeScript | Open source | Gateway tools, browser | ACP child sessions | Cron tools | Many messaging channels, web UI |
| OpenCode | TypeScript + Bun | Open source | File, bash, glob/grep, MCP | Child sessions | No | Terminal, desktop, IDE |
| OpenHands | Python | MIT | Rich tool set, apply_patch | Parallel conversation trees | No | Web UI, CLI |
| Pi | TypeScript + Bun | MIT | read, write, edit, bash | Extensions | No | Terminal |
| Polyglav | Python (stdlib only) | MIT | Web, file, edit, git, shell, dev wrappers | Types, delegate, teams, fleet | Jobs (cron/interval/one-shot) | Terminal, CLI, HTTP API, MCP |

## Profiles

### Aider
A terminal pair-programming agent with a git-native workflow. It maps the repository, edits files, and keeps changes in git, so it fits developers who live in the terminal and want commit-by-commit control.

### Claude Code
Anthropic's coding agent shared across terminal, IDE, desktop, web, and mobile surfaces. It brings subagents, skills, hooks, MCP, and cross-session memory to a polished, Claude-first experience.

### Cline
An IDE extension, CLI, and SDK with a plan/act split, checkpoints, and a Kanban view for parallel agents. It is built for editor-centric coding across many providers.

### Codex
OpenAI's Rust coding agent with terminal-native and cloud surfaces, sandboxed execution, and MCP. It integrates tightly with OpenAI models and ChatGPT plans.

### Hermes
Nous Research's personal agent with persistent memory, a learning loop that grows skills, multi-channel messaging, and remote or serverless execution backends. It is built to remember you and improve over time.

### OpenClaw
A self-hosted gateway that connects many messaging channels to agents and routes coding to external harnesses. It is strongest as an always-on assistant that meets you where you already chat.

### OpenCode
A full-featured open-source coding agent with a rich terminal UI, desktop and IDE surfaces, broad provider support, and a plugin SDK. It is a polished coding platform.

### OpenHands
A Python software-engineering agent with container sandboxing, a web UI, and parallel conversation trees. It offers strong isolation and a generous tool set for engineering tasks.

### Pi
A minimal, self-extensible TypeScript harness with a unified LLM API, a terminal UI, telemetry, and standalone binaries. It starts small and grows into exactly what you need.

## Why teams choose Polyglav

- Zero external dependencies and a standard-library core, so the entire runtime is easy to audit and there is no supply chain to track.
- One loop behind a REPL, a CLI, and an HTTP API, so the same agent is interactive, scriptable, and deployable as a service.
- Orchestration built in: types, delegation, teams, scheduled jobs, and a fleet supervisor, ready without extra infrastructure.
- Configuration as data: models, tools, providers, types, teams, skills, and permissions are all editable, versionable, and plugin-extensible.
- Local-first and provider-agnostic: run fully local or bring any OpenAI-compatible provider.

## When to choose

| Scenario | Pick | Why |
|----------|------|-----|
| A small, auditable core you own and embed | Polyglav | Stdlib-only Python, REPL, CLI, and HTTP API from one loop |
| Many scoped agents under one supervisor, with scheduling | Polyglav | Fleet supervisor, jobs, and teams built in |
| A polished coding agent across IDE, desktop, and web | Claude Code, OpenCode, Cline | Rich surfaces and editor integration |
| An always-on assistant reachable from messaging apps | OpenClaw, Hermes | Multi-channel gateways and companion apps |
| A memory and skill learning loop that improves over time | Hermes | Persistent memory, skills, and a user profile |
| Strong isolation with a ready sandbox | OpenHands, Hermes, Pi | Container or micro-VM backends |
| A minimal runtime you extend with packages | Pi | Everything is an extension |

## References

- https://aider.chat
- https://github.com/anomalyco/opencode
- https://github.com/anthropics/claude-code
- https://github.com/cline/cline
- https://github.com/earendil-works/pi
- https://github.com/polyglav/polyglav
- https://github.com/All-Hands-AI/OpenHands
- https://github.com/NousResearch/hermes-agent
- https://github.com/openai/codex
- https://github.com/openclaw/openclaw
