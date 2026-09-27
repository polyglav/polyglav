# Polyglav development skill

How to work on the Polyglav codebase itself. The project description lives in `AGENTS.md`; this skill adds the working conventions and the team flow.

## Conventions

- Stdlib only. No external dependencies in the core. Plugins may opt into deps via their manifest.
- Type hints required on every function signature. Use `from __future__ import annotations` if needed.
- No comments in code. Prefer `pathlib.Path` over `os.path`.
- ASCII punctuation only in docs: plain hyphens and three dots, never em/en dashes, curly quotes, or the single-character ellipsis. Split clauses with periods or commas, never semicolons.
- Keep the four planning files in sync: VISION.md (why, stable), PLAN.md (what, Task | Effort | Provides tables, finished tasks removed), TODO.md (backlog, ## Open and ## Done sorted newest-first, ## Done one-liners of at most 100 chars separated by ---), CHANGELOG.md (history, version sections newest at top, single flat bullet list newest first).
- After completing a planned task: mark it [x] in TODO.md, add an entry under the current version section in CHANGELOG.md (start a new version section first if none exists), and remove the task from PLAN.md.
- Documentation-only changes get no CHANGELOG entry; they are visible in git history.
- Keep the version in pyproject.toml in sync with the current version in CHANGELOG.md.

## Roles are specialists, ask the right one

- Roles are specialists for their area, and other agents ask them for work, so context stays small.
- Code: every question about the codebase goes to `developer` - where something is, how it works, what to change, a proposed solution, or the implementation. The developer answers with exact paths and line references, or investigates, proposes, and implements.
- Web and external facts: every search or current source goes to `researcher`. No other role calls a web tool.
- Documentation: Markdown and the planning files go to `docs`.
- Downstream roles start from the specialist's answer (the developer's code map and proposed solution) and read only what it did not cover, so the same file is not re-read by several roles.
- Record a short code map in your result when you had to read beyond the brief, so the next stage can reuse it.

## Commits

- One commit per task, staged per task: stage only that task's files, never `git add -A` across unrelated work.
- Message: a single line, '<Past-tense verb> <short subject>', capitalized, no trailing period, no prefix tags. Examples: "Added sequential team runs", "Fixed agent loop issues".
- Docs-only changes are committed separately with the same style.
- Never push, merge, checkout existing work, or rewrite history. Branches are allowed for long multi-task sessions so the human can diff against main.
- `git_commit` is gated by the `vcs` category (default `ask`). The `committer` role and the leader carry `vcs: allow`, so they commit with no prompt. Every other role stays ask-gated, and an ask auto-denies in a sub-run, so a builder stage never commits mid-run. A stage that may not commit returns the exact proposed message and lets the committer land it.

## Verify before finishing

- Tests: `python -m unittest discover tests` (core + bundled plugin suites). Single file: `python -m unittest tests.test_engine`.
- Run the related tests before each commit, then the whole suite once before finishing the working package.

## Tool usage

- `file_read` to inspect, `glob`/`grep` to locate code, `list_dir` to explore.
- `file_edit` for surgical search-and-replace; `file_write` for create/overwrite/append.
- `code_test`/`code_lint`/`code_format` run the project commands above.
- `git` (read-only) to inspect state; `git_commit` (gated by the `vcs` carve) to stage and commit.
- `run_command` is allowlisted to the dev command set (tests, ruff, git, python -m polyglav).

## Permissions

- Roles carry only the permissions a task truly needs. Web is denied for the dev roles; a task that needs web research uses the `researcher` role, which has web allow.
- Only a role carved to commit sets `vcs: allow` (`committer`, and the leader). Builder roles set `vcs: ask`, so no stage can commit mid-run.
- If a stage hits a denied or ask-gated tool, stop and report it as a "needs permission <x>" open question rather than bypassing policy or guessing.
- When you cannot answer a question yourself, list it as an open question for the human. Human decisions happen in the interactive REPL between runs.

## The workflow

- The assistant gathers and concretizes the operator's requirements, holds the whole picture, and coordinates. It does not read source code, search the web, or implement; it asks the right specialist.
- A task that touches code runs the `dev` team: developer (investigate and propose) > programmer (implement) > tester > code-reviewer (review loop) > committer.
- A task that changes docs runs the `docs` team: assistant (scope) > docs (write) > committer.
- The assistant works through `.polyglav/TODO.md` for its own work tracking, and reports a short summary after each run.

## Guardrails

- Never push, merge, checkout, or rewrite history.
- Keep changes minimal and scoped to the task; one commit per task.
- Report changed files, the commands run, their results, and a short code map.
