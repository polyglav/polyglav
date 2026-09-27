# Tool-use evaluation harness

`polyglav eval` measures how well a model uses the registered tools. It runs task fixtures through the same headless agent loop as `polyglav run` and reports metrics per fixture and across the suite, so tool descriptions and schemas can be tuned against measured behavior, and providers compared side by side.

## CLI

```bash
polyglav eval --path <project> list        # list discovered fixtures
polyglav eval --path <project> run         # run the suite, print the metrics table
polyglav eval --path <project> run --fixture grep-symbol
polyglav eval --path <project> run --provider openai --model gpt-4o --output json
polyglav eval --path <project> run --compare ollama,openai
```

The `--path` flag sits on the `eval` command before the subcommand, like `jobs` and `fleet`.

Each fixture runs in its own isolated temp worktree. Its `files` are written there, a throwaway `.polyglav/config.json` carries the connection and permission settings, and the process changes into the worktree for the turn so relative tool paths resolve. Sessions are throwaway and deleted with the worktree. The engine uses `HeadlessUI(auto='allow')`, so ask-gated tools run without prompting.

Tool permissions default to `read`/`list`/`web` allowed and `edit`/`bash`/`mcp` denied. A fixture may override with its own `tool_permission` and `tools_deny`.

## Metrics

Per fixture:

- `trace` - the executed tool calls `[{name, arguments}]`.
- `names` - the tool-name sequence.
- `accuracy` - 1 when `names` equals the fixture's `expected` sequence exactly.
- `pass` - the declarative verifier result.
- `calls` - total tool calls.
- `redundant` - count of duplicate identical `(name, arguments)` invocations.
- `errors` - engine errors plus tool results starting with `Error`.
- `tokens` - `total_tokens` from provider usage (prompt + completion fallback).
- `status` - the turn status (`ok`, `truncated`, `error`, `cancelled`).

The suite summary averages accuracy and pass rate and totals calls, redundant calls, errors, and tokens. `--compare P1,P2` runs the same suite once per provider and prints a side-by-side summary.

## Fixtures

A fixture is a JSON file describing a task, optional worktree files, the expected tool trace, and a declarative verifier. Fixtures are discovered from three sources, merged by `id` with local winning: the bundled `polyglav-core-eval` plugin, `~/.config/polyglav/eval/*.json` (global), and `.polyglav/eval/*.json` (local).

```json
{
  "id": "read-file-lines",
  "description": "Read a file and report its line count",
  "task": "Read src/app.py and report how many lines it has.",
  "files": {
    "src/app.py": "import sys\n\ndef main():\n    return 0\n"
  },
  "expected": ["file_read"],
  "verifier": {
    "must_include": ["file_read"],
    "avoid": ["run_command"],
    "max_calls": 2
  }
}
```

Fields:

- `id` and `task` are required. Without a file-level `id`, the filename stem is used.
- `files` maps relative paths to content, provisioned into the worktree before the turn.
- `expected` is the ordered tool-name sequence used for the accuracy metric.
- `verifier` is a declarative pass/fail check, all optional:
  - `exact` - the name sequence must equal this list.
  - `must_include` - every listed tool name must appear.
  - `avoid` - none of the listed tool names may appear.
  - `max_calls` - at most this many tool calls.
  - `min_calls` - at least this many tool calls.
  - `args` - for each `{tool: {param: value}}`, at least one call to that tool must pass those arguments.
- `tool_permission` merges over the eval defaults (`category: action`), and `tools_deny` appends name-level denials.

## Bundled fixtures

The `polyglav-core-eval` bundled plugin contributes a small catalog that exercises the fs tools against provisioned worktrees:

- `read-file-lines` - read a file, report its line count.
- `find-then-read` - locate a file by `glob`, then read it.
- `list-directory` - list a directory tree.
- `grep-symbol` - find where a symbol is defined.
- `page-large-file` - page through a large file with `offset`/`limit`.

The catalog is contributed through the `register_fixtures(fixtures)` plugin entry hook, which takes a dict of fixture id to fixture data. Any plugin can ship its own fixtures the same way, and local files override plugin fixtures by `id`.

## Testing

`tests/test_eval.py` covers the fixture model, verifier evaluation, metric computation (accuracy, redundant, errors, tokens), fixture discovery and precedence, and the aggregation. The suite is driven with a mock provider, so it runs without network or an API key. The `polyglav eval` CLI is covered in `tests/test_cli.py`, and the `register_fixtures` hook in `tests/test_plugins.py`.