# Roles

A role is a named agent definition: a system prompt, an optional model override, and optional skills and per-agent tool permissions. It turns a plain agent into a specialized sub-agent for swarm delegation (see [swarm.md](swarm.md)). Examples: a `researcher` who searches the web and keeps findings, a `writer` who turns findings into prose, a `referencer` who extracts citations into a `.bib` file, and an `editor` who checks text against the original prompt.

## What a role bundles

A role is a single reusable profile carrying several distinct axes of an agent.

| Axis | What it covers | Field |
|---|---|---|
| **Persona** | Identity and behavior - the agent's voice, tone, and communication style | `system_prompt` |
| **Function** | What the agent does - research, writing, review, implementation | `system_prompt` + the role's name and description |
| **Authority** | The scope it may act in - which tools it may use and which are denied | `tool_permission` |
| **Capability** | What it can run on - a model override and attached skills | `model`, `skills` |
| **Expertise** | The domains it is tagged for, used for grouping and filtering | `tags` |
| **Archetype** | A stored, reusable pattern that teams reference as a stage | the registry entry itself |

No roles ship with the package. A fresh install has an empty catalog, and the user or an agent creates roles as a project needs them (the `catalog` tool and `/roles new`). Typical patterns a project builds are a `researcher` that gathers web sources, a `writer` that turns a findings brief into a document, a `code-reviewer` that reviews a change, and a `composer` that designs teams into the catalog. A project that keeps a tuned catalog can commit it under `.polyglav/` so it travels with the repository.

A role carve only needs to declare the write keys it wants to narrow, because read keys are allowed by default and the mode sets the outer bound. For example, a document `writer` might set `edit: allow`, `bash: deny`, `web: deny`, while a `researcher` sets `web: allow` and `edit: deny`.

## Storage

Roles come from three layers, merged exactly like config: plugin, then global, then local, local winning per field:

- **Plugin** - roles contributed by plugins via the `register_roles` entry hook (`registry.add_plugin(...)`, see [plugins.md](plugins.md)). An in-memory layer: never written to any `roles.json`, refreshed on `/plugins install`/`update`/`uninstall`.
- **Global** - `~/.config/polyglav/roles.json`.
- **Local** - `.polyglav/roles.json`.

Merging is field-by-field for the same `name`: an entry overrides only the fields it sets, so an unset field (e.g. no `model`) inherits from the layer below.

Schema (per entry):

```json
{
  "name": "researcher",
  "system_prompt": "You are a web researcher. Gather sources, evaluate them, and report findings.",
  "model": "deepseek-r1",
  "skills": [],
  "tags": ["research", "writing"],
  "tool_permission": { "web": "allow", "delegate": "allow" },
  "grant_permission": { "web": "allow", "delegate": "allow" },
  "ask_policy": { "permission": "auto", "direction": "user" }
}
```

Fields:

