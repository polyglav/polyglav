# Developer teams and coding assistants

Polyglav is native to the terminal, so developers are the most natural first audience. Repo-scoped agents, permission-gated machine tools, and a headless CLI fit a working day and a CI pipeline without a new editor, a daemon, or a dependency tree. The shared foundation is in [index.md](index.md).

## Why it fits

- **Right tool, already installed**. A standard-library Python package and a REPL you already understand, with no lockfile churn and no supply chain to audit.
- **Scoped by repository**. Launch inside a repo (or pass `--path`) and the worktree scoping keeps file tools inside it. `file_read`, `list_dir`, `glob`, `grep`, and `file_write` operate on the code you are working on. See [tools.md](../tools.md).
- **CI-native**. `polyglav run` is a single headless command with `--output json`, so agents run in pipelines, pre-commit hooks, and scheduled jobs the same way they run in the terminal.
- **Permission discipline by design**. `run_command` for builds, tests, and git defaults to `ask`, so the model proposes before it executes. Headless agents auto-deny anything unapproved, which keeps accidental shell side effects rare.

## Fit by use case

- **Codebase Q&A**. Ask where the retry logic lives or how providers register, and get an answer from the actual tree via `glob`, `grep`, and `file_read`, with the file and line cited.
- **PR and change review**. Summarize diffs, flag risks, and draft review comments. Sessions give the whole review thread a replayable record.
- **Test and CI triage**. Run `polyglav run -p "explain this test failure" --output json` in the pipeline, with tool results such as exit codes and logs feeding the analysis.
- **Documentation generation**. Draft release notes, README sections, and migration guides from history and code, then write them with `file_write` under review.
- **Multi-repo fleets**. Run one `polyglav serve --path <repo>` agent per repository, answering over the API. See [fleet.md](../fleet.md).
- **Release and ops notes**. Summarize changelogs, craft commit messages, and prepare runbooks from local records.

## Hands-on setup

A complete step-by-step recipe for a lead, implementer, tester, and reviewer fleet with git worktree isolation and user gates between hand-offs is in [usage/programming.md](../usage/programming.md).

## What is live and what is planned

Read and Write modes are live: the agent starts read-only (write and exec tools are denied) and `/mode write` (or `polyglav run --mode write`) restores full access. The swarm foundations are live as well: a role catalog (bundled defaults plus global and local `.polyglav/roles.json`), an in-process sub-agent engine, and the `call` (named role), `delegate` (named team), and `offload` (read-only sibling) tools that run work under roles and pipelines, so a single REPL can hand research, writing, or programming work to `researcher`, `programmer`, or `code-reviewer` sub-agents. See [roles.md](../roles.md), [teams.md](../teams.md), and [swarm.md](../swarm.md). Developer tooling is live too: `file_edit` for surgical search-and-replace, read-only `git` plus gated `git_commit`, `code_test`/`code_lint`/`code_format` wrappers, a `run_command` command allowlist (`tool_permission.bash_allow`), and the per-worktree instructions file (`project_instructions`, default `AGENTS.md`) auto-loaded into the system prompt. The interactive `/agent` command and auditor agents are planned, as are notebook mode and richer interactive data analysis. These track [PLAN.md](../../PLAN.md) and [TODO.md](../../TODO.md). Tab completion, `/compact`, `/session`, and `polyglav run` already cover most day-to-day flows.

## Get started

1. `pip install polyglav` and run `polyglav` inside your repository, then `/connect` to your provider or point `--base-url` at a company gateway.
2. Try `/tool` to run tools directly, then ask a codebase question and watch it read the tree.
3. For automation, run `polyglav run -p "summarize the failing tests" --path tests --output json`. Add it to CI with `--yes` only when you are comfortable with the permissions.
4. Scope harder agents with `tools.deny` (a read-only reviewer denies `run_command` and `file_write`) and `tool_permission` categories in [config.md](../config.md).
