# Workflows and usage

This page is the big picture: how work moves through Polyglav from a request to a delivered result, and the patterns people build on top. It stays at the level of ideas. For exact commands, see the linked reference pages.

## The shape of a run

A larger task moves through the same steps every time:

1. **Ask** - the user tells the `assistant` what they want, in a sentence. Small tasks are answered inline. Bigger ones move on.
2. **Compose** - the `composer` role designs a team for the task: which specialists, which skills each one needs, the order of stages, and whether a review loop should run. The team is saved to the catalog and can be reused.
3. **Run** - the team runs stage by stage. Each stage is its own sub-agent with its own role, skills, and permission carve, and it writes its own session log. A review loop lets a producer revise against the reviewer's feedback until it passes.
4. **Hand off** - as the work changes shape, control moves between runs. One agent finishes and hands focus to the next, which continues with its own session intact.
5. **Watch or stay out** - the user can follow along, jump into any run, or leave it running in the background.
6. **Remember** - after the run, the team and its members refresh their memory, so the next run continues from the change instead of replaying a whole transcript.
7. **Report** - a summary surfaces when the run finishes or fails, and recurring work reports out of band.

## Patterns

### Team of teams

A writing or research goal often needs two cooperating teams. A lead team keeps the direction steady: it tracks requirements, researches sources, drafts the text, and runs a review loop so the writer revises against the requirements and the references. A supporting team supplies evidence: it gathers data, checks the requirements, and produces tables and analysis that justify the statements in the text.

The lead team leads and the support team serves. Each stage is a role with its own prompt and permissions, and each writer can carry more than one skill, so the same writer drafts an expose and later the full work by switching skills per task.

### Focus and handoff

Agents hand control to one another as the work moves through phases. The assistant does not have the permissions to build a team itself, so it hands focus to the composer. The composer builds the team, starts it, and finishes. A planning agent picks up, creates the task list, and starts a developer. The developer works, and when it reports a task done, the planner can hand it another one, because the developer still has its session and remembers what it just did.

The user can watch this flow, stay out of it, or jump in with `/focus`, which shows the run tree and lets them attach to any run. Handoff moves focus and stops the current run, and never disturbs the target's session.

### Scheduled maintainer

Recurring work is a job. A job carries its own role and skills, so a convention like "keep the docs in sync with AGENTS.md" lives in a skill rather than in every prompt. The scheduler runs it unattended, and a run memory carries context from one run to the next.

### Supervised fleet

For many independent agents, run one process per folder and let the fleet supervisor manage them: it allocates ports, checks health, and restarts failures. Each agent has its own config, model, and permissions, and clients reach it over HTTP.

### Scripted agent

The same loop is available headlessly. Use the CLI for one-shot prompts and the HTTP API for services, so an agent can be a step in a pipeline or a backend for another tool.

## Where to go next

- [Agent swarms](../swarm.md) - delegation, types, and how agents cooperate
- [Teams](../teams.md) - stages, skills, memory, and the review loop
- [Sessions](../session.md) - the run logs and how context is kept bounded
- [Jobs](../jobs.md) - scheduled and durable work
- [Agent fleets](../fleet.md) - many scoped agents under a supervisor
- [Roles](../roles.md) and [Skills](../skills.md) - defining reusable specialists
