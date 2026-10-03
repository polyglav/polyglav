# Polyglav Documentation

Detailed reference for Polyglav. For the overview and features see the [README](../README.md), and for installation and usage see [INSTALL.md](../INSTALL.md).

- [Agent fleets](fleet.md) - single-purpose agent fleets, one scoped process per agent, deployment
- [Agent swarms](swarm.md) - swarm orchestration, delegation, types, auditor and team patterns
- [Roles](roles.md) - role catalog, storage, delegation and permission rule
- [API endpoints](api.md) - HTTP JSON API for `polyglav serve`
- [Architecture](architecture.md) - agent core: the loop, engine, UI sinks, front-ends, extension points
- [Commands & CLI](commands.md) - slash commands and headless CLI flags
- [Compare](compare/) - category-driven comparisons: harness, framework, low-code, no-code
- [Configuration](config.md) - config schema and keys
- [Deployment](deploy.md) - Docker deployment (image + Compose fleet)
- [Eval harness](eval.md) - tool-use evaluation (`polyglav eval`), task fixtures, metrics
- [Jobs](jobs.md) - scheduled and durable jobs (`polyglav jobs`), cron scheduling, approvals
- [Memory](memory.md) - bounded role, team, and job memory, automatic and manual
- [Model Context Protocol](mcp.md) - MCP client and server
- [Modes and access](modes.md) - read/write posture, access classification, the mode cap
- [Plugins](plugins.md) - bundled, layout, manifest, management
- [Providers](providers.md) - providers, auto-detection, the chat event contract, adding a provider
- [Security](security.md) - permission model, threat model, data posture, prompt injection
- [Sessions](session.md) - session log format, message schema, compaction, persistence
- [Skills](skills.md) - skill registry, storage, type injection
- [Testing](testing.md) - running the mock test suite, per-file coverage map
- [Tools](tools.md) - tool registry, bundled tools, tool policy, registration metadata
- [Usage](usage/programming.md) - step-by-step setup variations
- [Use cases](use-cases/) - audience guides: developer, education, enterprise, home lab, personal, research, small business
- [Workflows and usage](usage/workflow.md) - how work flows from a request to a result, and common patterns
- [Writing tools for agents](writing-tools.md) - how to design, name, and describe tools for the agent loop
