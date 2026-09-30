# Vision

**One agent, many heads**

Polyglav is an agent harness: the runtime that turns a language model into an agent that can act. The model plans, the harness executes, and one streaming loop drives an interactive REPL, a headless CLI, and an HTTP API. Polyglav is deliberately small, zero-dependency, and auditable, so the whole runtime fits in one review.

The main agent, **assistant**, is the point of contact: it greets you on first run and asks what you want to do, answers small tasks inline in the current run, delegates bigger tasks to sub-agents or whole teams instead of blocking, runs recurring work in the background, watches your other agents for health, and reports back. Everything you need to see is reachable from one place: sessions, running agents, and configured jobs on the machine. Users never see the machinery. They feel supported and do less work.

## What Polyglav is

An agent is a model plus a harness:

- **Execution loop** - one SSE stream per turn. The model either emits content or requests tool calls, which the loop runs and feeds back until the answer is complete.
- **Tool dispatch** - one registry with one OpenAI-compatible function-calling contract. Tools carry their own permissions, path scoping, and status rendering.
- **Context management** - session logs, compaction, and bounded memory keep the provider context honest.
- **State and memory** - complete append-only session logs, run-owned continuity, and compacted memory per role, team, and job.
- **Sandboxing and permissions** - `allow` / `ask` / `deny` per tool, path-scoped confirmation outside the worktree, and an audit trail in the session log.
- **Observability** - every prompt, thought, tool call, result, and error is persisted.
- **Orchestration** - one agent or many: roles and delegation (swarm), scheduled durable work (jobs), and a supervisor for many scoped agents (fleet).

## The runtime

Polyglav assembles five replaceable layers. Each can be swapped without touching the others:

| Layer | What it holds |
|-------|---------------|
| Access | the front-ends: REPL, CLI, HTTP API, MCP, and ACP |
| Orchestration | runs, focus, delegation, teams, jobs, and the fleet supervisor |
| Capability | tools, skills, roles, and permissions |
| Model | providers and the model catalog |
| Storage | sessions, memory, and the catalog |

The direction is **everything is a plugin**. Models, tools, skills, sessions, sandboxes, storage, loops, scheduling, and the UI become replaceable plugins around a thin core. The REPL itself moves to a plugin, so the same runtime can be driven by a terminal, a web UI, or another agent. The core keeps the loop and the registry contracts, and nothing customer-specific.

Interop is part of the same idea. MCP connects tools and sessions today. ACP, inward and outward, is the direction: Polyglav hosts other harnesses and can be hosted by them.

## How the assistant works

- **Onboarding** - on first run the assistant introduces itself, explains what it can do, and asks what the user wants to do. No system-level configuration is required of simple users.
- **Small tasks inline** - a question or a small task is answered in the current run, through the existing one-stream agent loop.
- **Bigger tasks delegated, never blocking** - for work that does not end after one task, the assistant starts sub-agents or whole teams, then reports their status. The user can check status with commands, jump into a session, ask for the current state, or view and mark items done on a per-agent todo list.
- **Recurring tasks carry their own role** - each job carries its own role and skills, so behavior is encoded once instead of re-prompted. A recurring task that maintains docs "per AGENTS.md" keeps that convention in its own skill, not in every prompt.
- **Health monitoring** - the assistant can watch endpoints (for example the `/health` of agents running as web APIs) and warn when an agent stops responding.
- **One-window status** - sessions, running agents, and configured jobs on the current machine are visible with commands, without a separate CLI. Logs are reachable from the same surface.
- **Report-back** - finished or failed runs surface a summary, and are delivered out-of-band over connectors (webhook first, email later) when the terminal is closed.
- **Governance mode** - when needed, the full control surface is available. For small tasks the assistant simply responds in the current run. The user does not see the complexity of the whole, only the reduced workload.

## Workflow

The end-to-end shape of a bigger task:

1. **Ask** - the operator states an outcome to the `assistant`, in one sentence.
2. **Compose** - for work beyond one task, the assistant engages the `composer` role, which designs a team: the specialists, the skills each needs, the stage order, and an optional review loop. The team is saved to the catalog, so it can be reused and extended.
3. **Run** - the assistant starts the team. Stages run in order, each with its own role, skills, and permission carve, and each writing its own session log. A review loop lets a producer revise against the reviewer's feedback until it passes.
4. **Hand off** - as phases change, control moves from one run to the next. The assistant hands focus to the composer, the composer to a planning agent, the planning agent to a developer, and back again with a new task. Each run keeps its own session, so a developer resumes with what it just did.
5. **Watch or stay out** - the operator can follow progress, jump into any run with `/focus`, or let it run silently. A status line shows what each agent is doing.
6. **Remember** - after the run, the team and its members update bounded memory. The next run continues from the change, not from a replayed transcript.
7. **Report** - finished and failed runs surface a summary, and recurring work reports out of band.

## Usage

A few ways people use Polyglav:

