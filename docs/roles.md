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

The bundled catalog ships two pre-carved teams plus an `assistant`, a `composer`, and a `leader` role, useful as delegation targets and as templates (see [teams.md](teams.md)). The assistant is the REPL's default root identity, the composer designs and persists teams, and the leader supervises them. All leave `model` and `skills` empty (inheriting the caller's model) and differ mainly in `tool_permission` (`leader` also sets `grant_permission`/`ask_policy`, `composer` sets `ask_policy`):

| role | function | tags | edit | bash | web | read |
|---|---|---|---|---|---|---|
| `assistant` | REPL root: answers small tasks, delegates bigger work to a composer/leader | management | - | - | - | - |
| `code-reviewer` | auditor: reviews a change, returns findings | programming, review | deny | allow | deny | allow |
| `composer` | team composer: designs and persists a team (`catalog` allow, `team` deny) | management | deny | deny | allow | allow |
| `editor` | auditor: checks a document against the prompt and sources | writing, review | deny | deny | deny | allow |
| `leader` | supervisor: coordinates teams and agents, delegates, grants, parks asks | research, writing, programming, review | deny | deny | deny | allow |
| `planner` | decomposes a task into an ordered, verifiable plan | programming | deny | deny | allow | allow |
| `programmer` | implements a change and runs the tests until green | programming | allow | allow | deny | allow |
| `referencer` | resolves citations into a `.bib` file | writing | allow | deny | deny | allow |
| `researcher` | gathers and evaluates web sources, returns findings | research, writing | deny | deny | allow | allow |
| `tester` | writes and runs tests, reports failures | programming | allow | allow | deny | allow |
| `writer` | turns a findings brief into a document, returns file path | writing | allow | deny | deny | allow |

`allow` echoes the caller's category default, `deny` is explicit, and `-` sets no carve (the caller's config applies unchanged). Override any role by creating a local (or global) entry with the same `name`.

## Storage

Roles come from four layers, merged exactly like config: bundled, then plugin, then global, then local, local winning per field. Precedence mirrors bundled plugins (`bundled < plugin < global < local`):

- **Bundled** - the read-only default catalog shipped in the package (`src/polyglav/bundled_roles.json`). Always present, never writable, overridable by any other layer.
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
  "ask_policy": { "permission": "auto", "direction": "human" }
}
```

Fields:

- `name` - unique key of the role.
- `system_prompt` - the role's system prompt, injected when it runs.
- `model` - optional. Overrides the caller's model when the role runs, falls back to the caller's when empty. Accepts a `provider/model` ref (e.g. `opencode-go/deepseek-v4-flash`) to pin provider and model together. The model must be approved before the role runs (`delegate`/`/teams run` ask interactively, or pass `--approve-model` headlessly, see [Model refs and approval](providers.md#model-refs-and-approval)).
- `skills` - optional list of standing skill names from the [skills registry](skills.md), resolved and injected into the role's sub-agent system prompt (and jobs with `--role`). A caller may layer additional skills per run through `delegate`/`team` or a team stage, so one reusable role carries a stable identity while each task adds its own instructions.
- `tags` - optional list of tags for grouping and filtering (`/roles list <tag>`). The bundled set uses a controlled vocabulary: `management`, `research`, `writing`, `programming`, `review`.
- `tool_permission` - optional per-agent overrides of `tool_permission` categories. The per-agent permission profile.
- `grant_permission` - optional ceiling on the categories this role may hand down to sub-agents. As a sub-agent it defaults to the role's own `tool_permission`; bound as the root (`assistant_role`) its `grant_permission` sets the root ceiling, so a read-only assistant can still authorize a team (an explicit config `grant_permission` wins). See [Delegation and permissions](#delegation-and-permissions).
- `ask_policy` - optional per-role override of the `ask` routing by kind (`permission`/`direction`), merged over the config `ask_policy`. See [config.md](config.md#ask_policy).

## Command

`/roles` manages the registry, and `/role` reports the active role:

- `/roles` - list roles, marking each one's origin (`bundled` / `plugin` / `local` / `global` / `merged`) and tags.
- `/roles list <tag>` - list only roles carrying the tag (e.g. `/roles list programming`). Unknown tags print the known tags.
- `/roles new <name> [system prompt]` - create a role in the local catalog (edit the JSON for full fields, including tags). Using an existing name overrides that role.
- `/roles remove <name>` - remove a role from the local catalog. Bundled roles cannot be removed (override them instead).
- `/roles show <name>` - show a role's full definition.
- `/role` - show the active run's role and session, so a focused or delegated run is identifiable at a glance.

## Delegation and permissions

`delegate` resolves its permission from the target role rather than from a single tool-level default:

- A configured role uses its own `tool_permission` overrides. The default for the `delegate` category is `allow` (delegation runs without a prompt). Set `delegate: "ask"` on a role to confirm each delegation to it. A role with `delegate: "deny"` is refused as a delegation target and is not offered the `delegate` tool itself. To bar a role from running team pipelines without blocking delegation to it, set `team: "deny"` instead (the `team` category gates only the `team` tool).
- A temporary role created only to run a task in parallel defaults to `deny` until you opt in.

Sub-agent permissions are bounded by the caller: the effective carve is the caller's `tool_permission`, narrowed by the role's carve and capped by the caller's `grant_permission` ceiling (see [config.md](config.md#permission-authority)). The config ceiling is a built-in allow set (`ask`, `bash`, `edit`, `list`, `read`, `web`), so a caller normally does not need to set one; set `grant_permission: {}` to fall back to the caller's own `tool_permission`, where a role can never grant a sub-agent more than the caller holds. A role that sets `grant_permission` may delegate categories it does not use itself. For example, a supervisor that denies `edit`/`bash` for itself but allows them in its ceiling can hand them to an `implementer` while never running them. An approved `ask(kind="permission")` request creates a one-shot grant on the asking sub-agent, consumed by the next matching call. The operator may grant `always` for the rest of that sub-agent's run.

## Relationship to /agent, skills, and fleets

- `/agent` is the planned interactive way to pick a role and run with it. Today a role runs directly through the `delegate` tool (the lead model proposes it, or `/tool delegate {"role": ..., "task": ...}`), which builds the in-process sub-engine from this catalog.
- Skills (a dedicated registry) are a separate capability layer attached to a role, distinct from tools and plugins.
- A role runs either in-process as a sub-engine (the default for delegation) or as a scoped `polyglav serve` process in a fleet. In-process variants share the caller's privileges, cross-process variants are confined by the target agent's worktree and `tool_permission` (see [fleet.md](fleet.md)).
