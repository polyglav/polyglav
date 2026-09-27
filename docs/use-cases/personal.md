# Personal and private use

The local-first, zero-dependency design makes Polyglav a natural private assistant. Your data stays on your machine, there is no telemetry and no cloud account, and the complete append-only session log doubles as a searchable journal of what you asked, what the agent did, and what it found. The shared foundation is in [index.md](index.md).

## Why it fits

- **Privacy by default**. Config and sessions live on your disk and provider traffic is outbound, so no external service holds your data. Pair the agent with a local model (Ollama via `/connect`) and nothing sensitive leaves the machine.
- **No account, no subscription**. Install with `pip`, connect a provider, and run. There is no SaaS tenant, no per-seat pricing, and no vendor lock-in.
- **Runs on modest hardware**. A single agent has a small footprint, so it runs comfortably on a laptop, a small server, or a Raspberry Pi.
- **A journal that keeps itself**. Every conversation is persisted with timestamps, duration, and tool activity, so the agent is a self-documenting research and decision log.

## Fit by use case

- **Personal knowledge assistant**. Point an agent at a notes or documents folder (`polyglav serve --path notes`) and ask questions in plain language. `glob`, `grep`, `file_read`, and `list_dir` keep answers grounded in your own files, with the matching excerpts cited.
- **Research assistant**. `web_search` and `web_fetch` (alias `open`) gather current information with sources, and sessions preserve the full trail of queries, pages fetched, and reasoning.
- **Notes and journaling**. A daily or topic-scoped session is a structured log. `/session load` and `/session save` switch between threads, and `/compact` trims provider context without touching the stored log.
- **Life and home automation**. With `run_command` you can drive scripts and local tools. Keep it read-only at first for reporting, summaries, and reminders. Anything that writes or executes belongs behind the `ask` confirmation that `bash` carries by default.
- **Offline and intermittent use**. Local models and a standard-library core need no external service, so the agent keeps working on a train, in the field, or on a disconnected machine.

## Gaps and planned

Personal power-user features are planned, not current: bookmarks (`/bookmark`), interactive data analysis and SQL over local files, notebook mode, hybrid local search with embeddings, and richer search over notes. These track [TODO.md](../../TODO.md). For most personal use the current core is already complete.

## Get started

1. Install with `pip install polyglav`, then run `polyglav` for the REPL or `polyglav serve --path ~/notes` for a headless agent.
2. `/connect` to a provider: Ollama for a fully local setup, or any OpenAI-compatible endpoint for hosted models.
3. Set permissions to taste. Keep `tool_permission.web: allow` and `tool_permission.bash: ask` (the default), and use `tools.deny` to remove capabilities you do not want, for example `file_write` on a research-only agent.
4. Ask away. Every turn lands in `.polyglav/sessions/` as a complete, replayable log.
