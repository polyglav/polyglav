# No-code

A **no-code** tool is turnkey: you install it or open it, configure agents and prompts through a UI, and use it without writing any code. You do not design a flow or write a plugin. You pick a model, give instructions, and go.

## Polyglav is approachable and keeps you in control

Polyglav is a terminal harness, and it is designed to feel simple from the first keystroke. The `assistant` root is a single conversational entry point: it introduces itself on first run, answers small tasks inline, and takes on bigger work by delegating to sub-agents and teams. You talk to one assistant, and the machinery stays out of sight.

For users who want control, Polyglav stays open and local. Everything runs on your machine, the configuration is plain text, and every action is recorded in an auditable session log. That is the trade no-code products cannot offer: the same friendly conversation, but with a self-hosted, inspectable, scriptable runtime behind it.

## Representatives

| Project | Language / stack | License | Configuration | Primary focus |
|---------|------------------|---------|---------------|---------------|
| AutoGPT platform | Python + TypeScript | Open source | Visual blocks and marketplace | Hosted or self-hosted autonomous agents |
| Hosted assistants (ChatGPT, Claude, Gemini) | Closed | Commercial | Chat and settings | General-purpose consumer assistants |
| Open WebUI | Python + TypeScript | Open source | Web UI and settings | Self-hosted chat over local and remote models |
| Polyglav | Python (stdlib only) | MIT | Text files, commands, and the `assistant` | Runnable agent harness with orchestration |

## Profiles

### AutoGPT platform
An autonomous agent platform with a visual block builder, an agent marketplace, and both hosted and self-hosted options. It makes agent building accessible while still exposing blocks for customization.

### Hosted assistants
ChatGPT, Claude, and Gemini are the most-used no-code agents: a chat box, a model picker, and settings. They are polished, hosted, and instantly available, with the model provider operating the service.

### Open WebUI
A self-hosted chat interface over local models and OpenAI-compatible endpoints, with model management, retrieval, and extensions. It brings the hosted chat experience to your own machine.

## Why teams choose Polyglav

- A conversational entry point: the `assistant` root makes the harness approachable, with one point of contact.
- Self-hosted and local-first: configuration and logs stay on your disk, with no cloud dependency.
- Auditable: every prompt, tool call, and result is persisted in a session log.
- Configurable as text: reshape the agent, its tools, teams, and permissions without touching a UI.
- Deployable: run it interactively in a terminal, script it from the CLI, or expose it over HTTP.

## When to choose

| Scenario | Pick | Why |
|----------|------|-----|
| A non-developer wants a chat assistant with no setup code | Hosted assistants, Open WebUI | Turnkey UI, model picker, prompts |
| A self-hosted chat front-end over local models | Open WebUI | Local-first UI over local and compatible APIs |
| An accessible agent builder with blocks | AutoGPT platform | Visual blocks and a marketplace |
| A conversational assistant backed by an auditable, scriptable runtime | Polyglav | `assistant` root plus a local, inspectable core |

## References

- https://chatgpt.com
- https://claude.ai
- https://gemini.google.com
- https://github.com/polyglav/polyglav
- https://github.com/open-webui/open-webui
- https://github.com/Significant-Gravitas/AutoGPT
