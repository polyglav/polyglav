import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from .sessions.manager import session_id_hash

MIN_INTERVAL = 60
CRON_HORIZON_DAYS = 4 * 366 + 1
HISTORY_MAX = 100

DEFAULT_JOB_SYSTEM_PROMPT = (
    'You are a recurring autonomous job. Complete the task given in the latest '
    'user message. Earlier runs of this job are part of this conversation '
    'history - use them to stay consistent, avoid repeating already-completed '
    'work, and report what you did.')

TASK_TEMPLATE = """# {name}

## Task
Describe what has to be done on every run. Replace this with the real job.

## Done when
How do we know this run succeeded?

## Notes
Constraints, context, links, files to touch."""


def parse_cron_field(field: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for element in field.split(','):
        element = element.strip()
        if not element:
            raise ValueError(f'empty element in field "{field}"')
        step = 1
        base = element
        if '/' in element:
            base, _, step_str = element.partition('/')
            step = int(step_str)
            if step <= 0:
                raise ValueError(f'invalid step in "{element}"')
        if base == '*':
            values = range(lo, hi + 1)
        elif '-' in base:
            a, _, b = base.partition('-')
            values = range(int(a), int(b) + 1)
        elif base.isdigit():
            values = range(int(base), int(base) + 1)
        else:
            raise ValueError(f'invalid cron element "{element}"')
        for v in values:
            if not (lo <= v <= hi):
                raise ValueError(f'value {v} out of range {lo}-{hi}')
            if (v - lo) % step == 0:
                out.add(v)
    return out


def _parse_weekdays(field: str) -> set[int]:
    values = parse_cron_field(field, 0, 7)
    return {(v - 1) % 7 for v in values}


def next_run(cron_expr: str, after: datetime) -> datetime:
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(
            'cron expression must have exactly 5 fields: minute hour dom month dow')
    minutes = parse_cron_field(parts[0], 0, 59)
    hours = parse_cron_field(parts[1], 0, 23)
    doms = parse_cron_field(parts[2], 1, 31)
    months = parse_cron_field(parts[3], 1, 12)
    dows = _parse_weekdays(parts[4])
    tz = after.tzinfo
    start = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    day = start.date()
    for _ in range(CRON_HORIZON_DAYS):
        if day.month in months and day.day in doms and day.weekday() in dows:
            first = day == start.date()
            start_hour = start.hour if first else 0
            start_minute = start.minute if first else 0
            for h in sorted(hours):
                if h < start_hour:
                    continue
                minute_lo = start_minute if h == start_hour else 0
                for m in sorted(minutes):
                    if m >= minute_lo:
                        return datetime(day.year, day.month, day.day, h, m,
                                        tzinfo=tz)
        day += timedelta(days=1)
    raise ValueError('no matching cron time found within 4 years')


def parse_dt(value: str) -> datetime:
    text = value.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f'invalid datetime: {value}')
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _clamp_interval(value) -> int:
    try:
        interval = max(MIN_INTERVAL, int(value))
    except (TypeError, ValueError):
        interval = MIN_INTERVAL
    return interval


def compute_next_run(job: 'Job', after: datetime) -> datetime | None:
    schedule = job.schedule or {}
    if schedule.get('cron'):
        return next_run(str(schedule['cron']), after)
    if schedule.get('interval'):
        return after + timedelta(seconds=_clamp_interval(schedule['interval']))
    if schedule.get('at'):
        at = parse_dt(str(schedule['at']))
        return at if at > after else None
    return None


