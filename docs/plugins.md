# Plugins

Plugins extend Polyglav with **tools**, **providers**, **slash commands**, and **services** without changing the core. The core stays stdlib-only. Third-party dependencies live inside the plugin and are imported lazily, so they only matter when you install and use that plugin.

## Installation locations

| Root | Scope | Precedence |
|------|-------|------------|
| `polyglav.plugins.bundled` | **bundled** with polyglav (shipped in the package) | lowest |
| `~/.config/polyglav/plugins/` | global, all projects | middle |
| `.polyglav/plugins/` | local to a project | highest (wins on name collision) |

First-party plugins ship with polyglav and are listed in the default `plugins` config, so they are active out of the box. `polyglav-core-web` provides `web_search` and `web_fetch`. `polyglav-core-webhook` provides the job report-back connector (`report.webhook`). `polyglav-core-fs` provides `file_read`, `list_dir`, `file_write`, `glob`, and `grep`. `polyglav-core-exec` provides `run_command`. `polyglav-core-mcp` provides the MCP client (`mcp_connect`/`mcp_list`/`mcp_disconnect`) and server (`polyglav mcp` and `POST /mcp`). See [mcp.md](mcp.md). `polyglav-core-eval` provides the eval fixture catalog for `polyglav eval`. See [eval.md](eval.md). `polyglav-core-edit` provides `file_edit`, `polyglav-core-git` provides `git`/`git_commit`, `polyglav-core-dev` provides `code_test`/`code_lint`/`code_format`, and `polyglav-core-onboarding` runs first-run project setup (`/onboard`). The vendor providers ship as bundled plugins too (`polyglav-core-ollama`, `polyglav-core-openai`, `polyglav-core-groq`, `polyglav-core-anthropic`, `polyglav-core-opencode`). See [providers.md](providers.md). They behave like any other plugin but cannot be uninstalled or updated, since they version with polyglav. Remove a name from `plugins` (or `/plugins disable`) to stop one loading. A global or local plugin with the same name overrides the bundled one.

## Plugin layout

A plugin is a directory with a `manifest.json`, an entry module, and an optional unit-test suite. Source modules live under `src/`, tests under `tests/` (a bare `.py` file at the root is also accepted, where name = filename and defaults apply):

```
~/.config/polyglav/plugins/web-scraper/
  manifest.json
  src/
    plugin.py          # entry module (manifest "entry" points here)
    helpers.py         # sibling modules, importable by the entry
  tests/
    test_plugins.py    # optional - run by `polyglav plugins test` and the core suite
```

The entry module may sit anywhere under the plugin directory. The `manifest.json` `"entry"` key is a path relative to the plugin root (default `plugin.py`). Sibling imports resolve from the entry module's directory, so a `src/` layout works like a flat one.

## Manifest

```json
{
  "name": "polyglav-web-scraper",
  "version": "0.3.1",
  "description": "Full-page scraping with links and structure",
  "polyglav_version": ">=0.12.0,<1.0",
  "python": ">=3.10",
  "entry": "plugin.py",
  "requires": ["beautifulsoup4", "lxml"],
  "provides": {"tools": ["scrape_page"], "providers": [], "commands": ["/scrape"]},
  "source": "https://github.com/example/polyglav-web-scraper"
}
```

| Key              | Default       | Description |
|------------------|---------------|-------------|
| `name`           | *(required)*  | Plugin name, also the install directory name |
| `version`        | `"0.0.0"`     | Plugin version |
| `description`    | `""`          | Shown in `/plugins` and `polyglav plugins list` |
| `polyglav_version` | `""`          | Semver range the plugin is compatible with (`>=0.12.0,<1.0`). Incompatible plugins are skipped at load |
| `python`         | `""`          | Minimum/maximum Python, same range syntax (`>=3.10`) |
| `entry`          | `"plugin.py"` | Module to load, relative to the plugin directory (may point into `src/`) |
| `requires`       | `[]`          | Third-party packages, metadata for status and `--deps` install, never imported by the core |
| `provides`       | `{}`          | Declared tools/providers/commands for `/plugins` display |
| `source`         | `""`          | Origin recorded on install, used by `update` |