- `name` - unique key of the role.
- `system_prompt` - the role's system prompt, injected when it runs.
- `model` - optional. Overrides the caller's model when the role runs, falls back to the caller's when empty. Accepts a `provider/model` ref (e.g. `opencode-go/deepseek-v4-flash`) to pin provider and model together. The model must be approved before the role runs (`delegate`/`/teams run` ask interactively, or pass `--approve-model` headlessly, see [Model refs and approval](providers.md#model-refs-and-approval)).
- `skills` - optional list of standing skill names from the [skills registry](skills.md), resolved and injected into the role's sub-agent system prompt (and jobs with `--role`). A caller may layer additional skills per run through `call`/`delegate` or a team stage, so one reusable role carries a stable identity while each task adds its own instructions.
- `tags` - optional list of tags for grouping and filtering (`/roles list <tag>`). A common vocabulary is `management`, `research`, `writing`, `programming`, `review`.
- `tool_permission` - optional per-agent overrides by permission key. The keys are `bash`, `edit`, `read`, `list`, `web`, `catalog`, `ask`, `handoff`, `offload`, `call`, `delegate`, `mcp`, `vcs` (not tool categories). A category name is normalized on save (`write` -> `edit`, `exec`/`shell`/`cmd` -> `bash`, `search` -> `web`), and an unknown key is rejected with the valid list. The per-agent permission profile.
- `grant_permission` - optional narrowing of the categories this role may hand down to sub-agents. The mode sets the ceiling (write keys are grantable in `write`, denied in `read`), and this only narrows it. It uses the same keys and normalization. See [Delegation and permissions](#delegation-and-permissions).
- `ask_policy` - optional per-role override of the `ask` routing by kind (`permission`/`direction`), merged over the config `ask_policy`. The `direction` route defaults to automatic (the caller for a delegated run, the user at the root). A role that sets `direction: caller` keeps its asks at the caller boundary so the run stays automated, while `direction: user` lets its asks reach the user. See [config.md](config.md#ask_policy).
- `description` - optional short summary, shown by `/roles show` and the `catalog` tool.
- `instructions` - optional Markdown file name under `.polyglav/roles/` (or `~/.config/polyglav/roles/`) that holds the role's long system prompt. It defaults to `<name>.md` when that file exists. The file body becomes `system_prompt`, and its YAML-like frontmatter can fill any field the JSON entry leaves unset. Frontmatter values are JSON (`tags: ["writing"]`, `tool_permission: {"bash": "deny"}`). The JSON entry stays authoritative: a `system_prompt` or field set there wins over the file.

Writing a role through `/roles new` or the `catalog` tool stores the prompt in `.polyglav/roles/<name>.md` and leaves a short entry (with an `instructions` reference) in `roles.json`. The prompt is not copied back into the index, so editing the Markdown body takes effect on the next catalog reload.

## Command

`/roles` manages the registry, and `/role` reports the active role:

- `/roles` - list roles, marking each one's origin (`plugin` / `local` / `global` / `merged`) and tags.
- `/roles list <tag>` - list only roles carrying the tag (e.g. `/roles list programming`). Unknown tags print the known tags.
- `/roles new <name> [system prompt]` - create a role in the local catalog (edit the JSON for full fields, including tags). Using an existing name overrides that role.
- `/roles remove <name>` - remove a role from the local catalog. A plugin role cannot be removed (override it with a local entry instead).
- `/roles show <name>` - show a role's full definition.
- `/role` - show the active run's role and session, so a focused or delegated run is identifiable at a glance.

## Delegation and permissions

`call` resolves its permission from the target role rather than from a single tool-level default:

- A configured role uses its own `tool_permission` overrides. The default for the `call` category is `allow` (a call runs without a prompt). Set `call: "ask"` on a role to confirm each call to it. A role with `call: "deny"` is refused as a call target and is not offered the `call` tool itself. To bar a role from running team pipelines without blocking calls to it, set `delegate: "deny"` instead (the `delegate` category gates only the team pipeline tool).
- A temporary role created only to run a task in parallel defaults to `deny` until you opt in.

Sub-agent permissions are bounded by the caller: the effective carve is the caller's `tool_permission`, narrowed by the role's carve and capped by the caller's `grant_permission` ceiling (see [config.md](config.md#permission-authority)). The ceiling comes from the mode: `write` makes write keys grantable, `read` denies them, and a role or config `grant_permission` can only narrow the result. A role that sets `grant_permission` may delegate categories it does not use itself. For example, a supervisor that denies `edit`/`bash` for itself but allows them in its ceiling can hand them to an `implementer` while never running them. An approved `ask(kind="permission")` request creates a one-shot grant on the asking sub-agent, consumed by the next matching call. A request naming a category (`edit`) grants the whole category, while one naming a tool (`file_write`) grants only that tool. The user may grant `always` for the rest of that sub-agent's run.

## Relationship to /agent, skills, and fleets

- `/agent` is the planned interactive way to pick a role and run with it. Today a role runs directly through the `call` tool (the caller model proposes it, or `/tool call {"role": ..., "task": ...}`), which builds the in-process sub-engine from this catalog.
- Skills (a dedicated registry) are a separate capability layer attached to a role, distinct from tools and plugins.
- A role runs either in-process as a sub-engine (the default for delegation) or as a scoped `polyglav serve` process in a fleet. In-process variants share the caller's privileges, cross-process variants are confined by the target agent's worktree and `tool_permission` (see [fleet.md](fleet.md)).