@dataclass
class JobRun:
    started_at: str = ''
    finished_at: str = ''
    status: str = ''
    reason: str = ''
    duration: float = 0.0
    session: str = ''
    attempt: int = 0
    content: str = ''

    def to_dict(self) -> dict:
        return {
            'started_at': self.started_at,
            'finished_at': self.finished_at,
            'status': self.status,
            'reason': self.reason,
            'duration': self.duration,
            'session': self.session,
            'attempt': self.attempt,
            'content': self.content,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'JobRun':
        return cls(
            started_at=d.get('started_at', ''),
            finished_at=d.get('finished_at', ''),
            status=d.get('status', ''),
            reason=d.get('reason', ''),
            duration=d.get('duration', 0.0),
            session=d.get('session', ''),
            attempt=d.get('attempt', 0),
            content=d.get('content', ''),
        )


@dataclass
class Job:
    name: str
    schedule: dict
    prompt: str = ''
    session: str = ''
    mode: str = ''
    provider: str = ''
    model: str = ''
    role: str = ''
    system_prompt: str = ''
    task_file: str = ''
    tool_permission: dict = field(default_factory=dict)
    tools_deny: list = field(default_factory=list)
    retries: int = 3
    backoff: float = 60.0
    timeout: int = 0
    require_approval: bool = False
    approve_model: bool = False
    approval_pending: bool = False
    enabled: bool = True
    status: str = 'proposed'
    created_at: str = ''
    next_run_at: str = ''
    last_run_at: str = ''
    history: list = field(default_factory=list)

    def runnable(self) -> bool:
        return bool(self.enabled) and self.status in ('approved', 'verified', 'failed')

    def ready_to_run(self) -> bool:
        if not self.runnable():
            return False
        if self.require_approval and not self.approval_pending:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'schedule': dict(self.schedule),
            'prompt': self.prompt,
            'session': self.session,
            'mode': self.mode,
            'provider': self.provider,
            'model': self.model,
            'role': self.role,
            'system_prompt': self.system_prompt,
            'task_file': self.task_file,
            'tool_permission': dict(self.tool_permission),
            'tools_deny': list(self.tools_deny),
            'retries': self.retries,
            'backoff': self.backoff,
            'timeout': self.timeout,
            'require_approval': self.require_approval,
            'approve_model': self.approve_model,
            'approval_pending': self.approval_pending,
            'enabled': self.enabled,
            'status': self.status,
            'created_at': self.created_at,
            'next_run_at': self.next_run_at,
            'last_run_at': self.last_run_at,
            'history': [r.to_dict() for r in self.history],
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'Job':
        return cls(
            name=d.get('name', ''),
            schedule=dict(d.get('schedule') or {}),
            prompt=d.get('prompt', ''),
            session=d.get('session', ''),
            mode=d.get('mode', ''),
            provider=d.get('provider', ''),
            model=d.get('model', ''),
            role=d.get('role', ''),
            system_prompt=d.get('system_prompt', ''),
            task_file=d.get('task_file', ''),
            tool_permission=dict(d.get('tool_permission') or {}),
            tools_deny=list(d.get('tools_deny') or []),
            retries=d.get('retries', 3),
            backoff=d.get('backoff', 60.0),
            timeout=d.get('timeout', 0),
            require_approval=d.get('require_approval', False),
            approve_model=d.get('approve_model', False),
            approval_pending=d.get('approval_pending', False),
            enabled=d.get('enabled', True),
            status=d.get('status', 'proposed'),
            created_at=d.get('created_at', ''),
            next_run_at=d.get('next_run_at', ''),
            last_run_at=d.get('last_run_at', ''),
            history=[JobRun.from_dict(r) for r in (d.get('history') or [])
                     if isinstance(r, dict)],
        )


class JobRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._jobs: dict[str, Job] = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        raw = data.get('jobs', []) if isinstance(data, dict) else []
        for d in raw if isinstance(raw, list) else []:
            if isinstance(d, dict) and d.get('name'):
                job = Job.from_dict(d)
                self._jobs[job.name] = job

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for job in self.all():
            if len(job.history) > HISTORY_MAX:
                job.history = job.history[-HISTORY_MAX:]
        tmp = self.path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps({'jobs': [j.to_dict() for j in self.all()]},
                                  indent=2))
        os.replace(tmp, self.path)

    def all(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.name)

    def find(self, name: str) -> Job | None:
        return self._jobs.get(name)

    def put(self, job: Job):
        self._jobs[job.name] = job
        self.save()

    def remove(self, name: str) -> bool:
        if name in self._jobs:
            del self._jobs[name]
            self.save()
            return True
        return False


