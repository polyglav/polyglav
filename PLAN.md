# Execution Plan

Groups the next tasks from `TODO.md` (`## Open`) into work packages, each providing a distinct next-level capability. Packages are ordered top-to-bottom by urgency and importance, vision-first. Re-rank the packages against the backlog before starting each next step (docs-first for the roadmap phases).

Finished tasks are removed from this file and live as one-liners in `TODO.md` `## Done` and in detail under the matching version in `CHANGELOG.md`.

## Method

- Effort: S < M < L
- Provides: the capability the task delivers

## Self-development team enablement

The selfdev teams run unattended, land their work, and can be reattached from the REPL. Runs are sequential, and the REPL can pause or resume one. The rest closes the gaps between the project catalogs and the described workflow.

| Task | Effort | Provides |
|------|--------|----------|
| Committer as a callable stage - a run calls the committer to land the current state as one commit with a correct message | M | commits during a run |
| Saved-session catalog in `/load` - `/load` lists and loads saved sessions, `/runs` stays a read-only history, so an operator reattaches to a prior agent after a restart | S-M | switch to any prior agent |
| Ask continuation - answering a parked ask resumes and continues its origin run in place, not only injecting the answer into the session | M | reply to stacked questions and continue |
| Researcher role with fresh context - a researcher role template with web access, started fresh per task | S | clean research per task |
| Docs writer commits each added task - commit the tasks right after the operator's prompt, then work one point at a time | S | tasks land as agreed |

## Memory and role instructions

A delegated role remembers the user's instructions across runs, long role instructions live in full-length Markdown, and a conclusion stage lets a finished run improve the catalog.

| Task | Effort | Provides |
|------|--------|----------|
| Memory with references - a compact summary plus pointers to full-length Markdown and session artifacts, with a stale-reference guard | S-M | recall without replay |
| Role memory for delegated roles - inject role memory in `_new_sub_engine` through a shared compose helper, with a refresh path | S | a role remembers across runs |
| Shared codebase research - a role consults a shared research note (or memory) so roles do not re-read the same files | S-M | no duplicated reads |
| `memorize` as a tool - memory writes through a tool an agent calls | S-M | memory the agent maintains |
| Conclusion stage - a write-scoped stage that distills a finished run into role files, skills, or memory, and never commits | M | self-improvement loop |

The modes-first redesign removed root roles, so root-role memory folded into role memory for delegated roles. The remaining work is a refresh path for that memory (the conclusion stage), otherwise an updated memory file is not re-injected until the next run.

## Role boundaries, skills, and project knowledge

A role's file and folder access is a config rule, not a prompt, and a skill is tool or framework centered while the project description lives in `AGENTS.md`.

| Task | Effort | Provides |
|------|--------|----------|
| `.polyglav` directory layout - reserved subfolders and file names, documented | S-M | a predictable state layout |
| Skill definition and catalog review - tool, language, or framework skills, with a `python` skill and a `polyglav` skill, project description moved to `AGENTS.md` | M | reusable skills |
| Hidden files and allowed roots - hide secrets and config from tools by default, restrict visible paths | M | no accidental exposure |

## Agent catalog, permissions, and presentation

The catalog grows the fields and rule shapes an agent needs to be a first-class, self-describing profile: resource-scoped access, presentation, kind, durable approvals, and a Markdown catalogue for teams and skills.

| Task | Effort | Provides |
|------|--------|----------|
| Ordered resource-scoped permission rules - `{action, resource, effect}`, wildcards, last match wins, multi-file deny | M | policy-enforced boundaries |
| Agent kind and default agent - root/delegated/both plus a default startup role | S-M | role selection by kind |
| Agent presentation and limits - `color`, `hidden`, `disabled`, and a step cap | S | a first-class agent profile |
| Durable approvals and a hard-deny layer - project-scoped `always` grants, exact-args, deny-only policy | M | approvals that outlive a run |
| Markdown catalogue for teams and skills - JSON index plus Markdown body, migrated | M | portable, editable catalogs |
| Per-agent request overlays - request headers and body overlay per role | S-M | per-agent request tuning |

## Output log and status legibility

A session leaves a durable record, and status lines stay legible when a tool argument is large.

| Task | Effort | Provides |
|------|--------|----------|
| Batched structured asks - several decisions in one structured ask | S | fewer round trips |
| Tester loop scope - the tester runs only the related tests during the loop and the whole suite once | S | a fast related check, then a full run |
| Streamed tool call progress - argument progress for long tool calls | S | no silent `plan_write` |
| Honest token usage - per-run and tree totals in status, `/runs`, and `/history` | M | real cost |
| Onboarding visibility - reasoning, sub-run output, tool detail, and live status | S | a useful first setup |
| Ask prompt legibility - remove the duplicate line, truncate at word boundaries, and use a distinct question style | S | readable questions |
| Prompt colour fallback - match the live prompt to the submitted line and fall back to basic ANSI | S | consistent colour |

