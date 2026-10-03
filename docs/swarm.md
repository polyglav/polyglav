# Agent swarms

A swarm is the layer of agent cooperation. A fleet is many scoped processes running side by side, and a swarm is those processes or in-process engines working together on a task. A lead agent delegates subtasks to specialized sub-agents, auditors review the output, and the group iterates until the goal is met. Fleet and swarm orchestration are two layers, not two names for one thing.

| | Fleet orchestration | Swarm orchestration |
|---|---|---|
| Concern | Running agents | Making agents cooperate |
| Unit | `polyglav serve` process scoped to a folder | Agent with a role, either a fleet process or an in-process engine |
| Primitives | Supervisor with port allocation, health checks, restart policy, config generation | `/agent` roles, `delegate` tool, sub-agent loops, auditor agents |
| Channel | None | `POST /chat` (cross-process) or an in-process sub-engine |
| Question | How do I keep the agents alive? | How do the agents get the job done? |

The two compose. A swarm can run on top of a fleet, each swarm agent a fleet process and `delegate` routing over the same `POST /chat` API. Delegation also works in-process as a sub-`Engine` with no fleet at all. The two tasks are therefore separable, and neither is subordinate to the other. See [fleet.md](fleet.md) for the fleet side.

## Building blocks

- **Roles** (`/agent`): per-agent system prompt, session namespace, and optional model override. A role makes a sub-agent specialized instead of a copy of the caller. Per-agent permission profiles build on this.
- **`delegate(role, task)` tool**: spawns a sub-agent loop that runs a task with its own role, session, and model, and returns the result. The core swarm primitive.
- **Auditor agents**: sub-agents that review a produced output (tests, code review, fact-checking) instead of producing content themselves.
- **Generate to check to correct**: run a main agent, an auditor, and a fix pass in a loop until the auditor passes. A team expresses this as a `loop` over a producer/reviewer stage block (see [teams.md](teams.md#review-loop)).
- **PM/dev/tester orchestration**: multiple specialized agents cooperating on one outcome as a user-facing pattern.

## Roles and delegation

Roles are named agent definitions (a system prompt, optional model override, and optional per-agent tool permissions) stored in a single JSON catalog with bundled, global, and local layers (schema, permission rule, and bundled default roster in [roles.md](roles.md)). `delegate(role, task)` spawns a sub-agent that runs the task with the role's prompt, session, and model, and returns the result. Delegation resolves its permission from the selected type: a configured role uses its own `tool_permission` overrides (category `delegate` defaults to `allow`, so delegation runs without a prompt unless a role sets `ask`), while a temporary role created only for parallel work defaults to `deny` until opted in. The bundled catalog ships two pre-carved teams ready to delegate to out of the box: `researcher`/`writer`/`referencer`/`editor` for documents and `planner`/`programmer`/`tester`/`code-reviewer` for programming.

In-process sub-engines run with a quiet `NullUI`, so they never interleave with the caller's REPL, execute synchronously (one sub-agent at a time), and keep their own session (`sub_<ts>_<id>` in the shared `sessions/` dir, the calling session recorded as `parent_id`, saved as a complete log). A caller may resume an existing run or session with `delegate(role, task, resume=..., context=...)`, so the same agent keeps its prior context while per-run skills extend it (see [teams.md](teams.md#resuming-a-member-run)). There is no standing warm-session name, because a session belongs to the run that started it. A sub-engine inherits the caller's provider, plugin manager, and worktree. The role's `system_prompt` becomes the sub-agent's system prompt, its `model` overrides the caller's when set, and its `tool_permission` carve narrows the caller's categories. The role's standing skills are injected, and a caller may layer per-run skills through `delegate`/`team` or a team stage, so a reusable agent keeps its identity while each task adds its own instructions. The carve is capped by the caller's `grant_permission` ceiling (default: the caller's own carve), so a sub-agent can never gain a permission the caller was not authorized to delegate. A role that sets `grant_permission` may hand down categories it does not use itself (a supervisor that denies `edit`/`bash` can still delegate them). Sub-agents run in `build` mode regardless of the caller's mode, so the role carve alone decides edit/bash. Ask-gated tools are auto-denied (no interactive confirm), so a sub-agent's effective permissions are exactly the categories its carve allows. A denial returns an explicit `permission denied` result rather than a user-decline marker, the sub-agent prompt names the auto-denied categories and forbids retrying, and the loop stops after a few consecutive denials so the agent escalates through `ask` or returns a final answer instead of looping. The `delegate` tool surfaces which role and task are running, returns the sub-agent's final answer as its result, and, with `delegate_echo` on (default), renders the answer plus a sub footer (duration + completion tokens) in the REPL. A sub-agent or team stage that needs a decision or permission mid-run calls the core `ask` tool: `target='human'` routes to the operator at the terminal (prefixed with the asking session), `target='lead'` routes to the calling engine's model via a bounded consultation, and the answer feeds back into the asking agent so it can continue instead of returning an open question. A `kind='permission'` ask is routed by `ask_policy.permission` and, when approved within the ceiling, adds a one-shot grant on the asking sub-agent (the operator may grant `always` for the rest of that run). A running sub-agent shows an interruptible status line: the Braille spinner names the active stage, prints a dim `↔ Switch <run>` marker, stops animating on Enter (continue silently) and always yields while a confirm or `ask` prompt waits for input. A live "jump into the active sub-agent" view is future work, because `Engine.chat()` is a single blocking call and the status thread cannot hand the turn over yet. The `focus_on_delegate` config (`off`/`ask`/`on`, default `on`) is the first step toward that view: after a synchronous `delegate` or team run completes, the REPL moves its focus to the child run (the last stage for a team), so its output is shown automatically, while the caller's turn still finishes.

A document pipeline is a typical use: a lead agent asks a `researcher` for findings, hands them to a `writer`, has a `referencer` collect citations into a `.bib` file, and runs an `editor` to check the result against the original prompt. This is team orchestration built on roles and delegation. Named pipelines are stored as teams: ordered role chains with per-stage task hints and handoff notes, in a four-layer registry (bundled `writing`/`programming` rosters, plugin contributions, global/local `teams.json`, see [teams.md](teams.md)). `Engine.run_team` executes a team sequentially, with per-run briefs built from the task, prior stage results, the shared team memory (`.polyglav/memory/teams/<name>.md`), and stage handoffs, and a rolling memory write after the run. A lead agent runs one with the core `team(name, task)` tool, and the operator with `/teams run <name> <task>`.

## In-process vs. cross-process

| | In-process | Cross-process |
|---|---|---|
| Unit | Sub-`Engine` in the same process | Another `polyglav serve` agent |
| Setup | Spawn a child engine with a role | Point `delegate` at a sibling agent's `POST /chat` |
| Isolation | Shares the caller's process | Process, worktree, and tool-policy boundaries (see fleet.md) |
| Uses | Auditors, quick subtasks, no fleet required | Team orchestration across scoped folders |

## Security

Sub-agents follow the same tool policy as any agent. In-process sub-engines share the caller's privileges. Cross-process delegation is confined by the target agent's own worktree and `tool_permission` config.