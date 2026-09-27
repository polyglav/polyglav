# Enterprise fit

Polyglav is deliberately small: a zero-dependency agentic core with one streaming loop, scoped per-process agents, and an append-only session log. That makes it a strong **orchestration, analysis, and assistant layer** above existing systems. It complements the deterministic systems that run production (SCADA, PLC, MES, ERP, quality and maintenance systems) rather than replacing them. The recurring conclusion across the research is consistent: start read-only, keep humans in the loop for anything that writes or controls, and grow autonomy in bounded steps.

This guide covers the enterprise-specific assessment: capability fit, industry fits, the extensions an enterprise deployment adds, and the audit advantage. The shared foundation (what Polyglav provides today, the adoption path, and the reference architecture) is in [index.md](index.md).

## Fit by capability area

The research consistently ranks the capability areas in the same order. This table generalizes that ranking beyond food production.

| Area | Fit | Notes |
|------|-----|-------|
| Monitoring | High | Summarizing alarms and context, correlating data sources, explaining deviations. Read-only, low risk. Needs data-source connectors. |
| Analysis | High | Root-cause analysis, trends, comparisons, KPI breakdowns. Keep deterministic calculation (SQL, time-series math, OEE formulas) in the analytics layer and use the LLM for interpretation. |
| Reporting | High | Shift/day/week reports, deviation reports, management summaries. Requires structured data, source and time-range citation, and data completeness indicators. |
| Planning | Medium | Drafting and evaluating plan variants, spotting capacity conflicts. The actual optimization belongs in a deterministic solver or APS/MES system. |
| Control / writing actions | Low to medium | Creating non-critical tickets or work orders with approval. Never direct control of safety-critical loops. Write actions must go through a permission, policy, and approval chain. |

The guiding principle from the research applies across industries: the target architecture is not "the model operates the plant" but "the agent interprets data and proposes actions, a policy and workflow layer checks them, and only a limited gateway may execute approved commands."

## Industry fits

Polyglav's combination of auditability, local control, and low footprint applies broadly across manufacturing and operations. The verticals below are examples of where the fit is strongest. The food section is the researched reference case. The list is illustrative rather than exhaustive, and the same capability pattern generalizes to any vertical with regulated processes, assets to monitor, and reports to produce.

### Manufacturing (general)

- **Document and knowledge access** - SOPs, work instructions, specifications, and standards searchable in plain language, with the current and valid version surfaced and cited.
- **Operations reporting** - automated shift, day, and deviation reports across lines, plants, and sites.
- **Maintenance support** - fault analysis against asset history, drafting work orders, spare-part queries. With CMMS integration, preparing and (with approval) raising work orders.
- **Production analysis** - OEE, downtime, scrap, and energy analysis, capacity and bottleneck questions in natural language.
- **Layered Process Audit (LPA) support** - checklist-driven audits of high-risk process steps, run at operator, supervisor, and management layers on different frequencies. Build and manage checklists, capture findings into corrective actions, and generate LPA summaries. The append-only session log doubles as the audit trail for the audits themselves.
- **Planning assistance** - plan variants, conflict detection, what-if scenarios for delays or outages.

### Food & beverage

The food industry is highly regulated (HACCP, IFS Food, BRCGS, ISO 22000, EU Regulation 178/2002) and requires full traceability of every decision. That is precisely where Polyglav's audit-first design pays off:

- **HACCP / CCP monitoring** - continuously watch critical control points (core temperatures, pasteurization, cold chain) and alert on deviation with a root-cause explanation.
- **Batch traceability** - follow lots from raw material to finished product, identify affected batches, and prepare recall documentation.
- **Compliance reporting** - automated documentation for audits: hygiene training, cleaning confirmations, quality releases, deviation records.
- **Recipe and allergen management** - versioned recipes, allergen cross-contamination risk awareness in line sequencing and cleaning cycles.
- **Supplier and quality scorecards** - aggregate quality data, delivery reliability, and complaint rates.

As elsewhere, food safety decisions (release of a batch, recall, setpoint changes) must stay human-gated. The agent prepares and evidences them.

### Pharmaceuticals & life sciences

Same pattern as food, with even tighter validation requirements (GxP, 21 CFR Part 11, EU Annex 11) for audit trails, electronic records, batch records, and deviation management. Polyglav's complete session logs and local storage align with validated-environment expectations, and the same phased approach applies: document knowledge, monitoring explanation, deviation analysis, and audit-ready reporting before any write access.

### Chemicals & process industries

Continuous process data, alarm floods, energy and media consumption, safety documentation (SDS, permit-to-work), and regulatory reporting. Read-only alarm triage and root-cause analysis are the natural entry points. Any setpoint or valve action belongs behind a dedicated gateway with independent safety functions.