def describe_schedule(job: Job) -> str:
    schedule = job.schedule or {}
    if schedule.get('cron'):
        return f"cron '{schedule['cron']}'"
    if schedule.get('interval'):
        return f'every {int(schedule["interval"])}s'
    if schedule.get('at'):
        return f'at {schedule["at"]}'
    return 'unscheduled'


def validate_schedule(schedule: dict):
    if not isinstance(schedule, dict):
        raise ValueError('schedule must be a mapping')
    if schedule.get('cron'):
        next_run(str(schedule['cron']), datetime.now(timezone.utc))
    elif schedule.get('at'):
        parse_dt(str(schedule['at']))
    elif not schedule.get('interval'):
        raise ValueError('schedule needs one of: cron, interval, at')


def job_session_name(name: str, when: datetime) -> str:
    ts = when.strftime('%Y%m%d_%H%M%S')
    session_id = session_id_hash('job', name, when.isoformat(), uuid4().hex)
    return f'job_{ts}_{session_id}'


def task_file_path(worktree: Path, job: 'Job') -> Path:
    if job.task_file:
        path = Path(job.task_file)
        if path.is_absolute():
            return path
        return (Path(worktree) / path).resolve()
    return (Path(worktree) / '.polyglav' / 'jobs' / f'{job.name}.md').resolve()


def ensure_task_file(worktree: Path, job: 'Job') -> Path:
    path = task_file_path(worktree, job)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TASK_TEMPLATE.format(name=job.name))
    return path


SUPERVISOR_ROLE = 'leader'

SUPERVISOR_TASK_TEMPLATE = """# {name}

## Task
Describe the standing goal the supervisor owns. On each run it plans, runs the
right teams or agents, parks any question it cannot decide for the user, and
finishes with a short summary.

## Done when
How we know this run succeeded.

## Notes
- The supervisor is the `leader` type: it coordinates and delegates, it does not
  implement. It may call `team`/`delegate` and `ask`.
- Under unattended mode a user question parks in .polyglav/asks.json. Answer it
  with /asks or POST /asks/<id>/answer, then resume the run's session.
"""


def add_supervisor_job(registry: 'JobRegistry', name: str, worktree: Path,
                       schedule: dict, task: str = '', task_file: str = '',
                       require_approval: bool = False) -> 'Job':
    if registry.find(name) is not None:
        raise ValueError(f'Job already exists: {name}')
    validate_schedule(schedule)
    job = Job(
        name=name,
        schedule=schedule,
        prompt=task or 'Lead the work, coordinate the teams, and report back.',
        role=SUPERVISOR_ROLE,
        mode='write',
        task_file=task_file or f'.polyglav/jobs/{name}.md',
        status='waiting_approval' if require_approval else 'approved',
        enabled=True,
        require_approval=require_approval,
    )
    path = task_file_path(Path(worktree), job)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SUPERVISOR_TASK_TEMPLATE.format(name=name))
    registry.put(job)
    return job


def read_task_file(worktree: Path, job: 'Job') -> str | None:
    path = task_file_path(worktree, job)
    if path.exists():
        return path.read_text()
    return None


def memory_file_path(worktree: Path, job: 'Job') -> Path:
    from .memory import memory_path
    return memory_path(worktree, 'job', job.name)


def read_memory(worktree: Path, job: 'Job') -> str:
    from .memory import read_memory as _read
    return _read(worktree, 'job', job.name)


def write_memory(worktree: Path, job: 'Job', text: str) -> Path:
    from .memory import write_memory as _write
    return _write(worktree, 'job', job.name, text)