- **One terminal, whole teams** - ask the assistant for an outcome (a document, a feature, a review), and let it compose and run a team. You stay at one prompt.
- **A recurring maintainer** - schedule a job that carries its own role and skills, for example "keep the docs in sync with AGENTS.md", and let the scheduler run it unattended.
- **A supervised fleet** - run many single-purpose agents, one per folder, under the fleet supervisor, and reach each over HTTP.
- **A library of specialists** - define roles and skills once, then reuse them across tasks, teams, and jobs, extending a role per task with additional skills.
- **A scripted agent** - drive the same loop from the CLI or the HTTP API for automation and CI.

This is the operator-facing half of the runtime, and it is what the phases turn on.

## Decisions

- **Assistant is the single point of contact** - the main agent is the operator's entry point. Delegation and team composition are its job, using the roles, teams, and skills registries (bundled, global, local, and plugin layers).
- **Modes are the posture** - the root agent is `config.system_prompt` plus the active mode, not a bound role. `read` is the default (read, search, and role-less read-only sibling offload; no writes, no named-role calls, no grants), and `write` is opt-in (filesystem writes, named-role `call`, team `delegate`, and permission grants, still bounded and confirmed for destructive actions). A single session-scoped mode switch replaces per-tool permission grants and the root delegation ceiling. No root/assistant role or bundled persona: the system prompt is set from config (or onboarding).
- **Run-owned sessions** - a session belongs to a run. Whoever starts a run creates its session: the root at startup, `delegate`/`team` at delegation, the scheduler per job run. A role is an identity a run borrows, never a session owner, so there is no `agent_<role>` and no `sub_<key>`.
- **Focus navigates, handoff moves** - `/focus` shows the run tree and jumps into existing runs, and never creates a session. `handoff` moves focus between runs and pauses or finishes the current one, without creating or naming a session.
- **Memory, not replay** - continuity has two scales. Within a run, the run's own session is the context, so a planner giving a developer another task sees its recent work. Across runs, continuity is bounded memory: a compacted Markdown summary per role, team, and job, injected into briefs and refreshed after runs, so recurring work does not replay an ever-growing session.
- **Sequential-first** - team stages run one member after another via `run_subagent` (existing, battle-tested). In-process threaded concurrency is the later milestone for watching and joining a live run (cuts wall-clock and lets the operator jump in, not tokens).
- **No pre-saved run prompts** - briefs, handoff, and memory are generated per run. Stored artifacts are roles, teams, and skills in the registries.
- **Core stays thin and publishable** - registries plus the sequential runner plus plugin hooks. Everything customer-specific lives in local `roles.json`, `teams.json`, `skills/`, or plugins, and moves toward plugins entirely.

## Context economics (why this costs what it costs)

- Sub-engines are separate `Engine`s, with no in-memory context sharing. The persistence channels are session logs and memory files.
- Cold starts cost: file re-reads by multiple members and brief duplication. Mitigations are facts-in-briefs (not just paths), research stages summarizing into team memory (`.polyglav/memory/teams/<name>.md`), and bounded role/team/job memory, so recurring work never replays a whole session.
- Honest limit: per-run redundancy will not go to zero. Sequential wall-clock is accepted until concurrent runs land.

## Phases

The task mapping lives in `PLAN.md` (work packages). The phases below name the verifiable stages, ordered by dependency:

- **Runtime and docs** - one runtime for many agents, the five replaceable layers, and the plugin direction, reflected in VISION, README, and the site.
- **Modes-first** - `read`/`write` modes as the only posture, access classified by permission key (fail-closed), per-tool grants replaced by a session-scoped mode switch, the root as `system_prompt` + mode, and the tool taxonomy `offload`/`call`/`delegate`.
- **Runs, focus, and memory** - run-owned sessions, focus that only navigates, handoff between runs, bounded memory per role/team/job, and non-blocking runs with live focus.
- **Onboarding** - the assistant introduces itself on first run and asks what to do. Defaults and docs for simple users.
- **One-window status** - `/status` shows sessions, running agents, and configured jobs on the machine. Logs are reachable from the same surface.
- **Non-blocking delegation** - the assistant delegates big tasks to sub-agents or teams without blocking, with progress reporting, jump-into-session, and per-agent todo lists that can be marked done.
- **Recurring tasks with roles** - jobs carry their own role and skills, so recurring behavior is encoded per task.
- **Health monitoring** - the assistant watches agent endpoints and warns on failures.
- **Report-back connectors** - job summaries delivered out-of-band.
- **Governance mode** - the full control surface when needed, invisible otherwise.

## TODO.md placement

The vision, runtime, and docs track is at the top of `TODO.md` and `PLAN.md` (Vision, positioning, and docs). The runs, focus, and memory redesign is the next package (Runs, focus, and memory). The assistant track is tracked as open tasks and as work packages in `PLAN.md` (Control & governance, Delegation & swarm, Jobs operations + report-back).

## Out of scope (later milestones, listed not planned)

Remote messaging channels (Telegram, WhatsApp, Discord, and more), multi-machine fleet orchestration, sandboxed execution with namespace or container isolation, and a plugin registry or marketplace.
