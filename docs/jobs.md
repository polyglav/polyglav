# Scheduled and durable jobs

`polyglav jobs` turns the one-shot agent loop into a durable workflow engine. `polyglav run` is a single turn. A job is a named task that adds scheduling, retries with backoff, approvals, a user-in-the-loop status model, and an append-only run history, stored as a file so it survives daemon restarts.

## Job store

Jobs live in `.polyglav/jobs.json` next to the sessions, one register per worktree (same rule as roles). The file is plain JSON and the last writer wins, so run one scheduler per `.polyglav`. Removing a job removes only its definition, while its sessions stay as the append-only log of every run. The register keeps the most recent 100 runs. The full transcript stays in the session file.

```json
{
  "jobs": [
    {
      "name": "nightly_report",
      "schedule": { "cron": "0 2 * * *" },
      "prompt": "Summarize today's operations logs into a short report.",
      "session": "",
      "mode": "plan",
      "type": "researcher",
      "system_prompt": "",
      "retries": 3,
      "backoff": 60,
      "timeout": 0,
      "require_approval": false,
      "task_file": "jobs/nightly_report.md",
      "enabled": true,
      "status": "approved",
      "created_at": "2026-08-26T08:00:00+00:00",
      "next_run_at": "2026-08-27T02:00:00+00:00",
      "last_run_at": "",
      "history": []
    }
  ]
}
```

## Status model

A job is a user-gated workflow, not a blind timer. `waiting_approval` is the parked state of `require_approval` jobs (see below):

```text
proposed > approved > executing > verified | failed
```

- `add` creates a `proposed` job that does not run until approved. `approve` marks it `approved`. `reject` returns it to `proposed` and disables it.
- The scheduler or a manual `run` sets it to `executing`, then `verified` on success (`ok` or `truncated` turn) or `failed` after retries are exhausted.
- `enable` / `disable` / `stop` toggle the `enabled` gate independently. A job runs only when `enabled` and its status is `approved`, `verified`, or `failed`. A manual `run` acts as an approval: a successful `proposed` job becomes `verified` and is then scheduled normally.

Every run (each retry attempt included) is appended to the job's `history` with start/finish times, status, reason, duration, session, the assistant output (capped), and the attempt number. The register saves after each attempt, so a daemon killed mid-retry leaves a correct trail the next start can pick up.

## Schedules

A job has exactly one schedule:

- **cron** - a 5-field expression `minute hour dom month dow`. Fields support `*`, `*/step`, `a-b`, `a-b/step`, and `a,b,c` lists. `dow` accepts `0` (Sunday) through `7` (also Sunday). The two day fields are restrictive: both must match (a restricted `dom` and `dow` do not OR together, unlike some cron variants). The parser is stdlib-only and deterministic. `next run` is always computed strictly after the previous run, so a scheduler that is down does not catch up on missed windows.
- **interval** - seconds between runs, minimum 60. `next run` is `interval` seconds after the previous run finishes.
- **at** - a one-shot ISO datetime (e.g. `2026-08-27T02:00:00Z`). The job disables itself after it runs.

## Job task file

A job is defined by its task, not a one-line prompt. Use `--file` to link a Markdown task file describing what has to be done:

```bash
polyglav jobs add nightly --file jobs/nightly-report.md --cron "0 2 * * *"
```

- **`--prompt` becomes optional** - `--file` alone is enough (at least one of `--prompt` / `--file` is required). Given both, `--prompt` is the short per-run trigger on top of the task file.
- When `--file` is omitted, the default path is `.polyglav/jobs/<name>.md`. A file missing at `add` time is **created from a template** (`# <name>` / `## Task` / `## Done when` / `## Notes`) to fill in.
- The job stores the path and **stays linked**: the file is re-read at the start of every run, so editing the `.md` changes the job, with no re-adding and no restart.
- **`polyglav jobs edit <name>`** (also `/jobs edit <name>`) opens the task file in `$EDITOR` (creating the template first if needed). `polyglav jobs show <name>` prints the stored path.
- Paths under the worktree are stored relative to it. Absolute paths stay absolute. A task file missing at run time fails that run with a clear `task file not found` reason, so a broken link is never silently ignored.

At run time the system prompt is composed of `role.system_prompt` (if a role is set), the task file contents (`## Job task`), `--system-prompt`, and the run memory (`## Run memory`, below). The engine's mode instruction is appended last. With none of them set, a generic recurring-job prompt is used.

## Run memory

Every run is summarized into the job's rolling memory, so the next run knows what happened before without a growing session file:

- After each run (successful or failed) the scheduler summarizes it through the same compaction path as `/compact` (seeded with the previous memory so context carries) and writes the result to **`.polyglav/memory/jobs/<name>.md`** atomically. If the summarize call fails, a short fallback of `Run <ts>: verified|failed` plus the first part of the output or error is stored instead.
- The memory file is **injected into the next run** as the `## Run memory` system prompt block. A compact, bounded record, never the whole history.
- `polyglav jobs show <name>` prints the memory file path and a preview. Read or hand-edit the `.md` like the task file (the next run uses whatever is there). A memory file that stops being summarized stays stale, but it never breaks a run.