## Assistant roles & team orchestration

The assistant is the operator's entry point. A composer turns a task into a team, a manager runs teams, and specialists do the work. A role keeps a standing identity and extends it with skills per task, teams iterate generate > check > correct, and the run tree records the call order. This track resumes after the sequential run control and composite session view above, ordered by dependency.

| Task | Effort | Provides |
|------|--------|----------|
| Manager role - runs one or many teams and reports, sequential first | M | one window over several teams |
| Team docs and catalog guidance - when to use sequential versus hierarchical, with examples | S | correct model choices |
| Composer plugin (nice-to-have) - a bundled role that designs a team from an under-specified request by asking clarifying questions and saving it | M | guided team design |
| Core dev team configuration - a development team with the review loop plus the project lead/support teams and skills | S | ready-made teams and skills |
| Role-name sync - adopt assistant, composer, manager, and specialist across types, prompts, and docs | S | one canonical vocabulary |
| Assistant-roles track docs - record the architecture and work packages in VISION, PLAN, and TODO | S | documented direction |
| Leader PM posture - hold the whole picture, push back on a request that breaks the project, and concretize an ambiguous prompt | S | a leader that holds the line |
| Prompt brevity budget - every role prompt states a short output budget and a fixed report shape | S | less scrolling |

## Control & governance

The assistant is the operator's single window to the machine: served agents are spawned and supervised from the REPL, unattended runs park their asks instead of failing, and finished work reports back. This is the control surface the rest of the roadmap builds on.

| Task | Effort | Provides |
|------|--------|----------|
| Onboarding - first run: the assistant introduces itself, explains what it can do, and asks what to do. No system-level configuration for simple users | M | a supported first step |
| One-window status - `/status` lists sessions, running agents, and configured jobs on the machine, with logs reachable from the same surface | M | see everything from one place |
| Agent health monitoring - the assistant watches endpoints (e.g. the `/health` of agents running as web APIs) and warns when an agent stops responding | S-M | alert when an agent is down |
| `/spawn` command - launch a scoped `polyglav serve` agent from the REPL (home -> project path), supervise (health/list/stop) and delegate to it | S-M | fleet agents from the terminal |

## Delegation & swarm

Agents cooperate through types, delegation, and team stages. Sub-agents use the caller's provider, plugin manager, and worktree (see `docs/swarm.md`).

| Task | Effort | Provides |
|------|--------|----------|
| Per-agent todo lists - view a delegated agent's tasks, mark items done, read its session after the run, and ask for the current state (OpenCode-style) | M | current state of a delegation |
| Auto team selection - the assistant composes the team (types + order + briefs) for a task and calls the stages in sequence | M | team orchestration as a user-facing pattern |
| `/agent` types - interactive type selection/run UX (type registry, sub-engine, and `call` landed) | M | pick a type and run with it |
| Auditor agents + generate > check > correct orchestration - run a main agent, an auditor, and a fix pass in a loop until passing | M-L | review-and-fix loops (later phase, listed in VISION.md out-of-scope) |
| PM/dev/tester team orchestration as a user-facing pattern | M | team pattern on top of the teams registry |
| Custom system prompts per session | S-M | per-site instructions |
| Role directory scan for export/import - read `.polyglav/roles/*.md` (front-matter roles) to import and export roles to Markdown | S-M | portable role definitions |
| Swarm orchestration umbrella (TODO item) | - | decomposed by this package |

## Jobs operations + report-back

React to and see jobs from outside the box. Run teams on schedule.

| Task | Effort | Provides |
|------|--------|----------|
| Recurring tasks carry their own role - each job carries its own role and skills, so behavior like "make doc changes per AGENTS.md" is encoded once instead of re-prompted every time | S-M | encoded recurring behavior |
| `jobs add --team` - scheduled team runs, per-run team summary session, member sessions as team stages | M | recurring team pipelines |
| Jobs operator API - `GET /jobs` and `POST /jobs/<name>/approve|reject|run|disable` on `polyglav serve` | M | any client can see/act per agent |
| Job event hooks - the scheduler emits typed transitions (`proposed`, `approved`, `will_run`, `executing`, `verified`, `failed`, `timeout`, `waiting_approval`) to registered `services`, channel-agnostic core | M | notification source |
| Job connectors - bundled `polyglav-core-webhook` (stdlib JSON POST, zero deps) first, email (SMTP + polling) and Telegram (urllib long-poll) plugins later, all driving the jobs operator API | M-L | operators react in time |
| Fleet jobs overview - `polyglav jobs list --root <dir>` combined agent/job table (agent, job, status, next run, task), then a web Control UI on top | M | one view of what runs next |
| Mid-run blocking job approval - an `ask` inside a running job pauses in place (per-tool-call `waiting_approval`), notifies via a connector, and resumes the same session on reply. Needs resumable mid-run state, a wait loop inside the run, and the connectors above | L | decide during the task |

