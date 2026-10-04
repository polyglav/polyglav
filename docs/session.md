# Sessions

Sessions are complete, append-only conversation logs. Every turn (the user prompt, the agent's thinking, each tool call with its result, and the answer) is persisted as JSON under the project's `.polyglav/sessions/` directory. Entries are never removed. Compaction only trims the provider context, never the log.

## Where sessions live

Each session is one JSON file: `.polyglav/sessions/<name>.json`, next to the local `.polyglav/config.json`.

Names are explicit (`/session new <name>`, `/session load <name>`, `polyglav run --session-id <name>`) or auto-generated as `ses_<timestamp>_<id>`, e.g. `ses_20260817_120000_ab12cd`. The `<id>` is a six-character base36 hash minted at creation and embedded in the name, so an auto session is fully named from the start (no prompt-slug rename).

Session files carry a kind prefix so the kinds stay distinguishable at a glance:

| Prefix | Kind | Example |
|--------|------|---------|
| `job_` | Jobs: one fresh file per run | `job_20260826_110230_7f3k2a.json` |
| `ses_` | Interactive/auto sessions | `ses_20260817_120000_ab12cd.json` |
| `sub_` | Delegation sub-agents | `sub_20260817_120100_cd34ef.json` |

The trailing `<id>` is a six-character base36 hash minted at creation and embedded in the name, so a generated session is fully named from the start (no prompt-slug rename). The `session_id` is the stable run handle: each run mirrors it as `Run.session_id`, `/focus` and `/history` show it, and commands accept it as `#<id>` (`/focus #ab12cd`, `handoff` target `#ab12cd`, `/history --run #ab12cd`, `/print --run #ab12cd`). Resolution is a direct filename glob for `*_<id>.json`, so an id is found without reading every session. The `ses_`, `job_`, and `sub_` kinds carry an id. Explicit names carry no id and are referenced by `session:<name>`. Files written before the `session_name`/`session_id` fields were introduced no longer load (the file is left on disk and stays listed).

Delegation writes each sub-agent's log as its own session: `sub_<ts>_<id>` (`sub_20260817_120100_cd34ef`), with the calling session recorded as `parent_id` rather than in the filename. Job runs use `job_<ts>_<id>`, with the job name still recorded in the job registry and each run's `JobRun.session`. A caller may resume a run or session explicitly with `delegate`/`team` `resume=...` and `context=continue|compact|new`, which appends to that run's own log instead of minting a new one. These live in the same `.polyglav/sessions/` directory and are regular sessions, listed by `/sessions` (annotated with their parent), exportable, and loadable, so caller and sub-agent logs stay separate and complete.

Each session also records the agent `role` that owns it (the bound root role, the delegated role, the team-stage role, or the job role), stamped at creation. That makes a run reconstructable from its log even after the process exits. A plain root or a headless run with no `--role` leaves `role` empty.

Each session also records the Polyglav `version` that created it, so a log says which build wrote it. The version is stamped once at creation and never changes. Files written before the field load with an empty `version` (no backfill).

Session files written before the turn format (flat `messages`) and files written before the `session_name`/`session_id` rename do not load: `read()` returns nothing for them, the file is left untouched on disk, and `/sessions` still lists the name. The turn format is a full cutover, not a compatibility layer.

## Managing sessions

The active session is handled by `/session` (like `/model` for the model). The catalog of saved sessions lives under `/sessions` (like `/models`).

| Command | Purpose |
|---------|---------|
| `/history [n\|all] [--thoughts [all]] [--run <target>]` | Numbered turn index of the active session (default last 10), with an optional dim thinking excerpt and a target selector |
| `/print <n>[.<m>] [--full] [--run <target>]` | Reprint a turn in full, or only its m-th part, capped per part by `print_max_chars` |
| `/session` | Show the active session (name, provider-context message count, context size) |
| `/session new <name>` | Create and switch to a new session |
| `/session load <name>` | Load a session (with compaction offer if it has a summary) |
| `/session save` | Save the current session |
| `/sessions` | List saved sessions |
| `/sessions preview <name>` | Structural preview (turn count, part kinds, tool names) without switching |
| `/sessions delete <name>` | Delete a session |
| `/sessions export <name> [out]` | Export a session to Markdown |
| `polyglav run --session-id <name>` | Load or create a session from headless mode |

The current session auto-saves after every turn and command, so nothing is lost on exit.

`/history` lists the active session's turns as a numbered index, one line per turn: `#<index>  [<status>]  <duration>  <tool count>  <prompt>`. The index is the turn's absolute `index`, so a turn can be named later regardless of the listing limit. `/history 3` shows the last three turns, `/history all` every turn, and `--thoughts` adds a dim first-line excerpt of the turn's thinking (`--thoughts all` prints the full thinking text). `/history --run <#id|#run|role|session:name|name>` reads another run's session without switching focus or the current session: a session id (`#ab12cd`) resolves to a live run first, otherwise the saved `ses_` session, a numeric run id (`#3`) resolves to the live focused run when present, otherwise the saved session, a role resolves to the live run with that role or the saved session, and a name resolves to the saved session (files without the current turn format read as not found).

`/print <n>` reprints the turn with that absolute index: the full turn metadata block (`#index`, status, duration, tool count, `started`/`ended`, model, provider, mode, reasoning, with empty values shown as `-`, so even a command turn is self-describing), then each part: the user prompt, thinking (dim), every tool call with `input` JSON, `output`, `is_error`, and `analysis`, the answer, command records (a compaction summary included), and system notes. `/print <n>.<m>` prints only the m-th part of turn n. Each part's text is capped at `print_max_chars` characters (default 4000) with `... (N more chars, use --full)` appended, and `--full` (or `print_max_chars: 0`) removes the cap. `/print` takes the same `--run <#id|#run|role|session:name|name>` selector as `/history`, resolving through the same rules without switching focus or the current session.

## Exporting to Markdown

`/sessions export <name>` renders any saved session as a Markdown transcript. It reads the persisted log directly (`read()`, not `load()`), so the current session is never switched and the source file is left untouched.

Default output is `.polyglav/exports/<name>.md`, next to the `sessions/` directory. A second argument overrides the path (`/sessions export <name> out.md`). `-` prints the transcript to stdout instead of a file. The command tab-completes session names.

The export is the full, auditable log: user prompts, each thinking block, tool calls (arguments and result, with the optional `analysis`), plain assistant answers, `command` records, compaction summaries (with the trimmed-context boundary), system notes, and a final `## Errors` section. Since it renders the persisted form, serialization-time transforms (`noise_tools` markers, `session_tool_max_chars` truncation) carry through as they appear in the file.

The headless CLI `polyglav export <name> [--out <file>]` reuses the same renderer for scripts and CI. `--out -` prints to stdout, and the default matches the slash command (`.polyglav/exports/<name>.md`).

## File structure

```json
{
  "created_at": "2026-08-17T12:00:00+00:00",
  "errors": [],
  "mode": "",
  "parent_id": "",
  "permissions": [],
  "role": "",
  "session_id": "ab12cd",
  "session_name": "ses_20260817_120000_ab12cd",
  "sub_sessions": [],
  "turns": [],
  "updated_at": "2026-08-17T12:05:15+00:00",
  "version": "0.35.0"
}
```

| Key | Type | Description |
|-----|------|-------------|
| `created_at` | string | ISO 8601 UTC timestamp of creation |
| `errors` | array | Turn-level errors (provider, network, agent loop) |
| `mode` | string | Session posture (`read` or `write`), empty means follow the config `mode`. Set by `/mode` |
| `parent_id` | string | Name of the session this one was spawned from (sub-agent sessions set it, empty otherwise) |
| `permissions` | array | Audit log of tool permission decisions (see below) |
| `role` | string | Role that owns the session, stamped at creation (empty for a plain root or a headless run with no `--role`) |
| `session_id` | string | Six-character base36 session id, embedded in an auto name's trailing component (empty for explicit names) |
| `session_name` | string | Session name, matches the filename |
| `sub_sessions` | array | Names of sessions spawned from this one (delegations, since the delegate sets the sub-agent's `parent_id`) |
| `turns` | array | The conversation log, append-only, one entry per turn |
| `updated_at` | string | ISO 8601 UTC timestamp, bumped on every appended part |
| `version` | string | Polyglav version that created the session, stamped at creation (empty for files written before the field) |

`/sessions preview` prints the `parent` and `sub-sessions` links. `/sessions` annotates `sub_*` children with their parent.

## Turn and part schema

A turn is one user prompt (or one slash command) and the agent's response to it. It holds the turn-level context and an ordered list of parts:

| Turn field | Description |
|------------|-------------|
| `index` | 1-based position in the log |
| `started_at` / `ended_at` | ISO 8601 UTC timestamps (duration is the difference) |
| `status` | `running`, `ok`, `error`, `truncated`, `empty`, or `cancelled` |
| `model` / `provider` | Model and provider that served the turn |
| `mode` | Agent `mode` in effect (`read` or `write`) |
| `reasoning` | The `reasoning` config value in effect (`false`/`"off"` or an effort value) |
| `parts` | Ordered list of parts (below) |

Every part has `type` and `timestamp`. Fields beyond those depend on the type:

| Part type | Fields | Description |
|-----------|--------|-------------|
| `user` | `text` | An user prompt |
| `text` | `text` | Assistant answer text |
| `thinking` | `text` | Reasoning that preceded the answer or the tool call |
| `tool` | `name`, `input`, `output`, `is_error`, `analysis` | One tool call and its result, co-located. `input` is the parsed argument object, `is_error` marks an `Error` result, `analysis` is the optional one-line model insight (`tool_analysis` config) |
| `command` | `text` | A slash command. `summary` and `compact_from` are set on a `/compact` record |
| `system` | `text` | An injected note (e.g. the `web_search: true` auto-search context) |

A tool call and its result never split into separate records: the `tool` part is created with `name`/`input`, the engine executes the call, and `output`/`is_error`/`analysis` fill in on the same part. Thinking recorded before a tool round becomes a `thinking` part ahead of the `tool` parts.

### Examples

A plain prompt and answer:

```json
{
  "index": 1, "started_at": "2026-08-17T12:00:00+00:00",
  "ended_at": "2026-08-17T12:00:05+00:00", "status": "ok",
  "model": "llama3.2", "provider": "ollama", "mode": "read",
  "parts": [
    {"type": "user", "text": "What is OEE?", "timestamp": "2026-08-17T12:00:00+00:00"},
    {"type": "thinking", "text": "The user asks a definitional question, answer directly.", "timestamp": "2026-08-17T12:00:01+00:00"},
    {"type": "text", "text": "OEE is Overall Equipment Effectiveness...", "timestamp": "2026-08-17T12:00:05+00:00"}
  ]
}
```

A tool round and the final answer:

```json
{
  "index": 2, "status": "ok",
  "parts": [
    {"type": "user", "text": "search for the latest Python release", "timestamp": "..."},
    {"type": "thinking", "text": "I need current data, search first.", "timestamp": "..."},
    {"type": "tool", "name": "web_search", "input": {"query": "latest Python release"},
     "output": "Web search results...", "is_error": false,
     "analysis": "Pages about recent Python releases, 3.13 being the latest.", "timestamp": "..."},
    {"type": "text", "text": "The latest release is 3.13...", "timestamp": "..."}
  ]
}
```

A command and a compaction record:

```json
{"index": 3, "status": "ok", "parts": [
  {"type": "command", "text": "/model llama3.3", "timestamp": "..."}]}
{"index": 4, "status": "ok", "parts": [
  {"type": "command", "text": "/compact", "summary": "Summary of the earlier conversation...",
   "compact_from": 4, "timestamp": "..."}]}
```

A `command` part with a `summary` is a compaction record: `summary` holds the text and `compact_from` the turn `index` where the kept portion starts. The configured `system_prompt` and mode instruction are injected at request time, never stored in the log.

Answering a parked ask (`/asks answer <id> <text>` or `POST /asks/<id>/answer` on `polyglav serve`) appends a `user` part `[answer to parked ask #<id>] <answer>` to the ask's origin session, so the next turn on that session resumes with the user's decision in context. See [config.md](config.md#unattended-mode).

## Errors

Turn-level failures are appended to the `errors` array, separate from the turn log:

```json
{"code": 401, "message": "Unauthorized", "timestamp": "2026-08-17T12:40:00+00:00"}
```

`code` is the HTTP status where one exists, otherwise `0`. Errors include provider auth/network failures, stream EOF or empty completions, `max_tokens` truncation, and unexpected agent-loop exceptions.

## Permissions

Every tool permission resolution is recorded to the `permissions` array, making the log an audit trail of what the agent was allowed to do:

```json
{"tool": "run_command", "action": "ask", "decision": "granted", "path": "/home/me/proj", "timestamp": "2026-08-17T12:40:00+00:00"}
{"tool": "file_write", "action": "deny", "decision": "denied", "path": "/home/me/proj/a.md", "timestamp": "2026-08-17T12:41:00+00:00"}
```

| Field | Description |
|-------|-------------|
| `tool` | The tool name |
| `action` | The resolved policy action: `allow`, `ask`, or `deny` |
| `decision` | The outcome: `granted` (ran), `declined` (user refused an `ask`), or `denied` (blocked by policy) |
| `path` | The tool's `path_arg` value when the tool has one (e.g. the file or command target) |
| `timestamp` | ISO 8601 UTC timestamp |

Per-invocation (resolver-based) actions are recorded the same way, for example `delegate` logs the action resolved from the target role, so which delegation was allowed, asked, or denied is auditable. Entries are append-only and never removed. Recording is always on, with no config switch, so the log stays a reliable audit record.

## Append-only semantics

Turns and errors are only ever appended. Compaction stores the summary in a `command` part and leaves the earlier turns in place. Loading a session never rewrites history. The only transformations happen at serialization time (below), never to the in-memory log. A turn is written whenever it produced content or thinking, so a truncated mid-reasoning turn still persists its thinking, and a reasoning-only turn (thinking, no text) is recorded rather than lost. An empty turn (no content, no thinking) still records its status and any tool results.

## Serialization-time transforms

Two config keys reshape `tool` part output when the session is written to disk, without touching the stored parts:

- **`noise_tools`** (default `["web_fetch", "open", "fetch_page"]`) - output of the listed tools is replaced with `[<tool> result excluded from log, see tool call above for parameters]`, keeping noisy results out of session files while `input` stays on the part.
- **`session_tool_max_chars`** (default `0` = unlimited) - caps persisted tool `output` to N characters, appending `… (truncated from <len> chars)`.

## Preparing the provider context

The provider payload is prepared from the turns by `turns.provider_messages()` (via `Engine._provider_messages`):

- The latest `command` part with a `summary` becomes a `system` summary: `Summary of earlier conversation:\n\n<summary>`, and turns before its `compact_from` index are skipped.
- `command` parts are dropped.
- Within a turn, assistant text and the consecutive `tool` parts that follow become one assistant message with `tool_calls`, followed by the `tool` result messages, so a co-located tool round rebuilds to the OpenAI-compatible shape.
- `thinking` is attached to the assistant message it preceded.
- `user` and `system` parts pass through in order.

For compaction, tool results fold back into the summarized context as `[tool result] <output>` user messages so the summary can carry forward what the tools found.

## Compaction

`/compact` summarizes the earlier conversation and trims the provider context, controlled by `compact_keep` (default 4 = turns kept at the tail). The summary is stored in the `summary` of a `command` part with a `compact_from` turn index, so the full history stays in the log while only the summary plus the kept turns are sent to the model going forward.
