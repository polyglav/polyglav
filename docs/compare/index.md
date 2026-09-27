# Polyglav comparisons

Polyglav is an agent **harness**: a runtime with the agent loop already built in. Projects in the space fall into four categories, depending on how much of the loop they give you and how you build with them.

| Category | What it is | You provide | Page |
|----------|------------|-------------|------|
| Harness | A runtime with the loop built in | instructions and tools | [harness.md](harness.md) |
| Framework | A library to build an agent | the control flow | [framework.md](framework.md) |
| Low-code | A visual canvas that generates code | flows, with code for custom parts | [lowcode.md](lowcode.md) |
| No-code | A turnkey product you configure | nothing, or prompts | [nocode.md](nocode.md) |

Polyglav sits in the harness category, with a clear angle: a zero-dependency, standard-library core that covers the full harness and the orchestration around it, stays configurable as data, and runs anywhere Python runs.

## Why Polyglav

- **Complete harness**: loop, tools, permissions, sessions, delegation, teams, jobs, and a fleet supervisor in one package.
- **Zero external dependencies**: the whole runtime is Python standard library, so it is small, portable, and easy to audit.
- **One loop, three surfaces**: a REPL, a headless CLI, and an HTTP API from the same code path.
- **Orchestration included**: types, the `delegate` and `team` tools, scheduled jobs, and a fleet supervisor, without extra infrastructure.
- **Configuration as data**: models, providers, tools, types, teams, skills, and permissions are editable, versionable, and plugin-extensible.
- **Local-first and provider-agnostic**: run fully local or bring any OpenAI-compatible provider, with complete session logs.

## Who is covered

| Project | Category | File |
|---------|----------|------|
| Aider | Harness | [harness.md](harness.md) |
| AutoGen | Framework | [framework.md](framework.md) |
| AutoGPT platform | No-code | [nocode.md](nocode.md) |
| Claude Code | Harness | [harness.md](harness.md) |
| Cline | Harness | [harness.md](harness.md) |
| Codex | Harness | [harness.md](harness.md) |
| CrewAI | Framework | [framework.md](framework.md) |
| Dify | Low-code | [lowcode.md](lowcode.md) |
| Flowise | Low-code | [lowcode.md](lowcode.md) |
| Hermes | Harness | [harness.md](harness.md) |
| Hosted assistants | No-code | [nocode.md](nocode.md) |
| LangChain | Framework | [framework.md](framework.md) |
| Langflow | Low-code | [lowcode.md](lowcode.md) |
| LangGraph | Framework | [framework.md](framework.md) |
| LlamaIndex | Framework | [framework.md](framework.md) |
| Microsoft Agent Framework | Framework | [framework.md](framework.md) |
| n8n | Low-code | [lowcode.md](lowcode.md) |
| Open WebUI | No-code | [nocode.md](nocode.md) |
| OpenClaw | Harness | [harness.md](harness.md) |
| OpenCode | Harness | [harness.md](harness.md) |
| OpenHands | Harness | [harness.md](harness.md) |
| Pi | Harness | [harness.md](harness.md) |

## How to choose

1. **How much do you want to build?** A harness runs out of the box, a framework is code you write, low-code is a canvas plus code, and no-code is a UI you configure.
2. **Where does it run?** Polyglav is a local process or a small HTTP service. Hosted assistants are cloud-only. Some harnesses need Node.js, Bun, or Docker.
3. **Who operates it?** A developer is comfortable with a terminal and text configuration. A mixed team often prefers a visual canvas. A non-developer wants a chat UI.
4. **What has to persist?** Polyglav keeps append-only session logs and bounded memory. Frameworks bring pluggable checkpointers. Chat UIs keep conversation history.
5. **How much isolation?** Polyglav gates tools with `allow` / `ask` / `deny` and records an audit trail. Some harnesses add container or micro-VM isolation.

## References

- https://github.com/polyglav/polyglav
- https://github.com/polyglav/polyglav/tree/main/docs
