# Memory

Continuity has two scales. Within a run, the run's own session is the context, so a planner giving a developer another task sees its recent work. Across runs, continuity is bounded memory: a compacted Markdown summary per scope, injected into briefs and refreshed after runs, so recurring work does not replay an ever-growing session.

## Scopes and storage

Memory lives under `.polyglav/memory/` in the worktree, one file per name:

| Scope | Path | Refreshed | Injected |
|-------|------|-----------|----------|
| `role` | `.polyglav/memory/roles/<type>.md` | After a delegated agent run | Into that role's sub-agent system prompt |
| `team` | `.polyglav/memory/teams/<name>.md` | After a team run | Into every stage brief |
| `job` | `.polyglav/memory/jobs/<name>.md` | After a job run | Into the run's system prompt |

Files are plain Markdown and human-editable. Reads fall back to the older locations (`.polyglav/jobs/<name>.memory.md`, `.polyglav/teams/<name>/memory.md`) so existing memories keep working, and writes always go to the new path. Writes are atomic (a `.tmp` file replaces the target).

## Automatic and manual

Each scope is refreshed by summarizing the run through the same compaction path as `/compact`, seeded with the previous memory so facts carry. A failed summarizer leaves the previous memory in place.

- `memory` (default `true`) enables or disables all scopes.
- `memory_scopes` (default all true) toggles a scope on or off individually.
- `memory_max_chars` (default `2000`) caps the summary text injected into a prompt or brief.
- `/memorize` summarizes the active run into the active role's memory, and `/memorize <role|team|job> <name>` writes a named scope.

See [config.md](config.md) for the keys and [teams.md](teams.md) / [jobs.md](jobs.md) for the pipeline and scheduler behavior.