## Entry contract

The entry module may define any of nine hooks (all optional):

```python
def register_tools(registry) -> None: ...        # @registry.register(...) - same as core tools
def register_providers(providers) -> None: ...   # providers["name"] = ProviderClass
def register_commands(commands) -> None: ...     # @commands.register(...) - same as core commands
def register_services(services) -> None: ...     # services["name"] = service object for core features
def register_roles(registry) -> None: ...     # registry.add_plugin({...}) - plugin-owned roles
def register_teams(teams) -> None: ...           # register into the TeamRegistry (see swarm.md)
def register_skills(skills) -> None: ...         # skills.add_plugin({...}) - see skills.md
def register_fixtures(fixtures) -> None: ...     # fixtures["id"] = fixture data - see eval.md
def register_startup(hooks) -> None: ...         # hooks.append(callable(chat)) - run once when the REPL starts
```

Plugin tools automatically inherit the tool permission policy, `/tool`, `/help`, query refinement, `noise_tools`, and session logging. The loop never special-cases plugin names. A tool handler may declare a `_config` keyword argument to receive the engine's `Config` (e.g. to read a config key like `tool_max_result_chars`). The registry passes it only when the handler's signature accepts it. It is never exposed to the model. See [tools.md](tools.md).

### Providers

`register_providers` contributes to the same provider set as the core `PROVIDERS` dict: the plugin provider appears in the `/connect` picker, and passing its `DEFAULT_BASE_URL` as a `/connect <url>` argument selects it automatically (see [providers.md](providers.md)). A plugin provider's `DEFAULT_BASE_URL` also makes it a model-ref target (`<name>/<model>`). A provider class may declare `HOST_PATTERNS` (a tuple of URL substrings) so `/connect <url>` auto-detects it from the host (see [Auto-detection](providers.md#auto-detection)). The core `detect_provider()` scans the merged set and prefers the longest matching pattern. The bundled vendor providers (`polyglav-core-ollama`, `-openai`, `-groq`, `-anthropic`, `polyglav-core-opencode`) are plugins themselves, so an external plugin registering a provider with the same name as a bundled one does not override it, because the core `PROVIDERS` registry wins on name conflicts.

### Services

