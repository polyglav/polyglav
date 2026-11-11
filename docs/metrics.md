# Metric runs

`polyglav metrics` runs a task through the headless agent loop and writes one machine-readable record of what happened. The record is the measurement substrate: it carries per-round context size and composition, tool and edit accesses tagged with evidence identifiers, compaction events, snapshot probe answers, and separate agent and probe costs. The metric formulas and the goal evidence stay outside the instrument, in the task description and the probe oracle.

## CLI

```bash
polyglav metrics --path <project> list
polyglav metrics --path <project> run --task <id> --condition single
polyglav metrics --path <project> run --condition single,multi --output json
```

`--path` sits on the `metrics` command before the subcommand, like `eval` and `jobs`.

## Conditions

- `single` is one long `engine.chat(task.prompt)`. It is the main measurement.
- `multi` is one `engine.chat` per entry in `task.turns`. It is the control condition.
- The difference between the two is itself a finding, so both records carry `condition` and the analysis can pair them by task id.

Each condition runs in its own isolated temp worktree with a throwaway `.polyglav/config.json`, so sessions and files are removed with it. The record is the artifact.

## Task description

A task is a JSON file under `.polyglav/metrics/*.json` or `~/.config/polyglav/metrics/*.json`, merged by id with local winning.

```json
{
  "id": "read-and-edit",
  "description": "Read the source, edit it, then report the value",
  "prompt": "Read src/app.py, change DEBUG to false, then report the old value.",
  "turns": ["Read src/app.py.", "Change DEBUG to false.", "Report the old value."],
  "files": {"src/app.py": "DEBUG = true\n"},
  "tool_permission": {"edit": "allow"},
  "tools_deny": [],
  "evidence": [
    {"id": "e1", "needles": ["DEBUG = true"], "critical": true}
  ],
  "goal_evidence": ["e1"],
  "probes": [
    {"id": "p1", "question": "What was DEBUG before the edit?",
     "checkpoint": "after-edit", "canonical": ["true"], "at_turn": 2}
  ],
  "compact": {"auto": true, "at": 170000, "before": 3, "keep": 1, "window": 1000000},
  "seed": 0,
  "mode": "write",
  "temperature": 0.0,
  "system_prompt": ""
}
```

- `id` is required. `prompt` is required for `single`, and `turns` is required for `multi`.
- `mode` defaults to `read` and is a measurement condition, not the project mode. Set `"mode": "write"` or pass `--mode write` for a task that needs writes.
- `temperature` defaults to `0.0` and comes only from the task. The project temperature is not inherited.
- `system_prompt` defaults to `""` and comes only from the task. The project system prompt is not inherited. The mode instruction still applies.
- `files` are written into the worktree before the run.
- `tool_permission` starts from the mode-aware metric base (`read` denies `edit`, `write` allows it) and merges the environment policy and then the task. `edit` is checked against the merged map, so a read task must explicitly set `edit: deny` when the environment allows it. Any other write-class key explicitly requested by the task under `read` also fails before the run with `metric task '<id>' requests <key> but the effective mode cap is read`.
- `evidence` declares the identifiers and needles the instrument looks for in tool results, edits, context blocks, and probe answers.
- `goal_evidence` is the task's goal set G. It is copied into the record as input metadata, not computed by the instrument.
- `probes` are checkpoint questions. `canonical` holds the accepted answers. Each probe runs against a frozen snapshot, never as a session turn: `baseline` at the first request, `turn` after a turn in `multi` (filtered by `at_turn` when it is above zero), `compaction_before` and `compaction_after` around each compaction, and `final` at the end. The snapshot plus the question goes to the provider directly, so recall comes from the recorded context and the run is not changed. `compaction_before`/`compaction_after` share a `compaction_index`, which gives `GSD_c` per boundary.
- `compact` overlays the automatic compaction settings for the run. Use an absolute `at` value for a stable boundary, for example `170000`. `window` is the context budget passed to `context_window`, not a hard model limit. The budget controls relative thresholds and display, while the agent loop continues until the provider stops it. Set a model-level budget once with `polyglav models context <provider/model> <tokens>`, or set `compact.window` per task.

