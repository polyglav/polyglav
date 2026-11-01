import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

from polyglav.config import Config, verbosity_level
from polyglav.engine import Engine, TurnResult
from polyglav.sessions import turns
from jobs import (Job, JobRun, JobRegistry, compute_next_run, job_session_name,
                   parse_dt, read_memory,
                   system_prompt_for, write_memory)
from polyglav.ui import HeadlessUI



class JobSupervisorUI:
    interactive = False

    def __init__(self, engine: Engine, job: Job, supervisor: str):
        self.engine = engine
        self.job = job
        self.supervisor = str(supervisor or 'assistant')

    def ask(self, question, context='', options=None, origin=''):
        roles = getattr(self.engine, 'roles', None)
        role = roles.find(self.supervisor) if roles is not None else None
        if self.supervisor not in ('', 'assistant') and role is None:
            return (f'[cancelled] Job supervisor role "{self.supervisor}" '
                    'is not in the catalog')
        options_text = ', '.join(str(o) for o in (options or []))
        prompt = (
            f'You are the supervisor for job "{self.job.name}". Answer the '
            'question below within the job permission ceiling. Approve only '
            'what the job needs, deny anything broader, and return only the '
            'answer.\n\n'
            f'Job task:\n{self.job.prompt or self.job.system_prompt or "(none)"}\n\n'
            f'Question:\n{question}\n\n'
            f'Context:\n{context or "(none)"}\n\n'
            f'Options:\n{options_text or "(none)"}')
        previous = getattr(self.engine, '_ask_ui', None)
        self.engine._ask_ui = None
        try:
            result = self.engine.run_subagent(
                self.supervisor if role is not None else '', prompt)
        except Exception as e:
            return f'[cancelled] Job supervisor failed: {e}'
        finally:
            self.engine._ask_ui = previous
        answer = (result.content or '').strip()
        return answer or None


def _fresh_job_session(sessions_dir: Path, name: str, when: datetime) -> str:
    while True:
        candidate = job_session_name(name, when)
        if not (Path(sessions_dir) / f'{candidate}.json').exists():
            return candidate


def _build_engine(config: Config, job: Job, verbose: bool,
                  stream: bool = False, session_name: str | None = None) -> Engine:
    sub_config = Config(path=str(config.local_path.parent.parent))
    agent_role = None
    skill_names = []
    grant_ceiling = None
    from polyglav.plugins.manager import PluginManager
    pm = PluginManager(config)
    pm.load()
    if job.role:
        from polyglav.modes import merge_policy
        from polyglav.role_model import resolve_permissions, resolve_grant_ceiling
        factory = pm.service('role_registry')
        roles = (factory(local_path=config.local_path.parent / 'roles.json')
                 if factory is not None else None)
        if roles is None:
            raise ValueError('Role registry plugin is not loaded')
        agent_role = roles.find(job.role)
        if agent_role is None:
            raise ValueError(f'Unknown role: {job.role}')
        if agent_role.model:
            sub_config.apply('model', agent_role.model)
        parent_self = dict(merge_policy(sub_config)[0])
        parent_grant = (sub_config.get('grant_permission') or parent_self)
        permissions = resolve_permissions(
            parent_self, parent_grant, agent_role.tool_permission)
        sub_config.apply('tool_permission', permissions)
        grant_ceiling = resolve_grant_ceiling(
            parent_self, parent_grant, agent_role.grant_permission, permissions)
        if agent_role.ask_policy:
            ask_policy = dict(sub_config.get('ask_policy') or {})
            ask_policy.update(agent_role.ask_policy)
            sub_config.apply('ask_policy', ask_policy)
        skill_names = list(agent_role.skills or [])
    try:
        system_text = system_prompt_for(
            job, config.local_path.parent.parent, agent_role,
            memory_store=pm.service('memory'))
    except FileNotFoundError as e:
        raise ValueError(str(e)) from e
    if skill_names:
        factory = pm.service('skill_registry') if pm is not None else None
        section_fn = pm.service('skills_section') if pm is not None else None
        if factory is not None and section_fn is not None:
            skills = factory(local_dir=config.local_path.parent / 'skills')
            section = section_fn(skills, skill_names)
            if section:
                system_text = system_text.rstrip() + '\n\n' + section
    sub_config.apply('system_prompt', system_text)
    sub_config.apply('mode', job.mode or 'write')
    if job.model:
        sub_config.apply(
            'model',
            f'{job.provider}/{job.model}'
            if job.provider and '/' not in job.model else job.model)
    if job.tool_permission:
        permissions = dict(sub_config.get('tool_permission') or {})
        permissions.update(job.tool_permission)
        sub_config.apply('tool_permission', permissions)
    if job.tools_deny:
        sub_config.apply('tools.deny', job.tools_deny)
    ui = HeadlessUI(auto='deny', verbose=verbose, stream=stream,
                    thinking_level=verbosity_level(sub_config, 'thinking'),
                    footer_level=verbosity_level(sub_config, 'footer'))
    engine = Engine(sub_config, ui=ui, plugin_manager=pm,
                    approve_models=job.approve_model or bool(job.model))
    supervisor = (job.supervisor
                  or str(config.get('jobs.supervisor', 'assistant') or 'assistant'))
    engine._ask_ui = JobSupervisorUI(engine, job, supervisor)
    engine.role = job.role or ''
    engine.current_run.role = engine.role
    if grant_ceiling is not None:
        engine._grant_ceiling = grant_ceiling
    fallback = job_session_name(job.name, datetime.now(timezone.utc))
    engine.load_or_create_session(session_name or job.session or fallback)
    return engine