### Automotive & discrete manufacturing

Line-side quality, andon/poka-yoke deviations, supplier quality, maintenance and tooling management, and production planning across variants. High value in reporting and analysis. Layered Process Audit (LPA) originated here: the same standard-work checklists run at operator, supervisor, and management layers on different frequencies, so coverage, findings, and corrective actions are a natural reporting and analysis workload. Control stays with the PLC / line control layer.

### Aerospace & defense

The automotive pattern with tighter certification and traceability: AS9100/AS9102 quality systems, ITAR/EAR export control, and part-level traceability from first article to in-service performance.

- **Document and knowledge access** - engineering standards, AS9102 first-article forms, work instructions, and customer requirements searchable with the valid revision cited.
- **NCR and quality analysis** - non-conformance reports, concessions, and MRB dispositions analyzed for root cause and recurrence trends.
- **Supplier quality** - supplier performance, certification status, and delivery reliability scorecards.
- **Audit preparation** - compliance evidence assembled for AS9100, customer, and regulatory audits.

Engineering release and disposition decisions stay human-gated.

### Electronics & semiconductor

Process-heavy, high-volume manufacturing where yield, rework, and equipment drift dominate. IPC standards and SPC govern assembly, and lots and serial numbers track every unit.

- **Yield and process analysis** - yield, rework, and defect pareto by line, station, shift, and equipment, with root-cause explanation.
- **Equipment monitoring** - drift, alarms, and preventive-maintenance signals across SMT, test, and wafer-fab equipment.
- **Traceability and RMA** - serial and lot traceability for field failures, warranty, and recall scoping.
- **Shift reporting** - daily production, quality, and exception reports.

Line and fab control stays with the automation and control layer.

### Medical devices

Like pharma, but the regulated artifact is the device: ISO 13485, 21 CFR Part 820, and EU MDR frame design, production, and post-market surveillance.

- **DHR/DMR documentation** - device history records and master records assembled and queryable.
- **CAPA and complaint analysis** - complaints, vigilance reports, and CAPAs analyzed for root cause and trends.
- **Sterilization and batch records** - sterilization cycles and lot records traced and reconciled.
- **Audit readiness** - evidence prepared for notified-body and FDA inspections.

Release decisions and field actions stay human-gated.

### Metals, plastics & heavy industry

High-temperature and high-energy processes such as casting, forging, molding, rolling, and heat treatment, where scrap, rework, and energy dominate cost.

- **Heat and lot analysis** - chemistry, heat, and batch results compared against spec with out-of-spec explanation.
- **Scrap and energy reporting** - scrap, rework, and energy intensity by product, line, and shift.
- **Tool and die maintenance** - tooling life, condition, and maintenance planning against the CMMS.
- **Production analysis** - OEE, throughput, and bottleneck questions in natural language.

Furnace, caster, and mill control stays with the process control system.

### Logistics & supply chain

Shipment monitoring, exception handling, carrier scorecards, warehouse querying, and documentation. Natural home for reporting and alerting. Write actions (order changes, dispatch instructions) need approval workflows.

### Energy & utilities

Asset monitoring, anomaly and predictive maintenance on rotating equipment, outage documentation, and regulatory reporting. Read-only insight and reporting first. Grid- or plant-critical actions remain with the control systems.

### Mining & extraction

Heavy assets, safety-critical operations, and environmental obligations. Data spans mobile fleet, fixed plant, ore grades, and tailings.

- **Fleet and plant health** - equipment condition, downtime, and predictive-maintenance signals across trucks, shovels, and the processing plant.
- **Safety incident analysis** - incident records analyzed for causes and recurring patterns.
- **Environmental reporting** - water, tailings, and dust monitoring summarized for regulatory and community reporting.
- **Ore-grade reconciliation** - planned versus actual grade reconciled across pit and plant.

Blasting and process control stays with the mine control system.

### Construction & engineering

Project-centric, documentation-heavy work across build, infrastructure, and engineering projects. Safety and quality depend on inspection discipline on site.

- **Site documentation** - daily logs, progress photos, and field reports assembled and searchable.
- **Inspection checklists** - safety and quality walk-downs, including layered process audit (LPA)-style checklists at crew, supervisor, and management frequencies.
- **Progress reporting** - daily, weekly, and milestone reports against the schedule and budget.
- **Punch-list and subcontractor tracking** - open items and subcontractor status summarized for review.

Contractual and payment actions stay behind approval workflows.

### Retail & consumer goods

Demand-driven and margin-thin, with quality, freshness, and waste driving cost. CPG quality functions are food & beverage quality in miniature.

