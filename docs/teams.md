# Teams

A team is a named, ordered chain of delegated stages, where each runs under a role and its result is handed to the next. A team turns the `call` primitive into a repeatable pipeline: "writing" = researcher > writer > referencer > editor for documents, "programming" = planner > programmer > tester > code-reviewer. The registry stores the definition and the sequential stage loop (`Engine.run_team`) executes it, reachable from the REPL (`/teams run`), the model (`call target=<team> kind=team`), and the CLI.

## Team shapes

A team has two types:

- **Sequential** (the default) - the stages run in order, and each stage's result is handed to the next. The caller is the manager: it receives the final stage's answer, decides whether it is correct, and calls the team again when it needs another pass. This is what `call` and `Engine.run_team` execute for a sequential team, and it is the right shape for a small fixed pipeline such as developer then tester.
- **Hierarchical** - a manager role receives the task, allocates work to the member roles with the `call` tool, validates the outcomes, re-assigns work when needed, and returns the final answer. The manager is the only run that stays open for the whole team. Use it when the work needs dynamic allocation or internal validation.

A composing agent can check a definition before saving it with `catalog action=validate`, which reports an unknown permission key, a missing stage role, a missing manager or member, a stage role that is not in the catalog, and a team that mixes the fields of the two types. The assistant confirms the design with the user (the deliverable, the type, and the per-role permissions) before composing a team, so an incomplete request is clarified rather than guessed.

## Storage

No teams ship with the package. A fresh install has an empty catalog, and the user or an agent creates teams as a project needs them (the `catalog` tool and `/teams new`). A project that keeps a tuned catalog can commit it under `.polyglav/` so it travels with the repository.

Teams come from three layers, merged exactly like roles: plugin, then global, then local, local winning per field:

- **Plugin** - teams contributed by plugins via the `register_teams` entry hook (`registry.add_plugin(...)`, see [plugins.md](plugins.md)). An in-memory layer: never written to any `teams.json`, refreshed on `/plugins install`/`update`/`uninstall`.
- **Global** - `~/.config/polyglav/teams.json`.
- **Local** - `.polyglav/teams.json`.

Merging is field-by-field for the same `name`: an entry overrides only the fields it sets, and `stages` is replaced wholesale.

## Schema

```json
{
  "writing": {
    "type": "sequential",
    "description": "Document pipeline: research, write, reference, edit",
    "tags": ["research", "writing"],
    "stages": [
      {
        "role": "researcher",
        "task_hint": "Gather and evaluate sources on the topic.",
        "handoff_note": "Hand the findings list to the writer."
      },
      {
        "role": "writer",
        "mode": "write",
        "task_hint": "Write the document from the findings list.",
        "handoff_note": "Hand the document path to the referencer."
      }
    ]
  },
  "site": {
    "type": "hierarchical",
    "description": "Manager-led landing page",
    "manager": "site-manager",
    "members": [
      {"role": "researcher", "task_hint": "Gather cited facts."},
      {"role": "designer", "skills": ["landing-page"]},
      {"role": "developer"},
      {"role": "tester"}
    ]
  }
}
```

Team fields:

