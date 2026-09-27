# Small business and solo operators

Small companies get the core properties an enterprise pays a lot for: complete audit logging, data on your own machine, and no vendor lock-in, with no IT department required. One process runs on the office PC or a single small server and serves the whole team over the HTTP API. The shared foundation is in [index.md](index.md).

## Why it fits

- **Enterprise-grade logging without the platform**. Every session records messages, tool calls, results, and reasoning. For a small manufacturer that is a ready-made quality and decision trail without buying a quality management system.
- **No lock-in and no licensing burden**. The core has zero external dependencies, is MIT licensed, and works with any OpenAI-compatible provider or a local model. You are never paying per seat or tied to a vendor's pricing.
- **Runs on what you have**. One existing machine hosts the agent, and team members reach it through `polyglav serve` (`POST /chat`, `GET /sessions`) or through the REPL on their own desks.
- **Scope by folder, not by headcount**. Run one agent per function (quality, production, service, admin), each pinned to its own directory and tool set. That discipline replaces a lot of permission administration.

## Fit by use case

- **Small manufacturers and workshops**. Quality documentation, layered process audit checklists, batch and deviation records, and work instructions searchable in plain language. The audit-first design in [enterprise.md](enterprise.md) applies at any scale: start read-only and gate any write.
- **Service businesses**. Recurring client reports, job summaries, and documentation drafted from your own records, with sources cited. `polyglav run` schedules these headlessly and is cron-friendly, so reporting stops eating the week.
- **Consultants and solo operators**. Research, proposal and deliverable drafting, and a complete client-facing paper trail. Sessions double as the project history you can hand over.
- **Startups**. Internal knowledge, onboarding docs, and support and release notes generated from the codebase and history. The developer guide covers team-specific patterns in [developer.md](developer.md).
- **Back office**. Admin queries against spreadsheets and documents, standard letters, and filing summaries, with write actions kept human-approved.

## Gaps and planned

Connectors to typical small-business systems are future work: spreadsheet and CSV querying, point-of-sale and invoicing integrations, and lightweight document management. These track [TODO.md](../../TODO.md). Deployment guidance for a single machine is in [deploy.md](../deploy.md).

## Get started

1. Install once on the office machine with `pip install polyglav`, then run `polyglav serve --path .polyglav` (or your work directory) and install any plugin the business needs.
2. `/connect` to a provider: a hosted OpenAI-compatible endpoint for convenience, or Ollama for a fully on-premise setup.
3. Lock permissions down. Keep `tool_permission.bash: ask` (the default), deny anything unused with `tools.deny`, and keep write tools out of read-only agents.
4. Point people at the API or a REPL session. Every question and answer is on the record in `.polyglav/sessions/`.