The task supplies the measurement conditions (`mode`, `temperature`, `system_prompt`, `tool_permission`, `compact`). The environment supplies access (`model`, `base_url`, the environment `tool_permission`, `cost.rates`, modes, and tool lists). The fields are written only to the throwaway worktree config and the record, never to the project config.

## Record

Each run writes `.polyglav/metrics/runs/<task>_<condition>_<stamp>.json` and prints a table or the JSON depending on `--output`.

```json
{
  "task_id": "read-and-edit",
  "condition": "single",
  "run_end": {"reason": "completed", "status": "ok", "turns": 3, "main_turns": 1, "rounds": 14, "main_rounds": 12},
  "goal_evidence": ["e1"],
  "rounds": [
    {"turn": 1, "round": 1, "ctx_tokens": 12000,
     "input_tokens": 12000, "cache_read_tokens": 2000,
     "cache_reported": true,
     "started_at": "2026-11-11T10:00:00.000+00:00",
     "ended_at": "2026-11-11T10:00:03.200+00:00",
     "at": 0.0, "duration": 3.2,
     "completion_tokens": 500, "status": "tool_calls", "cost": 0.01,
     "context_blocks": [
       {"kind": "tool", "turn": 1, "part": 4, "tokens": 800, "evidence_ids": ["e1"]}
     ]}
  ],
  "tool_calls": [
    {"name": "file_read", "turn": 1, "round": 2, "part": 4,
     "category": "read", "path": "src/app.py",
     "arguments": {"path": "src/app.py"}, "arguments_truncated": false,
     "result_tokens": 800, "evidence_ids": ["e1"],
     "content_hash": "ab12cd34ef56", "is_error": false}
  ],
  "edits": [
    {"turn": 1, "round": 5, "path": "src/app.py", "category": "write",
     "result_tokens": 120, "evidence_ids": ["e1"], "content_hash": "..."}
  ],
  "compactions": [
    {"turn": 1, "round": 7, "compaction_index": 1,
     "boundary_turn": 1, "boundary_part": 12,
     "auto": true, "reason": "threshold", "context_before": 168000,
     "context_after": 42000, "usage": {"prompt_tokens": 168000,
     "completion_tokens": 900}, "cost": 0.02}
  ],
  "probes": [
    {"id": "p1", "phase": "baseline", "after_turn": 0,
     "compaction_index": 0, "question": "What was DEBUG before the edit?",
     "answer": "true", "correct": false, "checkpoint": "after-edit",
     "ctx_tokens": 2000, "usage": {"prompt_tokens": 2000},
     "cost": 0.0002, "evidence_ids": []},
    {"id": "p1", "phase": "compaction_before", "after_turn": 1,
     "compaction_index": 1, "question": "What was DEBUG before the edit?",
     "answer": "true", "correct": true, "checkpoint": "after-edit",
     "ctx_tokens": 168000, "usage": {"prompt_tokens": 168000},
     "cost": 0.0168, "evidence_ids": ["e1"]},
    {"id": "p1", "phase": "compaction_after", "after_turn": 1,
     "compaction_index": 1, "question": "What was DEBUG before the edit?",
     "answer": "true", "correct": true, "checkpoint": "after-edit",
     "ctx_tokens": 42000, "usage": {"prompt_tokens": 42000},
     "cost": 0.0042, "evidence_ids": ["e1"]}
  ],
  "cost": {
    "input": 12000, "output": 500, "cache_read": 2000, "total": 0.01,
    "probe": {"input": 212000, "output": 40, "cache_read": 0, "total": 0.0212},
    "total_including_probe": 0.0312
  },
  "instrument": {
    "name": "polyglav", "version": "0.52.0", "package_version": "0.52.0",
    "commit": "a2e8d96", "source_hash": "ab12cd34ef56",
    "system_prompt_hash": "12ab34cd56ef", "tools_hash": "ef56ab12cd34",
    "python": "3.14.6", "platform": "macOS-..."
  },
  "settings": {
    "mode": "write", "cap": "write",
    "tool_permission": {"read": "allow", "list": "allow", "web": "allow",
                        "edit": "allow", "bash": "deny", "mcp": "deny",
                        "call": "deny", "delegate": "deny", "ask": "deny"},
    "tools.allow": [], "tools.deny": [],
    "compact_auto": true, "compact_at": 170000, "compact_before": 3,
    "compact_keep": 1, "context_window": 1000000, "temperature": 0.0,
    "max_tokens": 8192
  },
  "artifacts": {
    "patches": [
      {"turn": 1, "round": 5, "path": "src/app.py", "patch": "...",
       "bytes": 120, "lines": 4}
    ]
  }
}
```

