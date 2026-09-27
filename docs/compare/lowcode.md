# Low-code

A **low-code** tool gives you a visual canvas for building AI or automation flows, and lets you drop into code for the parts that need it. You assemble nodes, connect them, and the platform runs the result, often exposing it as an API. It is the middle ground between a framework (all code) and a no-code product (no code).

## Polyglav is code-first, with a path to visual

Polyglav takes the code-first route and makes it a strength. Every configuration, from models and providers to tools, roles, teams, and skills, is text you can read, diff, review, and keep in version control alongside your project. That means reproducible setups, clean reviews, and no hidden state in a database.

The composition model is the registries: define types with their own prompts and permission carves, compose teams with per-stage skills and a review loop, and run them from a prompt, a slash command, or the CLI. This covers the same ground as a canvas while staying scriptable.

Polyglav also meets the visual tools halfway. A planned PlantUML plugin draws a configuration or a run as a node diagram, so you get the readability of a canvas without moving the runtime into one. The agents, teams, and workflows stay text, and the picture is generated from them.

## Representatives

| Project | Language | License | Building style | Primary focus |
|---------|----------|---------|----------------|---------------|
| Dify | Python + TypeScript | Open source | Visual workflow canvas | LLM app development and backend-as-a-service |
| Flowise | TypeScript | Open source | Drag-and-drop canvas | LLM apps and chatflows |
| Langflow | Python | MIT | Visual flow canvas | Agent, RAG, and MCP app builder |
| n8n | TypeScript | Fair-code | Node-based workflow editor | Workflow automation with AI agent nodes |
| Polyglav | Python (stdlib only) | MIT | Code and configuration | Runnable agent harness with orchestration |

## Profiles

### Dify
An open-source platform for building LLM applications with a visual workflow editor and a backend-as-a-service layer. It helps teams ship LLM apps and agents with observability and a managed API.

### Flowise
A drag-and-drop builder for LLM apps and chatflows. It is approachable for prototyping assistants and retrieval chains, with a friendly canvas.

### Langflow
A visual builder for agents, RAG apps, and MCP servers that generates Python under the hood. It offers a large component library and flow-as-API deployment.

### n8n
A fair-code workflow automation platform with a node editor and a deep integration catalog. It is strongest at wiring business systems together with AI agent nodes.

## Why teams choose Polyglav

- Configuration as versioned text: reviewable, reproducible, and friendly to git-based workflows.
- Scriptable and automatable: drive the same agent from a prompt, a slash command, the CLI, or the HTTP API.
- Orchestration as configuration: types, teams, skills, and a review loop without a canvas or a database.
- A path to visuals: the PlantUML plugin renders configurations and runs as node diagrams.
- Zero external dependencies, so the runtime stays small and portable.

## When to choose

| Scenario | Pick | Why |
|----------|------|-----|
| A visual flow a mixed team can read and edit | Langflow, n8n, Dify, Flowise | Canvas, prebuilt components, flow-as-API |
| Broad integration with business apps and triggers | n8n | Deep integration catalog and templates |
| Configuration you version and review with the project | Polyglav | Text registries, session logs, git-friendly setup |
| Running many scoped agents on modest hardware | Polyglav | Minimal footprint and a fleet supervisor |

## References

- https://docs.dify.ai
- https://docs.flowiseai.com
- https://docs.langflow.org
- https://docs.n8n.io
- https://github.com/polyglav/polyglav