## Tool engineering for agents

Tools are the provider-facing surface: one OpenAI-compatible contract, registry metadata drives the loop. Hardening it for any provider (weak OpenAI-compatible backends especially), from the Anthropic tool-writing principles (choosing the right tools, namespacing, meaningful context, token efficiency, description prompt-engineering) and the tool-use evaluation methodology.

| Task | Effort | Provides |
|------|--------|----------|
| Tool spec polish - `grep.glob` -> `include`, description examples / preference guidance | S | unambiguous parameters and clearer tool selection |
| Full `file_*` namespace extension - if `file_glob`/`file_grep` prove better with most models, extend the prefix to `list_dir`/`glob`/`grep` (old names stay aliases) | S-M | consistent namespace |

## Fleet & control plane

Run many scoped agents under a supervisor with a control surface.

| Task | Effort | Provides |
|------|--------|----------|
| Immutable agent config - `polyglav serve` agents cannot change their own configuration, permissions, or tool list | S-M | control-plane rule |
| Minimal web Control UI - stdlib `http.server` page over the existing `polyglav serve` JSON API | M | dashboard over the JSON API |
| Multiuser API + queue / rate limits | M | many feeds without blocking the loop |
| Headless web API plugin-first - stdlib `http.server` fallback, richer framework (FastAPI) via the dependency plugin | S-M | fast API without core deps |
| Observability + telemetry decision - latency/cost/error metrics, Pi-style contracts | M | measured operations |

## Plugin ecosystem

Capabilities install as discoverable, isolated packages.

| Task | Effort | Provides |
|------|--------|----------|
| PyPI plugin source - install from `importlib.metadata` entry points | M | regular-package plugins |
| Plugin registry / marketplace - discoverable plugin sharing | M-L | plugin discovery |
| Shared plugin virtualenv - one venv for all plugin dependencies | M | isolated deps, one venv |
| Per-plugin virtualenv isolation - per-plugin `.venv`, site-packages injected at import | M | strongest dependency separation |
| Externalize bundled plugins - versioned repos, bundled copies stay the default | M | versioned bundled plugins |
| Plugin test harness - external plugins ship a test suite, `polyglav plugins test <name>` runs it | S-M | tested plugins |
| Cross-plugin tool router - virtual tool names (`open`, `search`, ...) dispatch per-argument to the matching plugin handler | M | context-aware dispatch |
| Web scraper + PDF-to-text plugins | S-M | non-text content types |
| Agent folder watcher - process new files on arrival | S-M | arrival-driven work |

## Apple Foundation Models on-device integration

Apple's on-device model is reachable from Python through the `apple-fm-sdk` alpha. It has no HTTP endpoint, a 4096-token context, cumulative streaming snapshots, and no tool calls on the streaming path, so it cannot reuse the OpenAI-compatible provider base. One bundled plugin integrates it in two stages: an `on_device` tool for an immediate, low-risk SDK check, then an `apple-fm` chat provider.

| Task | Effort | Provides |
|------|--------|----------|
| `on_device` tool - bundled `polyglav-core-apple-fm` plugin exposing an `on_device` tool for summarize, classify, and extract prompts, with lazy SDK import, availability reasons, and input and output caps | S-M | first on-device call and a private local helper |
| `apple-fm` chat provider - `BaseProvider` subclass with snapshot-to-delta streaming, provider-side context trimming, no tool calling, and `_fetch_models` and `check_connection` overrides | M | offline, private chat provider |
| Apple FM docs and tests - `docs/providers.md` row and section, `docs/plugins.md` bundled list, `docs/testing.md` row, default `plugins` entry, mocked SDK tests | S | documented and tested integration |

The provider uses a fresh `LanguageModelSession` per turn, since Polyglav's provider context is authoritative and a persisted SDK transcript would duplicate history against the 4096-token window. Tool calling stays out of the first provider cut, and the relay that would add it lives in `TODO.md` only.

