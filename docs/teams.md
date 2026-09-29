# Teams

A team is a named, ordered chain of delegated stages, where each runs under a role and its result is handed to the next. A team turns the `delegate` primitive into a repeatable pipeline: "writing" = researcher > writer > referencer > editor for documents, "programming" = planner > programmer > tester > code-reviewer. The registry stores the definition and the sequential stage loop (`Engine.run_team`) executes it, reachable from the REPL (`/teams run`), the model (the `team` tool), and the CLI.

## Storage

Teams come from four layers, merged exactly like roles: bundled, then plugin, then global, then local, local winning per field. Precedence is `bundled < plugin < global < local`:

- **Bundled** - the read-only default roster shipped in the package (`src/polyglav/bundled_teams.json`, the `writing` and `programming` pipelines above).
- **Plugin** - teams contributed by plugins via the `register_teams` entry hook (`registry.add_plugin(...)`, see [plugins.md](plugins.md)). An in-memory layer: never written to any `teams.json`, refreshed on `/plugins install`/`update`/`uninstall`.
- **Global** - `~/.config/polyglav/teams.json`.
- **Local** - `.polyglav/teams.json`.

Merging is field-by-field for the same `name`: an entry overrides only the fields it sets, and `stages` is replaced wholesale.

## Schema

```json
{
  "writing": {
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
        "mode": "build",
        "task_hint": "Write the document from the findings list.",
        "handoff_note": "Hand the document path to the referencer."
      }
    ]
  }
}
```

Team fields:

