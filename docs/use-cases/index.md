# Use cases

Polyglav is deliberately small: a zero-dependency agentic core with one streaming loop, scoped per-process agents, and an append-only session log. That makes it a strong orchestration, analysis, and assistant layer above existing systems, not a replacement for the deterministic systems that run production (SCADA, PLC, MES, ERP, quality and maintenance systems). The recurring conclusion across the research is consistent: start read-only, keep humans in the loop for anything that writes or controls, and grow autonomy in bounded steps.

The audience guides in this folder assess how that core fits a specific context. This page holds the shared foundation they all build on.

## Audience guides

| Guide | Context | File |
|-------|---------|------|
| Developer | Coding assistants and engineering teams | [developer.md](developer.md) |
| Education | Teaching, tutoring, and course preparation | [education.md](education.md) |
| Enterprise | Regulated industries, extension requirements, audit advantage | [enterprise.md](enterprise.md) |
| Home lab | Makers, self-hosters, and personal servers | [homelab.md](homelab.md) |
| Personal | Private and personal use, local models, privacy-first | [personal.md](personal.md) |
| Research | Academia and sensitive research data | [research.md](research.md) |
| Small business | Small companies, solo operators, and startups | [small-business.md](small-business.md) |

## What Polyglav provides today

These capabilities exist now and form the foundation any evaluation builds on:

- **Auditability by design**. Every session is a complete, append-only log. Each message, tool call with its result, reasoning (`thinking`), and error is persisted with timestamps, duration, model, and provider, and every tool permission decision is recorded in the session `permissions` array. Entries are never removed. Compaction only trims the provider context, never the log. See [session.md](../session.md).
- **Zero-dependency core**. Python standard library only. Nothing to audit and no supply chain. In a regulated environment this is a supply-chain and security property, not just a convenience.
- **Local-first data sovereignty**. Config and session logs live on your disk, and all provider traffic is outbound. No external logging or telemetry service holds your data.
- **Permissions and isolation**. Every tool is gated by `allow` / `ask` / `deny`, with path-scoped confirmation for anything outside an agent's worktree. Headless agents auto-deny anything that would require confirmation, so an agent's reachable surface is exactly what its config allows.
- **Fleet shape**. One process per single-purpose agent, each scoped to its own folder, config, model, and tool permissions. The small per-process footprint lets many focused agents run on one machine. See [fleet.md](../fleet.md).
- **Headless modes**. `polyglav run` for scripting and CI/CD, and `polyglav serve` for an HTTP JSON API (`POST /chat`, `GET /sessions`, `GET /health`, `GET /version`). Agents talk to each other over the same API.
- **Plugin-first extensibility**. External repositories register tools, providers, commands, and services without touching the core. Plugin dependencies are imported lazily, so the stdlib-only guarantee holds. See [plugins.md](../plugins.md).
- **Multi-provider**. Ollama, OpenAI, Groq, Anthropic, and any OpenAI-compatible endpoint, with auto-detection from the base URL. Local models keep confidential data in-house.

## Adoption path

The same phased path recurs across the research and applies to any context, from a single personal machine to a regulated plant:

1. **Read-only copilot**. Document search, KPI queries, shift and day reporting, alarm and fault analysis. Success criteria are faster reporting and traceable sources, with no write access to target systems.
2. **Workflow assistant**. Draft tickets and work orders, prepare deviation records, create plan variants, and trigger notifications. All writes require user approval.
3. **Bounded autonomy**. Escalate defined alarms, raise work orders under safe criteria, propose batch holds, and execute controlled non-safety-critical actions. Only after validation, and only through a permission and approval chain.
4. **Fleet-wide platform**. Fleet orchestration, unified connectors and agent packages, edge capability, cross-site benchmarks, and central compliance and audit evaluation.

## Reference architecture

A production-grade deployment composes three layers. Polyglav is the agent runtime in the middle. Enterprise functions are separate services around it rather than logic baked into the core. Smaller deployments skip most of this and run one or a few agents.

```text
Users / shift lead / web / TUI / API
                 |
        Identity & Policy Layer
                 |
        Polyglav Control Plane
   Sessions | Agents | Approvals | Audit
                 |
       Agent Orchestrator / Workflow
                 |
        Tool Gateway / MCP Gateway
                 |
  ----------------------------------------
  MES | ERP | SCADA | Historian | LIMS
  CMMS | DMS | Monitoring | Planning
  ----------------------------------------
                 |
        Event Bus and Data Platform
                 |
      Edge Nodes / Plant Gateways
```

- **Control plane**. Agents, configuration, policies, tool approvals, versions, and deployments. Agents must never be able to change their own configuration, permissions, or tool list.
- **Data plane**. Production data, documents, events, tool execution, and local connectors.
- **Fleet and swarm**. [fleet.md](../fleet.md) and [swarm.md](../swarm.md) describe the two composable layers: a fleet of scoped `polyglav serve` processes, and a swarm of cooperating agents (types, `delegate`, auditors) that runs on top of the fleet or in-process. For enterprise use the research recommends a bounded, hierarchical multi-agent system, with a coordinator delegating to specialized agents that have clear responsibilities, minimal tool sets, and defined output formats, rather than a freely communicating swarm.
- **Human-in-the-loop**. Write and control actions flow through `propose -> policy check -> human approval -> execute -> verify -> audit`, so "autonomous agents" become an auditable business process.