## Developer workflow

Repo-aware coding assistance: version control, lint/format/test wrappers, scoped shell policy, per-worktree context.

| Task | Effort | Provides |
|------|--------|----------|
| Workspace sessions - tools write into a scoped `--workspace` dir, optional git sync | M | scoped workspaces |
| `code_debug` / `compile` - pdb/gcc/rustc wrappers (test/lint/format landed as `code_test`/`code_lint`/`code_format`) | S-M | debug + compile |
| Dev tool fallback - `code_lint`/`code_format` print a setup hint when the configured linter/formatter is absent and honor the `dev.lint_cmd`/`dev.format_cmd` overrides | S | lint/format in any repo |

## Knowledge & memory

Answers drawn from past sessions and local documents, bridging toward a vector store.

| Task | Effort | Provides |
|------|--------|----------|
| Session recall - full-text search over past sessions | M | answer from own history |
| Grep text index - internal bundled plugin (stdlib) indexing converted text files | M | search my notes in the worktree |
| `docs_search` - local grep + DuckDuckGo doc lookups | M | documentation lookups |
| Hybrid RAG + vector store | L | local semantic search |
| Topic-aware ranking - classifier for query intent to weight search results | M | intent-weighted results |
| Citations / source attribution - URL + snippet with every answer | S-M | grounded answers |

## Remote channels

Command agents from messaging apps.

| Task | Effort | Provides |
|------|--------|----------|
| Channel gateway - one adapter surface over the engine/serve API | M | one adapter surface |
| Telegram adapter - long-polling bot, send + receive | S-M | Telegram channel |
| WhatsApp adapter - business-API HTTP channel | M | WhatsApp channel |
| More adapters (Discord, Signal, email) | S-M | extra channels as plugins |
| Remote auth + session scoping + headless deny | M | secure remote command |

## Interactive analysis & notebooks

Data work inside the loop.

| Task | Effort | Provides |
|------|--------|----------|
| Interactive data analysis - CSV querying, SQL execution | M | data work in the loop |
| Notebook mode - persistent editable cells with run outputs | L | iterative data work |

## Share & polish

Session artifacts become portable and navigable.

| Task | Effort | Provides |
|------|--------|----------|
| Conversation sharing links - web-shareable sessions (builds on Markdown export) | M | shareable sessions |
| Session import from Markdown | M | round-trip session exchange |
| Bookmarks (`/bookmark`) | S | session pinning |
| Command palette / fuzzy history - CTRL-P style history search | M | fast history search |

## Enterprise operations & data

Durable, auditable workflows over plant and business data.

| Task | Effort | Provides |
|------|--------|----------|
| Hash-chained audit log | M | tamper-evident additive log |
| Edge / offline store-and-forward | M | buffering for unreliable connectivity |
| Sandboxed exec - namespace/container isolation for `run_command` | L | safe shell |
| Tool dry-run mode - propose args/effects without executing | S-M | safe tool gateway |
| Connectors (`read_stream`/`write_stream`) - MQTT, OPC-UA, Modbus data channels | M-L | industrial data channels |
| Time-series, inference, optimisation tools - anomaly/forecast, `model_infer`, scheduling | M | plant analytics |
| SCADA control + reporting - registers, Markdown/PDF/BI push | M | plant control + reporting |
| Onboarding wizard, RBAC, queue scaling - MES/data-source setup, roles, concurrency | M | enterprise readiness |

## Release & community

Distribution and outward-facing presence.

| Task | Effort | Provides |
|------|--------|----------|
| `polyglav update` | M | self-update |
| Standalone binary build | M | single executable |
| Docs site (ReadTheDocs) | S-M | ReadTheDocs reference docs |
| Community channels - Discord/X slots in README | S | community presence |

## How the layers compose

One round hands off in three steps:

1. **Start** - the operator starts a task: `polyglav jobs add`/`run` for scheduled work, or a REPL prompt or `/tool call <target>` for ad-hoc work. The jobs operator API adds a remote start (`POST /jobs/<name>/approve`) later
2. **Distribute + review** - the assistant splits the task into subtasks and calls them: sequentially by type or team stage today (`call`, `Engine.run_team`), routed to fleet agents over `POST /chat` once cross-process calls land, with auditor agents reviewing the output (generate > check > correct)
3. **Return** - results come back to the operator: the call result, team memory, or job summary today, the jobs operator API + webhook/email/Telegram connectors when the jobs layer lands. The fleet supervisor restarts crashed processes underneath. The jobs layer restarts failed work - two kinds of restart, both compose

Fleet is the substrate that stays up, not the conductor of the work.
