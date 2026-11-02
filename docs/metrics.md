# Metric runs

`polyglav metrics` runs a task through the headless agent loop and writes one machine-readable record of what happened. The record is the measurement substrate: it carries per-round context size and composition, tool and edit accesses tagged with evidence identifiers, compaction events, probe answers, and cost. The metric formulas and the goal evidence stay outside the instrument, in the task description and the probe oracle.

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
  "compact": {"auto": true, "at": 0.85, "before": 3, "keep": 1, "window": 200000},
  "seed": 0,
  "temperature": 0.0
}
```

- `id` is required. `prompt` is required for `single`, and `turns` is required for `multi`.
- `files` are written into the worktree before the run.
- `tool_permission` merges over the metric defaults (`read`, `list`, `web`, and `edit` allowed, `bash`, `mcp`, `call`, `delegate`, and `ask` denied).
- `evidence` declares the identifiers and needles the instrument looks for in tool results, edits, context blocks, and probe answers.
- `goal_evidence` is the task's goal set G. It is copied into the record as input metadata, not computed by the instrument.
- `probes` are checkpoint questions. `canonical` holds the accepted answers, and `at_turn` selects the turn after which the probe runs. In `single`, every probe runs after the one turn. A probe turn denies every tool, so recall comes from the context rather than a re-read.
- `compact` overlays the automatic compaction settings for the run.
- `temperature` defaults to the project config.

## Record

Each run writes `.polyglav/metrics/runs/<task>_<condition>_<stamp>.json` and prints a table or the JSON depending on `--output`.

```json
{
  "task_id": "read-and-edit",
  "condition": "single",
  "run_end": {"reason": "completed", "status": "ok", "turns": 3, "main_turns": 1, "rounds": 14, "main_rounds": 12},
  "goal_evidence": ["e1"],
  "rounds": [
    {"turn": 1, "round": 1, "probe": "", "ctx_tokens": 12000,
     "input_tokens": 10000, "cache_read_tokens": 2000,
     "completion_tokens": 500, "status": "tool_calls", "cost": 0.01,
     "context_blocks": [
       {"kind": "tool", "turn": 1, "part": 4, "tokens": 800, "evidence_ids": ["e1"]}
     ]}
  ],
  "tool_calls": [
    {"name": "file_read", "turn": 1, "round": 2, "part": 4,
     "category": "read", "result_tokens": 800, "evidence_ids": ["e1"],
     "content_hash": "ab12cd34ef56", "is_error": false, "probe": ""}
  ],
  "edits": [
    {"turn": 1, "round": 5, "path": "src/app.py", "category": "edit",
     "result_tokens": 120, "evidence_ids": ["e1"], "content_hash": "..."}
  ],
  "compactions": [
    {"turn": 1, "round": 7, "boundary_turn": 1, "boundary_part": 12,
     "auto": true, "reason": "threshold", "context_before": 168000,
     "context_after": 42000, "usage": {"prompt_tokens": 168000,
     "completion_tokens": 900}, "cost": 0.02}
  ],
  "probes": [
    {"id": "p1", "after_turn": 1, "probe_turn": 2,
     "question": "What was DEBUG before the edit?", "answer": "true",
     "correct": true, "checkpoint": "after-edit", "evidence_ids": ["e1"]}
  ],
  "cost": {"input": 12000, "output": 500, "cache_read": 2000, "total": 0.01}
}
```

The record carries the fields the metrics need:

- `rounds` carries `ctx_tokens` (input plus cache-read tokens), `input_tokens`, `cache_read_tokens`, `completion_tokens`, `status`, `cost`, and the per-request `context_blocks` with `kind`, `turn`, `part`, `tokens`, and the matched `evidence_ids`.
- `tool_calls` and `edits` carry `turn`, `result_tokens`, `evidence_ids`, and `content_hash`. `result_tokens` and block tokens use the same chars/4 counter for every run.
- `compactions` carries the boundary, the automatic or manual reason, the summarization usage, and the context size before and after.
- `probes` carries `correct` and `checkpoint`, and the raw answer for re-scoring.
- `run_end` carries the status and reason, so a run that stops early is distinguishable from one that completes.
- `cost` aggregates the per-round and summarization usage through `cost.rates`.

The instrument does not compute CRR, CEF, GSD, CTx, or PER. It writes the inputs: `goal_evidence` and the probe oracle come from the task description, and the context composition comes from the engine observer.

## Testing

`tests/test_metrics.py` covers the task model, evidence matching, content hashing, probe scoring, single and multi runs, compaction records, cost aggregation, discovery, and the list command. `tests/test_cost.py` covers the rate model. The engine side is covered by `tests/test_engine_observer.py` and `tests/test_auto_compact.py`.