- `name` - unique key (the file/registry key).
- `stages` - ordered list of stage objects. A stage may also be a plain string (`"researcher"`), shorthand for a stage with only a role.
- `description` - optional, shown in `/teams show`.
- `tags` - optional list for grouping and filtering (`/teams list <tag>`), same vocabulary as roles.
- `loop` - optional review loop over a producer/reviewer stage block (see [Review loop](#review-loop)). Properties: `from`, `until`, `max_iterations`, `verdict`.

Stage fields:

- `role` - required, the role name (must exist in the [roles registry](roles.md) at run time, resolved against the same four-layer merge).
- `mode` - optional agent mode override for the stage. Empty inherits the caller. With the sequential stage loop, an explicit mode applies to that stage's sub-engine while the rest of the team follows the caller.
- `task_hint` - optional guidance folded into the delegated brief for this stage.
- `handoff_note` - optional note passed with the previous stage's result into the next stage's brief.
- `skills` - optional list of skill names added to this stage's role for the run, layered over the role's standing skills (see [skills.md](skills.md)). The `team` tool adds task-wide skills to every stage through its own `skills` argument.

## Managing teams

- `/teams` - list teams, marking each one's origin (`bundled` / `plugin` / `local` / `global` / `merged`) and tags, with the stage chain on the next line.
- `/teams list <tag>` - list only teams carrying the tag (e.g. `/teams list programming`).
- `/teams new <name> [description]` - create a team in the local catalog (edit the JSON for stages, tags, and per-stage fields). Using an existing name overrides that team.
- `/teams remove <name>` - remove a team from the local catalog. Bundled teams cannot be removed (override them instead).
- `/teams show <name>` - show a team's full definition (stages, task hints, handoff notes).

Plugins contribute teams through the same `register_teams` entry hook the kit machine (templates, recipes) uses. See [plugins.md](plugins.md).

## Running a team

`Engine.run_team(team, task)` runs the stages one after another through the same in-process sub-engine as `delegate` (`run_subagent`): each stage runs in its own fresh `sub_<ts>_<id>` session by default, with its own role prompt, skills, and permission carve, and the stage `mode` overrides the caller's when set (an empty `mode` inherits). A failed stage stops the run and the remaining stages do not execute.

The brief handed to each member is built per run from:

- the team name (and description) plus the original task,
- each prior stage's result (a `## Stage N result (<session>)` block, capped at 4000 chars with a truncation marker),
- the previous stage's `handoff_note` as a stage handoff line,
- the shared team memory block, when present,
- the stage's `task_hint` (or a generic "Complete this stage of the task." line).

After the run, the whole team run is summarized (seeded with the previous team memory) and written to **`.polyglav/memory/teams/<name>.md`** (atomic write, human-editable). The next run reads the same file back into its briefs, so facts from earlier runs carry without the session files growing. If the summarizer fails, a fallback of one line per stage (role, status, first part of the output or error) is stored instead.

`/teams run <name> <task>` executes a team from the REPL and prints one line per stage (`<n>. <role> <status> <duration>s`), the final member's result, and the memory file path.

## Resuming a member run

Every stage starts a fresh run with its own session by default. To continue a previous thread, pass `resume` to the `team` tool:

- `team(name, task, resume=...)` resumes that run or session for the **first stage**, which then keeps its prior context. Later stages start fresh, seeded by the brief.
- `resume` accepts a run id (`#3`), a session id (`#ab12cd`), a session name, or `session:<name>`.
- `context` controls how the resumed context is treated: `continue` (append, default), `compact` (summarize the prior turns first), or `new` (ignore `resume` and start fresh).

The same applies to a single delegated agent: `delegate(role, task, resume=..., context=...)`. There are no standing warm-session names, since a session belongs to the run that started it and is resumed explicitly by run or session handle.

## Review loop

A team can iterate a producer/reviewer block until the review passes or a cap is reached, the generate > check > correct pattern. The team's `loop` names the block by stage role (or zero-based index):

```json
{
  "loop": { "from": "writer", "until": "reviewer", "max_iterations": 3, "verdict": "VERDICT:" }
}
```

- Stages before `from` run once, then the `from..until` block repeats, then stages after `until` run once.
- The `until` stage is the review. It passes when its result contains the verdict marker followed by `PASS` (case-insensitive). The default marker is `VERDICT:`, configurable through `loop.verdict`. A reviewer stage should be told to end with `VERDICT: PASS` or `VERDICT: CHANGES`.
- On the next iteration the producer's brief carries a `## Findings from the previous review` block, so it revises with the review context even though each iteration starts a fresh run.
- `max_iterations` (default 3) caps the block. Reaching it without a pass is still a successful run, with the last review as the result.

Each loop iteration starts a fresh producer run seeded by the findings, rather than replaying a standing session.

## The `team` tool

`team(name, task)` is the model-facing entry point (core, like `delegate` and `ask`), so a lead agent can orchestrate a whole pipeline in one call instead of delegating each stage itself. It runs `Engine.run_team` and returns the final stage's answer (or `Error: team "<name>" failed: <reason>`).

- **Permission**: the `team` category gates the tool (default `allow`), separate from `delegate` so a role can be a delegation target but not run pipelines. On top of that, a per-invocation resolver reads the stage roles like `delegate`: a stage role that sets `delegate: "deny"` disables the team, `"ask"` confirms it, otherwise it runs. Unknown teams and stages with unknown roles return a clear error.
- **Ceiling**: each stage's carve is still capped by the caller's `grant_permission` (see [config.md](config.md#permission-authority)). When a stage's requested permissions get clamped, the result carries a `(reduced permissions for: <role>)` note, so a silently degraded run is visible. A stage whose carve requests a category the caller cannot delegate is told which categories are auto-denied, and the run stops after repeated denials instead of looping.
- **Depth and cycles**: `run_team` refuses a team already on the current stack (`team_cycle`) and stops at `max_team_depth` nested team runs (default 2, `team_depth`), so a supervisor stage that itself runs teams cannot recurse forever. Both values propagate into sub-engines.

The REPL `/tool team {"name": ..., "task": ...}` runs the same handler through a persisted agent-loop turn (the tool is registered `loop=True`).

Scheduled team runs (`jobs add --team`) and job-style recurring member sessions are later milestones.