def system_prompt_for(job: 'Job', worktree: Path, agent_role=None) -> str:
    parts = []
    if agent_role is not None and getattr(agent_role, 'system_prompt', ''):
        parts.append(agent_role.system_prompt)
    if job.task_file:
        content = read_task_file(worktree, job)
        if content is None:
            raise FileNotFoundError(
                f'task file not found: {task_file_path(worktree, job)}')
        body = content.strip()
        if body:
            parts.append(f'## Job task\n\n{body}')
    if job.system_prompt:
        parts.append(job.system_prompt)
    memory = read_memory(worktree, job)
    if memory:
        parts.append(f'## Run memory\n\n{memory}')
    if not parts:
        parts.append(DEFAULT_JOB_SYSTEM_PROMPT)
    return '\n\n'.join(parts).strip()


def publish(registry: JobRegistry, job: Job, print=print):
    now = datetime.now(timezone.utc)
    if not job.created_at:
        job.created_at = now.isoformat(timespec='seconds')
    next_at = compute_next_run(job, now)
    job.next_run_at = next_at.isoformat(timespec='seconds') if next_at else ''
    registry.put(job)
    if job.status == 'waiting_approval':
        gate = ('waiting_approval - each run needs its own approval '
                '(`polyglav jobs approve <name>`)')
    elif job.status == 'approved':
        gate = 'approved - runs on schedule'
    else:
        gate = ('proposed - approve it to activate '
                '(`polyglav jobs approve <name>` or /jobs approve <name>)')
    print(f'Added job: {job.name} [{job.status}]')
    print(f'  schedule: {describe_schedule(job)}')
    print(f'  next run: {job.next_run_at or "-"}')
    if job.task_file:
        print(f'  task file: {job.task_file} (edit it with `polyglav jobs edit {job.name}`)')
    print(f'  status:   {gate}')


def _fmt_dt(value: str) -> str:
    return value or '-'


def _uptime(created_at: str) -> str:
    if not created_at:
        return '-'
    try:
        start = parse_dt(created_at)
    except ValueError:
        return '-'
    total = max(0, int((datetime.now(timezone.utc) - start).total_seconds()))
    if total < 60:
        return f'{total}s'
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f'{days}d {hours}h'
    if hours:
        return f'{hours}h {minutes}m'
    return f'{minutes}m'


def render_list(registry: JobRegistry, print=print):
    jobs = registry.all()
    if not jobs:
        print('  (no jobs configured)')
        print('  Add one with: polyglav jobs add <name> --cron "0 2 * * *" --prompt "..."')
        return
    print(f'{len(jobs)} jobs:')
    for job in jobs:
        schedule = describe_schedule(job)
        next_at = _fmt_dt(job.next_run_at)
        last = _fmt_dt(job.last_run_at)
        gate = 'runnable' if job.ready_to_run() else (
            'waiting approval' if job.status == 'waiting_approval' else (
                'proposed' if job.status == 'proposed' else 'disabled'))
        print(f'  {job.name:<20} {schedule:<28} {job.status:<8} '
              f'{gate:<17} next: {next_at:<27} last: {last}')
    print('  (stop a job with: polyglav jobs stop <name> | '
          'polyglav jobs status for a runtime summary)')


def parked_asks_for_run(polyglav_dir: Path, session: str) -> list[dict]:
    if not session:
        return []
    from .asks import AskStore
    from .sessions.manager import SessionManager
    sessions_dir = Path(polyglav_dir) / 'sessions'
    if not sessions_dir.exists():
        return []
    manager = SessionManager(sessions_dir)
    seen: set[str] = set()
    queue = [session]
    while queue:
        name = queue.pop()
        if not name or name in seen:
            continue
        seen.add(name)
        loaded = manager.read(name)
        if loaded is not None:
            for child in (loaded.sub_sessions or []):
                if child not in seen:
                    queue.append(child)
    store = AskStore(Path(polyglav_dir) / 'asks.json')
    return [a.to_dict() for a in store.list('pending') if a.origin in seen]


