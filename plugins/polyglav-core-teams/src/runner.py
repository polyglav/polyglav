from dataclasses import dataclass, field

from polyglav.config import verbosity_level
from polyglav.engine import TurnResult
from polyglav.sessions import turns
from polyglav.ui import glyph

from teams import Team, read_team_memory, write_team_memory


@dataclass
class TeamRunResult:
    name: str = ''
    stages: list = field(default_factory=list)
    content: str | None = None
    memory: str = ''
    status: str = 'ok'
    errors: list = field(default_factory=list)
    streamed: bool = False

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'stages': [r.to_dict() for r in self.stages],
            'content': self.content,
            'memory': self.memory,
            'status': self.status,
            'errors': self.errors,
            'streamed': self.streamed,
        }


def _review_passed(content: str | None, marker: str) -> bool:
    if not content:
        return False
    text = content.lower()
    base = (marker or 'VERDICT:').strip().lower() or 'verdict:'
    if base.endswith('pass'):
        return base in text
    return f'{base} pass' in text


def _stage_errors(role: str, result: TurnResult) -> list:
    if result.errors:
        return list(result.errors)
    status = result.status or 'error'
    detail = f'stage "{role}" ended with status "{status}"'
    if result.session:
        detail += f' (session {result.session})'
    return [{'code': status, 'message': detail + ' - see the sub-session log'}]