def _attempt(engine: Engine, prompt: str, timeout: int,
             team: str = '') -> TurnResult:
    def run() -> TurnResult:
        if not team:
            return engine.chat(prompt, origin='job')
        found = engine.teams.find(team)
        if found is None:
            return TurnResult(status='error',
                              errors=[{'code': 0, 'message': f'Unknown team: {team}'}],
                              session=engine.current_session.session_name)
        result = engine.run_team(found, prompt)
        duration = sum(float(getattr(stage, 'duration', 0) or 0)
                       for stage in result.stages)
        return TurnResult(
            content=result.content,
            errors=list(result.errors or []),
            duration=round(duration, 1),
            session=engine.current_session.session_name,
            status='ok' if result.status == 'ok' else 'error',
            run_id=engine.current_run.id,
        )

    timeout = max(0, int(timeout or 0))
    if timeout <= 0:
        try:
            return run()
        except Exception as e:
            return TurnResult(status='error',
                              errors=[{'code': 0, 'message': str(e)}],
                              session=engine.current_session.session_name)
    bag: dict = {}

    def target():
        try:
            bag['value'] = run()
        except Exception as e:
            bag['error'] = e

    thread = threading.Thread(target=target,
                              name=f'job-{engine.current_session.session_name}',
                              daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return TurnResult(status='error',
                          errors=[{'code': 'timeout',
                                   'message': f'job exceeded {timeout}s timeout'}],
                          session=engine.current_session.session_name)
    if 'error' in bag:
        return TurnResult(status='error',
                          errors=[{'code': 0, 'message': str(bag['error'])}],
                          session=engine.current_session.session_name)
    return bag['value']


class JobScheduler:
    def __init__(self, config: Config, verbose: bool = True,
                 stream: bool = False, plugin_manager=None):
        self.config = config
        self.registry = JobRegistry(config.local_path.parent / 'jobs.json')
        self.verbose = verbose
        self.stream = stream
        self._pm = plugin_manager

    def _plugin_manager(self):
        if getattr(self, '_pm', None) is None:
            from polyglav.plugins.manager import PluginManager
            self._pm = PluginManager(self.config)
            self._pm.load()
        return self._pm

    def _out(self, msg: str, error: bool = False):
        stream = sys.stderr if error else sys.stdout
        if self.verbose:
            stream.write(f'[job] {msg}\n')
            stream.flush()

    def _dispatch_report(self, job: Job, run: JobRun):
        try:
            service = self._plugin_manager().service('report')
            if service is None:
                return
            reporter = getattr(service, 'report', None)
            if not callable(reporter):
                return
            worktree = self.config.local_path.parent.parent
            memory = read_memory(
                worktree, job, self._plugin_manager().service('memory'))
            payload = {
                'event': 'job.run.completed',
                'job': job.name,
                'status': run.status,
                'duration': run.duration,
                'reason': run.reason,
                'session': run.session,
                'started_at': run.started_at,
                'finished_at': run.finished_at,
                'content': run.content,
                'worktree': str(worktree),
                'memory': (' '.join(memory.split()))[:1000] if memory else '',
            }
            reporter(payload, self.config)
            self._out(f'{job.name}: report dispatched')
        except Exception as e:
            self._out(f'{job.name}: report failed: {e}', error=True)

    def run_job(self, job: Job) -> JobRun:
        job.status = 'executing'
        job.next_run_at = ''
        self.registry.save()
        run_started = datetime.now(timezone.utc)
        run_session = job.session
        if not run_session:
            run_session = _fresh_job_session(
                self.config.local_path.parent / 'sessions', job.name, run_started)
        retries = max(0, int(job.retries or 0))
        backoff = max(0.0, float(job.backoff or 0))
        attempt = 0
        last_run: JobRun | None = None
        finished = datetime.now(timezone.utc)
        while True:
            attempt += 1
            started = datetime.now(timezone.utc)
            try:
                engine = _build_engine(self.config, job, self.verbose,
                                       self.stream, run_session)
            except ValueError as e:
                run = JobRun(started_at=started.isoformat(timespec='seconds'),
                             finished_at=started.isoformat(timespec='seconds'),
                             status='failed', reason=str(e), attempt=attempt,
                             session=run_session)
                job.history.append(run)
                self.registry.save()
                self._finish(job, run, started)
                self._update_memory(None, job, run)
                self._dispatch_report(job, run)
                return run
            if attempt > 1:
                prompt = (f'[Previous attempt {attempt - 1} failed. Retry this '
                          f'job and finish it.]\n\n{job.prompt}')
            else:
                prompt = job.prompt
            self._out(f'run {job.name} (attempt {attempt})')
            result = _attempt(engine, prompt, job.timeout, job.team)
            finished = datetime.now(timezone.utc)
            ok = result.status in ('ok', 'truncated')
            reason = ''
            if result.errors:
                reason = '; '.join(
                    e.get('message', '') for e in result.errors
                    if isinstance(e, dict) and e.get('message'))
                if len(reason) > 300:
                    reason = reason[:300] + '...'
            run = JobRun(
                started_at=started.isoformat(timespec='seconds'),
                finished_at=finished.isoformat(timespec='seconds'),
                status='verified' if ok else 'failed',
                reason=reason, duration=round(result.duration, 1),
                session=result.session or '', attempt=attempt,
                content=(result.content or '')[:1000])
            job.history.append(run)
            self.registry.save()
            if ok or attempt > retries:
                break
            delay = backoff * (2 ** (attempt - 1))
            self._out(f'attempt {attempt} failed - retrying in {delay:.0f}s '
                      f'(attempt {attempt}/{retries + 1})')
            if delay > 0:
                time.sleep(delay)
        self._finish(job, run, finished)
        self._update_memory(engine, job, run)
        self._dispatch_report(job, run)
        return run

    def _update_memory(self, engine, job: Job, run: JobRun):
        worktree = self.config.local_path.parent.parent
        summary = None
        memory_store = self._plugin_manager().service('memory')
        if engine is not None:
            try:
                messages = []
                prior = read_memory(worktree, job, memory_store)
                if prior:
                    messages.append(
                        {'role': 'system',
                         'content': f'Previous run memory:\n{prior}'})
                messages += turns.provider_messages(engine.current_session.turns)
                summary = engine._summarize(messages)
                if summary:
                    summary = str(summary).strip()
            except Exception:
                summary = None
        if not summary:
            summary = f'Run {run.started_at}: {run.status}.'
            if run.content:
                summary += f'\n{run.content}'
            elif run.reason:
                summary += f'\nError: {run.reason}'
            summary = summary[:1500]
        if memory_store is not None:
            write_memory(worktree, job, summary, memory_store)
            self._out(f'{job.name}: run memory updated')

    def _finish(self, job: Job, run: JobRun, finished: datetime) -> JobRun:
        job.last_run_at = run.started_at
        job.status = 'verified' if run.status == 'verified' else 'failed'
        if job.require_approval:
            job.status = 'waiting_approval'
            job.approval_pending = False
        if job.schedule.get('at'):
            job.enabled = False
            job.next_run_at = ''
        else:
            next_at = compute_next_run(job, finished)
            job.next_run_at = next_at.isoformat(timespec='seconds') if next_at else ''
        self.registry.save()
        verb = 'verified' if run.status == 'verified' else 'failed'
        if job.require_approval:
            verb += ' (next run waits for approval)'
        self._out(f'{job.name}: {verb} ({run.duration}s, '
                  f'{len(job.history)} run(s) recorded)')
        return run

    def tick(self, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        due = []
        for job in self.registry.all():
            if not job.ready_to_run():
                continue
            try:
                next_at = parse_dt(job.next_run_at) if job.next_run_at else now
            except ValueError:
                next_at = now
            if next_at <= now:
                due.append(job)
        for job in due:
            self.run_job(job)

    def daemon(self, tick_seconds: float = 15.0):
        self._out('job scheduler started - press Ctrl-C to stop')
        try:
            while True:
                try:
                    self.tick()
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    self._out(f'error in scheduler tick: {e}', error=True)
                time.sleep(max(1.0, float(tick_seconds)))
        except KeyboardInterrupt:
            self._out('job scheduler stopped')
        return 0