`register_services` lets a plugin power a core feature that is not tool-calling. Two services exist today: web search-then-answer and job report-back. The bundled `polyglav-core-web` registers `services['search']` with `search(query, num)`, `display(query, results)`, and `context(query, results)` methods (without it, that mode reports the service is unavailable instead of erroring). The bundled `polyglav-core-webhook` registers `services['report']` with a `report(payload, config)` method: the scheduler calls it once per completed job run with a `job.run.completed` payload and its `Config`, so the connector reads its own keys (e.g. `report.webhook`) and posts the report. Any plugin can register a `report` service the same way to deliver run summaries elsewhere (email, chat, a local log). See [jobs.md](jobs.md#report-back).

### Roles, teams, and skills

`register_roles(registry)` contributes roles to the `RoleRegistry` via `registry.add_plugin(entry)` (same entry shape as `roles.json`). Plugin roles form an in-memory layer below global and local, so precedence is `plugin < global < local`, and a `roles.json` entry can always override or replace a plugin-provided role. `register_teams(teams)` and `register_skills(skills)` register into the team and skills registries the same way (`teams.add_plugin(...)` / `skills.add_plugin(...)`, entry shapes in [teams.md](teams.md) and [skills.md](skills.md)). The `/roles` list marks plugin roles `(plugin)`. After `/plugins install`/`update`/`uninstall` the running REPL re-applies all three hooks immediately. Tools and commands still activate on the next start.

### Eval fixtures

`register_fixtures(fixtures)` contributes task fixtures to the tool-use evaluation harness. The hook receives a dict of fixture `id` to fixture data (same shape as the JSON fixtures under `.polyglav/eval/`, see [eval.md](eval.md)). Local and global fixture files override plugin fixtures by `id`. The bundled `polyglav-core-eval` plugin ships the default catalog this way.

### Startup

`register_startup(hooks)` appends a `callable(chat)` that the REPL runs once when it starts, after plugins load and before the first prompt. It is the first-run hook: the bundled `polyglav-core-onboarding` plugin uses it to detect an unconfigured project and ask about its purpose and assistant, then writes the local config. A hook that raises is swallowed so one plugin cannot stop the REPL from starting. Only `ChatLoop` runs startup hooks, so headless `run`/`serve` engines never prompt.

### Lazy dependencies

Keep third-party imports **inside** the tool function, not at module top level. A missing dependency then surfaces as a normal tool result with install guidance. Plugin packages are only imported in the process running your configured plugins, and only when their tools are actually called:

```python
def register_tools(registry):
    @registry.register(name='pdf2text', description='Extract text from a PDF',
                       parameters={'type': 'object', 'properties': {'path': {'type': 'string'}},
                                   'required': ['path']})
    def pdf2text(path):
        try:
            from pypdf import PdfReader
        except ImportError:
            return 'Error: pdf2text requires "pypdf" - pip install pypdf'
        ...
```

## Managing plugins

### Config activation

```json
{
  "plugins": ["polyglav-core-web", "polyglav-core-fs", "polyglav-core-exec"]
}
```

- `plugins` is the list of plugins to load. **Empty (`[]`) = all discovered plugins load.** The default config lists the bundled plugins so they are active by default. Remove a name (or `/plugins disable`) to stop one loading.
- `/plugins enable <name>` appends a name. `/plugins install` and `/plugins uninstall` add or remove the name automatically.
- Changes apply on the next start (plugins load once at engine init). `plugins.enabled` / `plugins.deny` from earlier versions are migrated automatically.

### REPL

```
/plugins                          # list plugins
/plugins <name>                   # detail: manifest, deps, status
/plugins enable <name>            # add to the plugins list, applies next start
/plugins disable <name>           # remove from the plugins list, applies next start
/plugins install <git-url|path> [--global] [--deps]
/plugins update <name>            # re-fetch from the recorded source
/plugins uninstall <name>
```

### CLI

The same operations are available headless (e.g. before a CI `polyglav run`):

```
polyglav plugins list
polyglav plugins install <git-url|path> --deps
polyglav plugins update <name>
polyglav plugins uninstall <name>
polyglav plugins test [name]
```

- `install` clones a git URL or copies a local directory into `.polyglav/plugins/` (or `~/.config/polyglav/plugins/` with `--global`), records `source`, and with `--deps` runs `pip install` on the declared `requires`.
- `update` runs `git pull` for remote sources or re-copies a local path.
- `test` runs a plugin's `tests/` unit suite (`--verbose` for per-test output). Without a name it runs every plugin that has one. The core test suite also runs these through `tests/test_plugin_suites.py`.
- Bundled plugins report an error for `update` and `uninstall`. Disable them instead.

## Status

`/plugins` (and `polyglav plugins list`) shows each plugin's name, version, **origin** (`bundled` / `global` / `local`), load status, and unmet `requires`:

- `loaded` - active
- `disabled` - not in the `plugins` list (when it is non-empty)
- `incompatible` - `polyglav_version` or `python` range not satisfied (reason shown)
- `error` - invalid manifest, missing entry module, or the entry module raised while loading

## Security

Plugins are arbitrary Python code that run with your user's privileges. Install only plugins you trust. A plugin's `register_providers` hook runs at load. Its tools run on demand like any built-in tool.

## Future paths

- **Dependency isolation**: today plugin deps install into the same Python environment (lazy imports keep the core clean). Shared-plugin and per-plugin virtualenvs are planned for stronger separation.
- **PyPI source**: the same hooks will be discoverable through `importlib.metadata` entry points, so plugins can be distributed as regular packages.
- **Externalizing bundled plugins**: the bundled `polyglav-core-*` plugins are the migration path for optional features. Web and machine tools now ship through them, and they can be forked or superseded by global/local plugins of the same name.