class TeamRunner:
    def __init__(self, engine):
        self.engine = engine

    def __getattr__(self, name):
        return getattr(self.engine, name)

    def _team_stats(self, result) -> str:
        if verbosity_level(self.config, 'status') != 'on':
            return ''
        duration = 0.0
        total = 0
        for stage in (getattr(result, 'stages', None) or []):
            try:
                duration += float(getattr(stage, 'duration', 0.0) or 0.0)
            except (TypeError, ValueError):
                pass
            run_id = getattr(stage, 'run_id', None)
            if run_id is not None:
                count = self.runs.rollup(run_id).get('total_tokens') or 0
            else:
                usage = getattr(stage, 'usage', None) or {}
                count = usage.get('total_tokens')
                if count is None:
                    count = ((usage.get('prompt_tokens') or 0)
                             + (usage.get('completion_tokens') or 0))
            total += int(count or 0)
        parts = [f'{duration:.1f}s']
        if total:
            parts.append(f'({total:,} tokens)')
        return ' '.join(parts)

    def _build_stage_brief(self, team, task: str, results: list,
                           index: int, memory: str,
                           prior_cap: int = 4000) -> str:
        parts = [f'Team: {team.name}'
                 + (f' ({team.description})' if team.description else ''),
                 f'Original task:\n{task}']
        plan = getattr(self.current_session, 'plan', '')
        if plan:
            parts.append(f'Active plan: {plan}')
        for j, res in enumerate(results[:index], 1):
            content = (res.content or '').strip()
            if not content:
                content = f'(no final text from {res.session or "stage"})'
            if len(content) > prior_cap:
                content = content[:prior_cap].rsplit(' ', 1)[0] + '\n... (truncated)'
            parts.append(f'## Stage {j} result ({res.session or "stage"}):\n{content}')
        stage = team.stages[index]
        if index > 0 and team.stages[index - 1].handoff_note:
            parts.append(f'Stage {index + 1} handoff from {team.stages[index - 1].role}: '
                         f'{team.stages[index - 1].handoff_note}')
        if memory:
            parts.append(f'## Team memory\n{memory}')
        hint = stage.task_hint or 'Complete this stage of the task.'
        parts.append(f'Your stage ({stage.role}):\n{hint}')
        parts.append(f'You are stage {index + 1} of team "{team.name}". Do this '
                     f"stage's work directly and do not call the team tool for "
                     f'"{team.name}".')
        return '\n\n'.join(parts)

    def _team_memory_summary(self, team, results: list, prior: str) -> str:
        messages = []
        if prior:
            messages.append({'role': 'system',
                             'content': f'Previous team memory:\n{prior}'})
        for res in results:
            session = self.sessions.read(res.session) if res.session else None
            if session is not None:
                messages += turns.provider_messages(session.turns)
        if not messages:
            return ''
        try:
            summary = self._summarize(messages)
        except Exception:
            summary = None
        if summary:
            return str(summary).strip()
        lines = [f'Team {team.name} run:']
        for i, res in enumerate(results, 1):
            content = (res.content or '').strip().replace('\n', ' ')
            part = f'Stage {i} ({res.session or "?"}): {res.status}'
            if content:
                part += f' - {content[:200]}'
            else:
                msg = ''
                for e in res.errors or []:
                    if isinstance(e, dict) and e.get('message'):
                        msg = str(e['message'])
                        break
                if msg:
                    part += f' - Error: {msg[:200]}'
            lines.append(part)
        return '\n'.join(lines)[:1500]

    def run(self, team, task: str, skills: list | None = None,
            resume: str = '', context: str = 'continue') -> TeamRunResult:
        depth = getattr(self, '_team_depth', 0)
        max_depth = int(self.config.get('max_team_depth', 2) or 0)
        stack = list(getattr(self, '_team_stack', []))
        if team.name in stack:
            return TeamRunResult(
                name=team.name, status='error',
                errors=[{'code': 'team_cycle', 'message':
                         f'Team cycle detected: {" -> ".join(stack + [team.name])}. '
                         'This run is already a stage of that team; do the '
                         'stage work directly and do not call the team tool '
                         'for it again.'}])
        if max_depth and depth >= max_depth:
            return TeamRunResult(
                name=team.name, status='error',
                errors=[{'code': 'team_depth', 'message':
                         f'Team nesting limit reached ({max_depth}): {team.name}'}])
        self.engine._team_stack = stack + [team.name]
        self.engine._team_depth = depth + 1
        self.current_session.team = team.name
        self.ui.info(f'{glyph(self.config, "enter", "↳")} Team {team.name}')
        try:
            result = self._run_team_stages(
                team, task, skills=skills, resume=resume, context=context)
            ok = result.status in ('ok', 'truncated')
            self.ui.worked(team.name, self._team_stats(result), ok=ok)
            return result
        finally:
            self.engine._team_stack = stack
            self.engine._team_depth = depth

    def _run_team_stage(self, team, stage, brief: str, skills: list | None,
                        resume: str = '', context: str = 'continue') -> TurnResult:
        mode = self._mode()
        stage_skills = list(skills or [])
        for name in (stage.skills or []):
            if name and name not in stage_skills:
                stage_skills.append(name)
        index = team.stages.index(stage)
        self.engine._stage_label = f'{stage.role} ({index + 1}/{len(team.stages)})'
        self.engine._stage_name = stage.role
        try:
            if stage is team.stages[0] and resume:
                return self.run_subagent(stage.role, brief, mode=mode,
                                         skills=stage_skills, resume=resume,
                                         context=context)
            return self.run_subagent(stage.role, brief, mode=mode,
                                     skills=stage_skills)
        finally:
            self.engine._stage_label = ''
            self.engine._stage_name = ''

    def _build_iteration_brief(self, team, task: str, memory: str, stage,
                               prior: list, iteration: int,
                               review: str = '') -> str:
        parts = [f'Team: {team.name}'
                 + (f' ({team.description})' if team.description else ''),
                 f'Original task:\n{task}']
        plan = getattr(self.current_session, 'plan', '')
        if plan:
            parts.append(f'Active plan: {plan}')
        if iteration > 1:
            parts.append(f'Review loop iteration {iteration}.')
        if review:
            parts.append(f'## Findings from the previous review\n{review}')
        for j, res in enumerate(prior, 1):
            content = (res.content or '').strip()
            if not content:
                content = f'(no final text from {res.session or "stage"})'
            if len(content) > 4000:
                content = content[:4000].rsplit(' ', 1)[0] + '\n... (truncated)'
            parts.append(f'## Iteration result {j} '
                         f'({res.session or "stage"}):\n{content}')
        if memory:
            parts.append(f'## Team memory\n{memory}')
        hint = stage.task_hint or 'Complete this stage of the task.'
        parts.append(f'Your stage ({stage.role}):\n{hint}')
        parts.append(f'You are a stage of team "{team.name}". Do this stage\'s '
                     f'work directly and do not call the team tool for '
                     f'"{team.name}".')
        return '\n\n'.join(parts)

    def _team_loop_plan(self, team):
        loop = dict(team.loop or {})
        if not loop:
            return None
        names = [stage.role for stage in team.stages]

        def resolve(value):
            if isinstance(value, int):
                return value
            if value is None:
                return None
            try:
                return names.index(str(value))
            except ValueError:
                return None

        frm = resolve(loop.get('from'))
        until = resolve(loop.get('until'))
        if frm is None or until is None or frm > until:
            return None
        max_iterations = max(1, int(loop.get('max_iterations', 3) or 3))
        marker = str(loop.get('verdict') or 'VERDICT:')
        return frm, until, max_iterations, marker

    def _run_team_loop(self, team, task: str, skills: list | None,
                       memory: str, plan, stages: list,
                       resume: str = '', context: str = 'continue') -> tuple[str, list]:
        frm, until, max_iterations, marker = plan
        for i in range(0, frm):
            stage = team.stages[i]
            brief = self._build_stage_brief(team, task, stages, i, memory)
            res = self._run_team_stage(
                team, stage, brief, skills, resume, context)
            stages.append(res)
            if res.status not in ('ok', 'truncated'):
                return 'error', _stage_errors(stage.role, res)
        iterations = 0
        last_review = ''
        block: list[TurnResult] = []
        while True:
            iterations += 1
            block = []
            for i in range(frm, until + 1):
                stage = team.stages[i]
                review = last_review if i == frm else ''
                brief = self._build_iteration_brief(
                    team, task, memory, stage, block, iterations, review)
                res = self._run_team_stage(
                    team, stage, brief, skills, resume, context)
                stages.append(res)
                block.append(res)
                if res.status not in ('ok', 'truncated'):
                    return 'error', _stage_errors(stage.role, res)
            last_review = (block[-1].content or '') if block else ''
            if _review_passed(last_review, marker):
                break
            if iterations >= max_iterations:
                break
        for i in range(until + 1, len(team.stages)):
            stage = team.stages[i]
            brief = self._build_iteration_brief(
                team, task, memory, stage, block, iterations)
            res = self._run_team_stage(
                team, stage, brief, skills, resume, context)
            stages.append(res)
            if res.status not in ('ok', 'truncated'):
                return 'error', _stage_errors(stage.role, res)
        return 'ok', []

    def _team_roles(self, team) -> list:
        if getattr(team, 'type', 'sequential') == 'hierarchical':
            names = [team.manager] + [m.role for m in team.members]
            return [self.roles.find(name) for name in names if name]
        return [self.roles.find(stage.role) for stage in team.stages]

    def _build_manager_brief(self, team, task: str, memory: str,
                             skills: list | None = None) -> str:
        parts = [f'Team: {team.name}'
                 + (f' ({team.description})' if team.description else ''),
                 f'Original task:\n{task}']
        plan = getattr(self.current_session, 'plan', '')
        if plan:
            parts.append(f'Active plan: {plan}')
        roster = []
        for member in team.members:
            line = f'- {member.role}'
            if member.task_hint:
                line += f': {member.task_hint}'
            if member.skills:
                line += f' (skills: {", ".join(member.skills)})'
            roster.append(line)
        if roster:
            parts.append('Members:\n' + '\n'.join(roster))
        if memory:
            parts.append(f'## Team memory\n{memory}')
        parts.append(
            f'You are the manager of team "{team.name}". Allocate the work to '
            'the member roles with the call tool, validate every result '
            'yourself, drive corrections until the work is complete, and then '
            'return the final answer. Do not call the team tool for '
            f'"{team.name}".')
        if skills:
            parts.append('Use these skills for the run: ' + ', '.join(skills))
        return '\n\n'.join(parts)

    def _run_team_manager(self, team, task: str, skills: list | None,
                          memory: str, resume: str = '',
                          context: str = 'continue') -> TurnResult:
        mode = self._mode()
        stage_skills = list(skills or [])
        agent_role = self.roles.find(team.manager)
        if agent_role is not None:
            for name in (agent_role.skills or []):
                if name and name not in stage_skills:
                    stage_skills.append(name)
        brief = self._build_manager_brief(team, task, memory, stage_skills)
        self.engine._stage_label = f'{team.manager} (manager)'
        self.engine._stage_name = team.manager
        mapping = {m.role: list(m.skills) for m in team.members if m.skills}
        previous = getattr(self.engine, '_team_member_skills', {})
        self.engine._team_member_skills = mapping
        try:
            return self.run_subagent(team.manager, brief, mode=mode,
                                     skills=stage_skills, resume=resume,
                                     context=context)
        finally:
            self._team_member_skills = previous
            self.engine._stage_label = ''
            self.engine._stage_name = ''

    def _run_team_stages(self, team, task: str, skills: list | None = None,
                         resume: str = '', context: str = 'continue') -> TeamRunResult:
        for agent_role in self._team_roles(team):
            if agent_role is None or not agent_role.model:
                continue
            ref = self.unfold_ref(agent_role.model)
            provider, _, model = ref if ref else (
                self.config.get('provider'), None, agent_role.model)
            if not self._ensure_model_approved(provider, model):
                return TeamRunResult(
                    name=team.name, status='error',
                    errors=[{'code': '', 'message':
                        f'Stage "{agent_role.name}" uses unapproved model "{model}" - '
                        'approve it first (/model, --approve-model, or /connect)'}])
        worktree = self.config.local_path.parent.parent
        memory = read_team_memory(worktree, team.name)
        stages: list[TurnResult] = []
        errors: list = []
        status = 'ok'
        try:
            if getattr(team, 'type', 'sequential') == 'hierarchical':
                if not team.manager:
                    status = 'error'
                    errors.append({'code': '', 'message':
                                   f'Team "{team.name}" has no manager'})
                elif self.roles.find(team.manager) is None:
                    status = 'error'
                    errors.append({'code': '', 'message':
                                   f'Manager role "{team.manager}" is not in the catalog'})
                else:
                    res = self._run_team_manager(team, task, skills, memory,
                                                 resume, context)
                    stages.append(res)
                    if res.status not in ('ok', 'truncated'):
                        status = 'error'
                        errors.extend(_stage_errors(team.manager, res))
            else:
                plan = self._team_loop_plan(team)
                if plan is None:
                    for i, stage in enumerate(team.stages):
                        brief = self._build_stage_brief(team, task, stages, i, memory)
                        res = self._run_team_stage(team, stage, brief, skills,
                                                   resume, context)
                        stages.append(res)
                        if res.status not in ('ok', 'truncated'):
                            status = 'error'
                            errors.extend(_stage_errors(stage.role, res))
                            break
                else:
                    status, errors = self._run_team_loop(
                        team, task, skills, memory, plan, stages, resume, context)
        except ValueError as e:
            status = 'error'
            errors.append({'code': '', 'message': str(e)})
        summary = self._team_memory_summary(team, stages, memory)
        memory_path = ''
        if summary:
            memory_path = str(write_team_memory(worktree, team.name, summary))
        content = None
        if stages:
            last = stages[-1]
            if last.content:
                content = last.content
        return TeamRunResult(
            name=team.name,
            stages=stages,
            content=content,
            memory=memory_path,
            status=status,
            errors=errors,
            streamed=any(getattr(s, 'streamed', False) for s in stages),
        )

def run(engine, team, task: str, skills: list | None = None,
        resume: str = '', context: str = 'continue') -> TeamRunResult:
    return TeamRunner(engine).run(team, task, skills=skills, resume=resume,
                                  context=context)
