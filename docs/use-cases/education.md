# Education

The small, local, permission-scoped design maps well onto teaching. Learners get a private assistant that runs on their own machine, educators get per-student or per-course agents that cannot stray outside a defined worktree, and everything is logged. The shared foundation is in [index.md](index.md).

## Why it fits

- **Safe by scope**. A student agent runs inside a course folder with `tool_permission.bash: ask` and `tools.deny` for write tools, so it explains and explores without modifying anything. The worktree scoping in [tools.md](../tools.md) does the guarding.
- **Honest by default**. `run_command` is `ask`-gated and headless agents auto-deny, so an agent cannot silently execute. Sessions also record how an answer was reached, which supports a "show your work" culture rather than a black box.
- **Free of cost and dependencies**. Students install one standard-library package and connect any provider, including a free or local model. There is no per-seat licensing and no lock-in.
- **Works offline**. A local model turns a laptop without connectivity into a fully functional tutoring environment.

## Fit by use case

- **Tutoring assistant**. Explain concepts, work through examples, and drill problems in a scoped folder, with the session log capturing the student's learning path.
- **Course and lesson preparation**. Draft syllabi, lecture outlines, exercises, and rubrics from source material with `file_write`, then iterate under review.
- **Assessment drafting**. Generate question banks and sample solutions from course notes, keeping provenance in the session log for quality control.
- **Code and lab courses**. A repo-scoped agent that reads the assignment tree, explains errors from compiler output, and proposes fixes the student reviews before `file_write`. See the developer guide for the pattern in [developer.md](developer.md).
- **Institutional reporting**. Headless `polyglav run` summarizes class dashboards and documentation for administrators.

## Gaps and planned

Sandboxed execution (namespace or container isolation for `run_command`) is planned, which would harden student exec further. See [TODO.md](../../TODO.md). Until then, the `ask` gate and folder scoping provide the practical guardrails.

## Get started

1. Install with `pip install polyglav` on each machine, then run `polyglav serve --path <course-folder>` for a per-course agent.
2. `/connect` to a provider. Local models keep everything on the student's machine.
3. Configure the guardrails: `tool_permission.bash: ask`, and `tools.deny: [file_write]` on read-only tutor agents.
4. Run the class through the REPL or the API. Every session lands in `.polyglav/sessions/` for review and follow-up.
