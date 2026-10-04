# Home lab, makers, and self-hosters

For home-lab users the appeal is a small, standard-library agent that runs on a Raspberry Pi, keeps its data local, has no telemetry, and composes with the rest of your stack over a plain HTTP API. The shared foundation is in [index.md](index.md).

## Why it fits

- **Fits the hardware you have**. No JVM and no node_modules, so it idles happily on a Pi next to your DNS server while you run the rest of your services.
- **Self-hosted and sovereign**. Sessions and config are files on your disk. Point it at Ollama on the same box and the whole stack is yours, offline-capable, with no vendor in the loop.
- **Scriptable and composable**. Run `polyglav run` in cron, `polyglav jobs daemon` for durable scheduled work with retries and approvals, and `polyglav serve` behind your reverse proxy, with agents talking to each other over `POST /chat`. It slots into an existing automation stack instead of demanding its own platform.
- **Permission-gated by design**. Home automation touches real systems, so the `ask` gate on `run_command` and worktree scoping keep the agent proposing before it acts.

## Fit by use case

- **Personal dashboards and reports**. Scheduled `polyglav run` jobs summarize logs, sensor readings, service health, and monthly usage into short reports on your own schedule.
- **Home automation assistance**. Explain device status and logs, draft automation rules, and propose changes, with writes and exec kept behind the `ask` confirmation.
- **Self-hosted knowledge base**. A docs or notes agent scoped to a folder answers from your files with citations grounded in `grep` and `file_read`.
- **Service-watch agent**. A per-service agent (`polyglav serve --path /srv/<app>`) triages logs and outage notes over the API. See [fleet.md](../fleet.md) for the fleet pattern.
- **Off-grid and lab bench**. A laptop or Pi with a local model works without connectivity, so the agent goes where the network does not.

## Gaps and planned

Home-lab power-user features are planned: bookmarks, notebook mode, RAG and vector search over your documents, and MCP support to wire the agent into other self-hosted tools. These track [TODO.md](../../TODO.md). The current core already covers reporting, triage, and grounded Q&A.

## Get started

1. Install with `pip install polyglav` on the Pi or NUC, and run `polyglav` in a terminal, or `polyglav serve --path /srv/notes --port 8787` behind your proxy.
2. `/connect` to Ollama on the same machine for a fully local setup, or any OpenAI-compatible endpoint.
3. Lock it down with `tool_permission.bash: ask`, and use `tools.deny` to strip capabilities you do not want on a given agent.
4. Schedule `polyglav run -p "summarize today's logs" --output json` in cron, or register it as a durable job (`polyglav jobs add` plus `polyglav jobs daemon`) for retries, approval-gating, and a recorded run history. Sessions accumulate as your searchable operations log either way.