The record carries the fields the metrics need:

- `rounds` carries `ctx_tokens` (the total input context, which equals `prompt_tokens` when usage is present), `input_tokens` (the same total), `cache_read_tokens` (the cached subset of `input_tokens`), `cache_reported`, `completion_tokens`, `status`, `cost`, `started_at`, `ended_at`, `at`, `duration`, and the per-request `context_blocks` with `kind`, `turn`, `part`, `tokens`, and the matched `evidence_ids`.
- `tool_calls` and `edits` carry `turn`, `result_tokens`, `evidence_ids`, and `content_hash`. Tool calls also carry `path`, the parsed `arguments`, and `arguments_truncated` when the arguments exceed 2000 characters. `result_tokens` and block tokens use the same chars/4 counter for every run.
- `compactions` carries the boundary, `compaction_index`, the automatic or manual reason, the summarization usage, and the context size before and after.
- `probes` carries `phase`, `after_turn`, `compaction_index`, `ctx_tokens`, `usage`, `cost`, `correct`, `checkpoint`, and the raw answer for re-scoring. `compaction_before` and `compaction_after` share an index.
- `run_end` carries the status and reason, so a run that stops early is distinguishable from one that completes.
- `cost` aggregates the per-round and summarization usage through `cost.rates`. `cost.total` is the agent cost, `cost.probe` is the measurement cost, and `cost.total_including_probe` is the sum. `KJE` uses `cost.total`, not the probe share.
- `instrument` identifies the build: `version`, `package_version`, best-effort `commit`, always-present `source_hash`, `system_prompt_hash`, `tools_hash`, `python`, and `platform`. Without `.git`, `commit` is empty and `source_hash` plus `package_version` identify the installed source. `system_prompt_hash` hashes the sent blocks in order (`summary`, `instructions`, `system`, `plan`, `todo`), and `tools_hash` hashes the ordered tool names and descriptions.
- `settings` records the run's effective configuration: `mode`, `cap`, `tool_permission`, `tools.allow`, `tools.deny`, `compact_auto`, `compact_at`, `compact_before`, `compact_keep`, `context_window`, `temperature`, and `max_tokens`. `tool_permission` is the map after the mode cap, so a permissive environment policy under `read` shows the write keys as `deny`.
- `artifacts.patches` stores every edit output with `turn`, `round`, `path`, the `patch` text, `bytes`, and `lines`, so `R1` and diff size can be computed without re-reading the session.

OpenAI-compatible usage reports `prompt_tokens` as the total input, with cache reads included as `prompt_tokens_details.cached_tokens`. `cache_reported` separates a reported zero from a provider that omits the field. The convention was verified against the `opencode-go` DeepSeek endpoint, where a warm request reported `prompt_tokens` 4036 with `cached_tokens` 3840. A native provider that reports input and cache reads separately must normalize them in the provider layer before they reach the instrument.

`started_at` and `ended_at` are millisecond UTC stamps. `at` is the monotonic start offset in seconds from the recorder start, and `duration` is the request time. The idle gap before a round is `at - (previous.at + previous.duration)`, so a cache expiry can be separated from a compression effect.

The instrument does not compute CRR, CEF, GSD, CTx, or PER. It writes the inputs: `goal_evidence` and the probe oracle come from the task description, and the context composition comes from the engine observer. `GSD` compares `baseline` with `final`; `GSD_c` compares `compaction_before` with `compaction_after` at the same `compaction_index`.

## Testing

`tests/test_metrics.py` covers the task model, execution settings and preflight, evidence matching, content hashing, probe scoring, single and multi runs, compaction records, cost aggregation, discovery, and the list command. `tests/test_cost.py` covers the rate model. The engine side is covered by `tests/test_engine_observer.py` and `tests/test_auto_compact.py`.