def render_status(registry: JobRegistry, print=print):
    jobs = registry.all()
    if not jobs:
        print('  (no jobs configured)')
        return
    for job in jobs:
        total = len(job.history)
        ok = sum(1 for r in job.history if r.status == 'verified')
        failed = total - ok
        runs = f'{total} run(s)' if total else 'never fired'
        if total:
            runs += f' ({ok} ok, {failed} failed)'
        state = 'awaiting approval' if job.status == 'waiting_approval' else job.status
        if not job.enabled:
            state += ' (stopped)'
        last_error = '-'
        if job.history:
            last = job.history[-1]
            if last.status != 'verified' and last.reason:
                last_error = last.reason[:70]
        print(f'  {job.name:<20} {state:<20} {runs:<28} next: {_fmt_dt(job.next_run_at)}')
        print(f'      uptime: {_uptime(job.created_at):<12} last error: {last_error}')
        if job.history:
            last = job.history[-1]
            detail = f'{last.status} ({last.duration}s)'
            if last.reason:
                detail += f' {last.reason[:60]}'
            if last.session:
                detail += f' {last.session}'
            parked = parked_asks_for_run(registry.path.parent, last.session)
            if parked:
                detail += f' [{len(parked)} parked ask(s)]'
            print(f'      last run: {detail}')
        if job.require_approval:
            pending = job.approval_pending
            print('      approval: per-run - next run '
                  f'{"approved - will fire" if pending else "WAITING for approve"}')


def render_show(registry: JobRegistry, name: str, print=print) -> bool:
    job = registry.find(name)
    if job is None:
        print(f'  Job not found: {name}')
        return False
    print(f'{job.name} [{job.status}] {"enabled" if job.enabled else "disabled"}')
    print(f'  schedule:   {describe_schedule(job)}')
    if job.prompt:
        print(f'  prompt:     {job.prompt}')
    print(f'  session:    {job.session or "per-run job_<ts>_<code>"}')
    if job.task_file:
        print(f'  task file:  {job.task_file} '
              '(edit it - changes apply on the next run)')
    worktree = registry.path.parent.parent
    memory_text = read_memory(worktree, job)
    memory_rel = str(memory_file_path(worktree, job).relative_to(Path(worktree)))
    if memory_text:
        print(f'  memory:     {memory_rel}')
        print(f'    last run memory: {" ".join(memory_text.split())[:120]}')
    else:
        print(f'  memory:     {memory_rel} (written after the first run)')
    if job.mode:
        print(f'  mode:       {job.mode}')
    if job.role:
        print(f'  role:       {job.role}')
    if job.provider:
        print(f'  provider:   {job.provider}')
    if job.model:
        print(f'  model:      {job.model}')
    if job.tool_permission:
        print('  tool_permission: ' + json.dumps(job.tool_permission))
    if job.tools_deny:
        print(f'  tools.deny: {", ".join(job.tools_deny)}')
    if job.system_prompt:
        print(f'  system_prompt: {job.system_prompt[:80]}')
    print(f'  durability: retries={job.retries} backoff={job.backoff}s '
          f'timeout={f"{job.timeout}s" if job.timeout else "none"}')
    if job.require_approval:
        pending = 'yes (approved for next run)' if job.approval_pending \
            else 'no (each run waits for approval)'
        print(f'  approval:   per-run required - {pending}')
    print(f'  created:    {_fmt_dt(job.created_at)}')
    print(f'  next run:   {_fmt_dt(job.next_run_at)}')
    print(f'  last run:   {_fmt_dt(job.last_run_at)}')
    print(f'  history:    {len(job.history)} run(s)')
    if job.history:
        for run in reversed(job.history):
            span = f'{_fmt_dt(run.started_at)} -> {_fmt_dt(run.finished_at)}'
            detail = run.reason or ''
            print(f'    {run.status:<8} attempt {run.attempt}: {span} '
                  f'({run.duration}s){"  " + detail if detail else ""}')
            if run.session:
                print(f'      session: {run.session}')
    if job.history and job.history[-1].content:
        preview = ' '.join(job.history[-1].content.split())[:140]
        print(f'    last output: {preview}')
    return True