- `name` - unique key (the file/registry key).
- `type` - `sequential` (default) or `hierarchical`.
- `stages` - sequential only. Ordered list of stage objects. A stage may also be a plain string (`"researcher"`), shorthand for a stage with only a role.
- `manager` - hierarchical only. The role that receives the task, calls members, validates results, and returns the final answer.
- `members` - hierarchical only. Ordered list of roles the manager may call, each with optional `skills` and `task_hint`.
- `description` - optional, shown in `/teams show`.
- `tags` - optional list for grouping and filtering (`/teams list <tag>`), same vocabulary as roles.
- `loop` - optional sequential review loop over a producer/reviewer stage block (see [Review loop](#review-loop)). Properties: `from`, `until`, `max_iterations`, `verdict`. A caller can also accept the result and call the team again instead of using a loop.

Stage and member fields:

- `role` - required, the role name (must exist in the [roles registry](roles.md) at run time, resolved against the same three-layer merge).
- `mode` - optional agent mode override for a sequential stage. Empty inherits the caller. Member modes are inherited from the manager.
- `task_hint` - optional guidance folded into the delegated brief for a stage, or shown to the manager as guidance for a member.
- `handoff_note` - optional note passed with the previous stage's result into the next sequential stage's brief.
- `skills` - optional list of skill names added for the stage or member run, layered over the role's standing skills (see [skills.md](skills.md)). The `call` tool adds task-wide skills to every stage through its own `skills` argument.

## Managing teams

- `/teams` - list teams, marking each one's origin (`plugin` / `local` / `global` / `merged`) and tags, with the stage chain on the next line.
- `/teams list <tag>` - list only teams carrying the tag (e.g. `/teams list programming`).
- `/teams new <name> [description]` - create a team in the local catalog (edit the JSON for stages, tags, and per-stage fields). Using an existing name overrides that team.
- `/teams remove <name>` - remove a team from the local catalog. A plugin team cannot be removed (override it with a local entry instead).
- `/teams show <name>` - show a team's full definition (stages, task hints, handoff notes).

Plugins contribute teams through the same `register_teams` entry hook the kit machine (templates, recipes) uses. See [plugins.md](plugins.md).

## Running a team

`Engine.run_team(team, task)` runs the stages one after another through the same in-process sub-engine as `call` (`run_subagent`): each stage runs in its own fresh `sub_<ts>_<id>` session by default, with its own role prompt, skills, and permission carve, and every stage inherits the caller's mode (a stage cannot escalate it). A failed stage stops the run and the remaining stages do not execute.

The brief handed to each member is built per run from:

- the team name (and description) plus the original task,
- each prior stage's result (a `## Stage N result (<session>)` block, capped at 4000 chars with a truncation marker),
- the previous stage's `handoff_note` as a stage handoff line,
- the shared team memory block, when present,
- the stage's `task_hint` (or a generic "Complete this stage of the task." line).

After the run, the whole team run is summarized (seeded with the previous team memory) and written to **`.polyglav/memory/teams/<name>.md`** (atomic write, human-editable). The next run reads the same file back into its briefs, so facts from earlier runs carry without the session files growing. If the summarizer fails, a fallback of one line per stage (role, status, first part of the output or error) is stored instead.

A hierarchical team runs its manager once through the same `run_subagent` path, with a brief that lists the original task, the member roster, each member's `task_hint` and `skills`, the shared team memory, and the instruction to allocate, validate, and return the final answer. The manager calls members with `call`; the members are ordinary role runs with their own permission carves. The team result is the manager's final answer.

`/teams run <name> <task>` executes a team from the REPL and prints one line per stage (`<n>. <role> <status> <duration>s`), the final member's result, and the memory file path. A hierarchical team prints its manager line and result.

## Resuming a member run

Every stage starts a fresh run with its own session by default. To continue a previous thread, pass `resume` to the `call` tool:

- `team(name, task, resume=...)` resumes that run or session for the **first stage** of a sequential team or the **manager** of a hierarchical team, which then keeps its prior context. Later stages start fresh, seeded by the brief.
- `resume` accepts a run id (`#3`), a session id (`#ab12cd`), a session name, or `session:<name>`.
- `context` controls how the resumed context is treated: `continue` (append, default), `compact` (summarize the prior turns first), or `new` (ignore `resume` and start fresh).

The same applies to a single delegated agent: `call(target=<role>, task=..., resume=..., context=...)`. There are no standing warm-session names, since a session belongs to the run that started it and is resumed explicitly by run or session handle.

## Review loop

A sequential team can iterate a producer/reviewer block until the review passes or a cap is reached, the generate > check > correct pattern. The team's `loop` names the block by stage role (or zero-based index):

```json
{
  "loop": { "from": "writer", "until": "reviewer", "max_iterations": 3, "verdict": "VERDICT:" }
}
```

- Stages before `from` run once, then the `from..until` block repeats, then stages after `until` run once.
- The `until` stage is the review. It passes when its result contains the verdict marker followed by `PASS` (case-insensitive). The default marker is `VERDICT:`, configurable through `loop.verdict`. A marker that already names the outcome (`VERDICT: PASS`) is honored as-is, while a bare prefix (`VERDICT:`) has `PASS` appended. A reviewer stage should be told to end with `VERDICT: PASS` or `VERDICT: CHANGES`.
- On the next iteration the producer's brief carries a `## Findings from the previous review` block, so it revises with the review context even though each iteration starts a fresh run.
- `max_iterations` (default 3) caps the block. Reaching it without a pass is still a successful run, with the last review as the result.

Each loop iteration starts a fresh producer run seeded by the findings, rather than replaying a standing session.

## The `call` team target

`call(target=<team>, kind=team, task=...)` is the model-facing entry point (core, like `call` on a role and `ask`), so a caller agent can orchestrate a whole pipeline in one call instead of calling each stage itself. It runs `Engine.run_team` and returns the final stage's answer (or `Error: team "<name>" failed: <reason>`).

- **Permission**: the `call` category gates the tool. On top of that, a per-invocation resolver reads the target roles. A sequential team is denied when any stage sets `callable: "deny"` and asks when any stage sets `"ask"`. A hierarchical team uses the manager's `tool_permission.call` action and requires the manager and every member to be callable. `tool_permission.call` is the "may call others" permission, while `callable` is the "may be called" permission. Unknown teams and roles return a clear error.
- **Ceiling**: each stage's carve is still capped by the caller's `grant_permission` (see [config.md](config.md#permission-authority)). When a stage's requested permissions get clamped, the result carries a `(reduced permissions for: <role>)` note, so a silently degraded run is visible. A stage whose carve requests a category the caller cannot delegate is told which categories are auto-denied, and the run stops after repeated denials instead of looping. When a stage fails without its own error detail, the team result names the stage status and its sub-session id (and, for a clamped stage, points at the caller ceiling) instead of an opaque `unknown error`.
- **Depth and cycles**: `run_team` refuses a team already on the current stack (`team_cycle`) and stops at `max_team_depth` nested team runs (default 2, `team_depth`), so a supervisor stage that itself runs teams cannot recurse forever. Both values propagate into sub-engines. A stage cannot run its own team: the per-invocation resolver returns `deny` (`disabled by tool policy`) when the requested name is already on the stack, and each stage brief instructs the stage to do its own work directly instead of calling the team tool for its own team.

The REPL `/tool call {"target": ..., "kind": "team", "task": ...}` runs the same handler through a persisted agent-loop turn (the tool is registered `loop=True`).

Scheduled team runs (`jobs add --team`) and job-style recurring member sessions are later milestones.