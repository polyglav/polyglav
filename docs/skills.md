# Skills

A skill is a named set of markdown instructions a role can attach: `Role.skills` lists skill names, and when that role runs, each resolved skill's content is injected into its system prompt under a `## Skills` section. Skills are capability instructions distinct from tools and plugins: a role carries them, and the sub-agent reads them.

## Storage

Skills come from three layers, merged like roles and teams: plugin contributions first, then global, then local, with local winning per field:

- **Plugin** - skills contributed by plugins via the `register_skills` entry hook (`registry.add_plugin(...)`, see [plugins.md](plugins.md)). An in-memory layer: never written to `.polyglav/skills/`, refreshed on `/plugins install`/`update`/`uninstall`.
- **Global** - `~/.config/polyglav/skills/<name>.md`.
- **Local** - `.polyglav/skills/<name>.md`.

Each skill is one flat Markdown file: the filename stem is the skill name, the body is the instructions.

## Schema

```markdown
# finders

Find sources and evaluate them. For each finding include the claim,
the source URL, and a one-line reliability assessment.
```

A skill has:

- `name` - the filename stem (`finders.md` -> `finders`), referenced from `Role.skills`.
- `content` - the full file body, injected verbatim into the role's system prompt.
- `description` - optional, defaults to the first line of the content for file-based skills. Plugin contributions may set it explicitly with `tags`.

Plugin contributions use the same entry shape, with an explicit `content` field:

```python
def register_skills(registry):
    registry.add_plugin({'name': 'finders', 'content': '# finders\n\n...'})
```

## Standing and per-invocation skills

`Role.skills` are a role's standing skills, the experience a role always carries. A caller may extend a role for one run with additional skills, so the same reusable agent gains task, technology, stack, or framework instructions without defining a new role:

- `delegate(role, task, skills=[...])` appends the named skills after the role's standing skills.
- A team stage may set `skills`, and `team(name, task, skills=[...])` adds task-wide skills to every stage.

Resolution order is standing skills first, then invocation skills (task-wide before stage-specific), deduplicated by name. Unknown names are skipped silently. Layering skills never changes a role's tool carve.

## Injection

When a role with `skills` runs as a sub-agent (`delegate`), each registered skill's content is appended to the role's system prompt:

```
<role system prompt>

## Skills

### finders

Find sources and evaluate them. ...
```

Missing or empty skills are skipped silently, and a role without skills gets an unchanged prompt. Jobs with `--role` inject the same section (from the global/local file layers, since plugin contributions do not reach the scheduler's preparse, the same rule as plugin roles there). The format is built by `skills_section(registry, names)` in `polyglav.skills`.

## Managing skills

- `/skills` - list skills (name, first-line description, origin), with origins shown as `(local)` / `(global)` / `(plugin)` / `(merged)`.
- `/skills new <name>` - create an empty local skill (edit the created `.md` file, or write one directly).
- `/skills remove <name>` - remove a local skill. Plugin skills cannot be removed (override them locally instead).
- `/skills show <name>` - print the full skill content.

Skills are plain Markdown files. The assistant can save a reusable procedure as a local skill (for example when composing a recurring task), and delegation injects a role's skills into the sub-agent prompt.