## CLI reference

```bash
polyglav jobs list                                # table of jobs and next runs
polyglav jobs status                              # runtime summary (fired count, last error, uptime)
polyglav jobs show <name>                         # definition + full run history
polyglav jobs add <name> --cron "0 2 * * *" --prompt "..." [options]
polyglav jobs add <name> --interval 3600 --file jobs/<name>.md [options]
polyglav jobs add <name> --at 2026-08-27T02:00:00Z --prompt "..." [options]
polyglav jobs approve <name>                      # proposed -> approved (or arm the next run)
polyglav jobs reject <name>                       # proposed, disabled
polyglav jobs enable <name> / disable <name>      # toggle the enabled gate
polyglav jobs stop <name>                         # same as disable - stop it now
polyglav jobs edit <name>                         # open/ create the task file in $EDITOR
polyglav jobs remove <name>                       # definition only. Sessions stay
polyglav jobs run <name> [--no-retry] [--verbose] # run now, apply retries, print result
polyglav jobs daemon [--tick 15] [--quiet]        # scheduler loop, Ctrl-C to stop
```

`polyglav jobs status` is the journalctl-style runtime view: per job it shows state, times fired (ok/failed), last error, next run, uptime since creation, and for `require_approval` jobs whether the next run is approved or waiting. The same surface is available in the REPL as `/jobs` (add, approve, disable, enable, list, reject, remove, run, show, status, stop).

`add` options:

| Flag | Meaning |
|------|---------|
| `--prompt` | Optional short per-run trigger. Required only when `--file` is not given |
| `--file` | Markdown task file describing the job (default `.polyglav/jobs/<name>.md`, template-created if missing). Linked, so edits apply on the next run |
| `--cron` / `--interval` / `--at` | Exactly one schedule (required) |
| `--session` | Stable session name. Default is a fresh per-run `job_<ts>_<id>` file |
| `--mode` | Mode override (`plan`, `build`, or custom) |
| `--provider` / `--model` | Provider / model overrides |
| `--role` | Apply a role's system prompt, model, and tool permissions |
| `--system-prompt` | System prompt describing the job. Without it or a role, a generic recurring-job prompt is used |
| `--tools-deny NAME` | Deny a tool (repeatable) |
| `--tool-permission category=action` | Permission override, e.g. `bash=allow` (repeatable) |
| `--retries N` | Retries after a failed attempt. Default `3` |
| `--backoff SECONDS` | Base backoff, doubled per retry. Default `60` |
| `--timeout SECONDS` | Max seconds for one attempt. `0` (default) = no cap |
| `--require-approval` | Arm one run per approve, so every run parks in `waiting_approval` until a user approves it |
| `--approve-model` | Approve the model referenced by `--role` (or `--model`) so the headless job may use it without prompting |
| `--approval auto` | Start `approved` instead of `proposed` |

## User in the loop

There are three distinct gates, from coarsest to finest:

1. **Arm / disarm (before any run)** - `add` starts `proposed`. `approve` arms it once, `stop`/`disable` disarms it. This is the baseline gate everyone uses.
2. **Per-run approval (`--require-approval`)** - for when "something has to be decided" about *this* run, not arm-or-disarm for all time. Each run parks in `waiting_approval`: the daemon will not fire it, `polyglav jobs status` shows `WAITING for approve`, and `polyglav jobs approve <name>` (or `/jobs approve`) arms exactly the next run. It parks again after the run. `reject` clears the grant. `run` still overrides and executes now.
3. **Mid-run blocking approval (tool-level, planned)** - an `ask` tool inside a running job pauses the run in place and waits for a user reply before resuming on the same session. The deepest "decide during the task" model, tracked separately in [TODO.md](../../TODO.md): it needs resumable mid-run state, a wait loop inside the run, and a transport to deliver the ask and return the answer (the planned webhook/email/Telegram connectors drive the same user API).

A job runs with `HeadlessUI(auto='deny')` on an unattended engine, the same posture as `polyglav serve`, plus parking. So until mid-run blocking is implemented, an `ask target='user'` inside a run is not paused and does not hang: it parks as a pending request in `.polyglav/asks.json` (returned to the agent as `[parked] Ask #<id> ...`), the run continues or finishes, and the user answers later with `/asks answer <id> <text>` or `POST /asks/<id>/answer` on `polyglav serve`, which injects the answer into the run's session for the next run or continuation. Give a job its permissions up front (`--tool-permission bash=allow`, a role carve, or a `--tools-deny` list) and it will not need mid-run interruption. A sub-agent inside a job can still use `ask target='caller'` for a decision from the job's model mid-run. `timeout` runs the attempt on a daemon thread and abandons it if it overruns. The abandoned thread may still write to the shared session, so inspect a timed-out job with `polyglav jobs show <name>` before a manual retry.