- **Demand and inventory analysis** - stock positions, sell-through, and replenishment questions in natural language.
- **Supplier scorecards** - delivery reliability, quality, and compliance aggregated per supplier.
- **Freshness and waste reporting** - shrinkage, expiry, and waste by category, store, and region.
- **Promotion and price planning** - plan variants and what-if scenarios for pricing and campaigns.

Write actions (orders, price changes, markdowns) go through approval.

### Public sector & government

Regulated back-office work that needs every decision step logged, matching the finance & healthcare pattern.

- **Regulation and policy knowledge** - legislation, directives, and internal policy searchable with the current and valid version cited.
- **Document drafting** - correspondence, briefings, and case-file drafts prepared with sources attached.
- **Case work assistance** - status, evidence, and deadline summaries for case files.
- **Auditable workflow** - every query and draft logged end to end for review and compliance.

### Finance & healthcare (support functions)

Less directly an industrial control use case, but the same core applies to auditable assistants for regulated back-office work: document knowledge, report generation, and compliance-adjacent drafting where every step is logged.

## Enterprise extensions needed

The research and the roadmap ([TODO.md](../../TODO.md)) agree on what an enterprise deployment adds on top of the core. These are planned or required extensions, not current capabilities:

- **Identity and access** - OIDC / SAML / LDAP integration, role-based access control down to tool level, tenant and site separation.
- **MCP support** - an MCP client plugin (connect to external MCP servers and register their tools into the ToolRegistry) and an MCP server (expose Polyglav's tools and sessions to external agents). Planned in [TODO.md](../../TODO.md).
- **Connectors** - data ingestion and write channels for the systems of record: OPC UA / MQTT for machine and sensor data, and adapters for MES, ERP, LIMS, CMMS, WMS, and document management. The enterprise plugin list in [TODO.md](../../TODO.md) covers `read_stream`/`write_stream`, time-series analysis, model inference, scheduling optimization, SCADA commands, and reporting.
- **Tool gateway and policy engine** - a controlled layer between the agent and target systems: whitelisted tools, strict input schemas, read/write separation, value ranges, rate limits, idempotency, four-eyes approval, dry run, and full logging. Write tools must never carry the same rights as read tools.
- **Durable workflows** - scheduled jobs, retries with backoff, timeouts, resumability, and the human-in-the-loop status model (`proposed`, `approved`, `executing`, `verified`, `failed`) landed as `polyglav jobs` (see [jobs.md](../jobs.md)). Dead-letter queues remain planned, and the workflow engine is now a first-class command.
- **Central audit aggregation** - Polyglav's per-agent session logs are complete, but enterprise compliance wants a central, tamper-evident view: aggregated audit with correlation IDs across agents and target systems, retention policies, and export for compliance and forensics. Options are a lightweight audit proxy in front of `polyglav serve`, or a dedicated store.
- **Observability** - metrics for latency, cost, errors, and tool usage, tracing across agent, MCP, and target systems, alerting on misbehavior, prompt and model versioning, rate and budget limits.
- **Edge deployment** - offline-capable agents with local buffering and store-and-forward for plants with limited or unreliable connectivity.
- **Sandboxed execution** - namespace/container isolation for `run_command`, listed as planned in [TODO.md](../../TODO.md).

The production-grade reference architecture and the phased adoption path are shared with the other use-case guides in [index.md](index.md).

## Audit advantage vs. alternatives

The research positions Polyglav's audit capability as its main differentiator for regulated environments. What matters is the depth of the record rather than a headline:

| Criterion | Polyglav today | OpenClaw (per its audit docs) |
|-----------|--------------|-------------------------------|
| Log granularity | Session-based: messages, tool calls, arguments, results, thinking, errors, timestamps, model | Gateway-wide: run identity, time, agent, action, status, result code |
| Tool arguments and context | Stored in the session log | Deliberately not stored in the audit ledger (metadata-only, privacy-friendly) |
| Reasoning | `thinking` metadata preserved with each assistant message | Not captured in the audit ledger |
| Tamper resistance | Append-only local files (modification is detectable, not cryptographically sealed) | Hash-chaining, optional SIEM forwarding |
| Cross-agent trail | Per-agent sessions, a supervisor must aggregate | Built-in gateway aggregation |
| Data sovereignty | Local files, no external service | Workspace-based, local-first by design |

Polyglav's advantage is log depth. Its logs are **content-complete**: the full chain from user request, context, tool call with arguments, result, and reasoning is reconstructable, which is what auditors and quality departments need for batch-level traceability, deviation investigation, and recall documentation. That completeness is paired with strict isolation (worktree scoping, headless auto-deny) and zero external logging. For enterprise-grade compliance, the recommended additions are central aggregation and tamper-evidence (hash-chained logging or WORM storage) on top of the existing session logs, both additive rather than rework.