## Report-back

A finished or failed run is surfaced in-band and, optionally, out-of-band, so an unattended supervisor does not have to be watched:

- **`polyglav jobs status` / `/jobs status`** prints a `last run:` line per job (status, duration, reason, session) under the run counts.
- **`polyglav jobs run` / `/jobs run`** print the run's result plus a `summary:` line from the run memory written after the run.
- **Delegated and team runs** show their outcome in the REPL sub-footer (`status session` after the duration/token footer, when `delegate_echo` is on).
- **Out-of-band**: after each completed run the scheduler dispatches one `job.run.completed` event to a registered `report` service. The bundled `polyglav-core-webhook` plugin implements it: set `report.webhook` to a URL and it POSTs the JSON payload (job, status, duration, reason, session, timestamps, content, worktree, memory summary, and parked asks). A pending ask parked during the run is flagged by id and origin, so a night that "finished but needs you" is visible in the report. Empty `report.webhook` is a no-op. Service failures are logged and never fail the run. A report fires once per completed run (the final status after retries), not per attempt. Per-job destinations are future work (TODO).

## Supervisor overnight run

A standing supervisor job is the overnight surface: job engines run unattended (they never read stdin), park user questions as asks, and report back. One command scaffolds it:

```bash
polyglav jobs add-supervisor night --interval 86400 --task "Lead the work."
# creates .polyglav/jobs/night.md from a supervisor template, role=leader, approved
polyglav jobs daemon            # runs it on schedule
polyglav jobs run night         # or run it once now
```

The job role is `leader`, whose `grant_permission` lets it delegate categories it denies itself (bash, web) to team stages, and whose `ask_policy` routes decisions to the user (parking them under unattended mode). The task file (`.polyglav/jobs/<name>.md`) carries the standing goal, and the next run picks up any edit. The model the job uses must be approved (`/model`, or `--approve-model` when a role or team references a model).

While it runs:

- `/asks` (or `GET /asks` on `polyglav serve`) lists parked asks. `/asks answer <id> <text>` (or `POST /asks/<id>/answer`) marks one answered and injects the answer into its origin session.
- `polyglav jobs status` shows the last run plus any parked asks. `polyglav jobs run`/`/jobs run` print the run summary and parked asks.
- With `report.webhook` set, each completed run is POSTed out-of-band, so a finished or failed night is reported without the terminal being watched.

Resuming a parked ask: the ask lives in the run's sub-session. Answer it, then continue that session with `polyglav run --session-id <origin> "continue"` (or `/session load <origin>` in the REPL).

## Session files per run

The **compact memory** is the run-memory file ([Run memory](#run-memory)): a rolling summary injected into every run to keep the model oriented across runs. Session files are the per-run audit:

- **By default each run gets a fresh session file**: `job_<YYYYMMDD>_<HHMMSS>_<id>.json` (e.g. `job_20260826_110230_7f3k2a.json`), distinct from interactive (`ses_...`) and delegation (`sub_...`) sessions. The `<id>` is the same six-character session id the other generated sessions use. No single file grows forever. Every run is a complete, self-contained log. A collision re-mints the id. Retries within one run share that run's file (the retry sees the failed attempt's context).
- **`--session <name>` opts into a stable, growing session** for one continuous transcript.
- The job register keeps the most recent 100 runs, each recording its session file.

## How a run executes

Each attempt builds a fresh headless `Engine` from the job's overrides, uses the run's session file (fresh `job_<ts>_<id>`, or the `--session` override), and calls `chat()` once. After the run it is summarized into the memory file for the next run, so continuity lives there rather than in a growing session. A retry continues from the failed attempt's trail (same run's session file) with a "Previous attempt failed. Retry this job" header. `polyglav jobs run --verbose` streams the live turn (tokens to stdout, tool activity to stderr) before the summary. `polyglav jobs run` prints the final answer headlessly.

## Scheduling semantics

The daemon (`polyglav jobs daemon`) wakes on the `--tick` interval (default 15s), runs every due, runnable job sequentially, then sleeps. Jobs are single-threaded: one at a time, in name order. Concurrent execution is future work. `next_run_at` is the single source of truth, computed when a job is added and after each run, and a `next_run_at` in the past makes a job due immediately. A missed window is not backlogged: after any run the next run is recomputed strictly after the current time (or the run's finish for interval schedules), so a scheduler stopped overnight runs the current schedule on wake instead of replaying old ones.

## Session logs

Each run writes a complete append-only log at `.polyglav/sessions/job_<ts>_<id>.json` (or the `--session` override): user prompts, assistant answers, tool calls and results, thinking, errors, and the `permissions` audit array. That is the durable record a `verified` or `failed` status points to. `polyglav jobs show <name>` prints the run history, each run's session file, and the last output. `/sessions export job_<ts>_<id>` renders one run's transcript to Markdown.
