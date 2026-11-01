import os
import shlex
import subprocess
import sys
from pathlib import Path

from polyglav.config import Config
from polyglav.plugins.manager import PluginManager

from jobs import (Job, JobRegistry, ensure_task_file, publish, read_memory,
                  render_list, render_show, render_status, validate_schedule)
from scheduler import JobScheduler


def _store_task_file(worktree: Path, value: str) -> str:
    if not value:
        return ''
    path = Path(value)
    if not path.is_absolute():
        path = (Path(worktree) / path).resolve()
    try:
        return str(path.relative_to(Path(worktree)))
    except ValueError:
        return str(path)


def cmd_jobs(args, config: Config | None = None) -> int:
    config = config or Config(path=getattr(args, 'path', None))
    registry = JobRegistry(config.local_path.parent / 'jobs.json')
    pm = PluginManager(config)
    pm.load()
    memory_store = pm.service('memory')
    action = getattr(args, 'action', None)

    if action == 'list':
        render_list(registry)
        return 0
    if action == 'status':
        render_status(registry)
        return 0
    if action == 'show':
        return 0 if render_show(registry, args.name,
                                memory_store=memory_store) else 1
    if action == 'remove':
        if registry.remove(args.name):
            print(f'Removed job: {args.name}')
            return 0
        print(f'Job not found: {args.name}', file=sys.stderr)
        return 1
    if action in ('approve', 'reject', 'enable', 'disable'):
        job = registry.find(args.name)
        if job is None:
            print(f'Job not found: {args.name}', file=sys.stderr)
            return 1
        if action == 'approve':
            job.status = 'approved'
            job.enabled = True
            if job.require_approval:
                job.approval_pending = True
        elif action == 'reject':
            job.status = 'proposed'
            job.enabled = False
            job.approval_pending = False
        elif action == 'enable':
            job.enabled = True
        else:
            job.enabled = False
        registry.save()
        print(f'Job {args.name}: status={job.status}, '
              f'{"enabled" if job.enabled else "disabled"}')
        return 0
    if action == 'add':
        file_arg = getattr(args, 'file', None) or ''
        prompt = getattr(args, 'prompt', '') or ''
        if not prompt and not file_arg:
            print('Error: a --prompt or --file is required', file=sys.stderr)
            return 1
        schedule = {}
        if getattr(args, 'cron', None):
            schedule['cron'] = args.cron
        elif getattr(args, 'interval', None):
            schedule['interval'] = args.interval
        elif getattr(args, 'at', None):
            schedule['at'] = args.at
        tool_permission: dict = {}
        for pair in getattr(args, 'tool_permission', []) or []:
            if '=' not in pair:
                print(f'Invalid --tool-permission "{pair}" '
                      '(want category=action)', file=sys.stderr)
                return 1
            category, _, action_name = pair.partition('=')
            tool_permission[category.strip()] = action_name.strip()
        try:
            validate_schedule(schedule)
        except ValueError as e:
            print(f'Error: {e}', file=sys.stderr)
            return 1
        if registry.find(args.name) is not None:
            print(f'Job already exists: {args.name} '
                  '(use `polyglav jobs show` first)', file=sys.stderr)
            return 1
        require_approval = bool(getattr(args, 'require_approval', False))
        job = Job(
            name=args.name,
            schedule=schedule,
            prompt=prompt,
            session=getattr(args, 'session', '') or '',
            mode=getattr(args, 'mode', '') or 'write',
            provider=getattr(args, 'provider', '') or '',
            model=getattr(args, 'model', '') or '',
            role=getattr(args, 'role', '') or '',
            team=getattr(args, 'team', '') or '',
            supervisor=getattr(args, 'supervisor', '') or '',
            system_prompt=getattr(args, 'system_prompt', '') or '',
            task_file=_store_task_file(config.local_path.parent.parent, file_arg),
            tool_permission=tool_permission,
            tools_deny=list(getattr(args, 'tools_deny', []) or []),
            retries=getattr(args, 'retries', 3),
            backoff=getattr(args, 'backoff', 60.0),
            timeout=getattr(args, 'timeout', 0),
            require_approval=require_approval,
            approve_model=bool(getattr(args, 'approve_model', False)),
            enabled=getattr(args, 'approval', 'manual') == 'auto',
            status=('approved' if getattr(args, 'approval', 'manual') == 'auto'
                    else 'proposed'),
        )
        if require_approval:
            job.status = 'waiting_approval'
            job.approval_pending = False
        if job.task_file:
            ensure_task_file(config.local_path.parent.parent, job)
        publish(registry, job)
        return 0
    if action == 'edit':
        job = registry.find(args.name)
        if job is None:
            print(f'Job not found: {args.name}', file=sys.stderr)
            return 1
        path = ensure_task_file(config.local_path.parent.parent, job)
        editor = os.environ.get('EDITOR') or os.environ.get('VISUAL') or 'vi'
        try:
            code = subprocess.call(shlex.split(editor) + [str(path)])
        except OSError as e:
            print(f'Error opening editor "{editor}": {e}', file=sys.stderr)
            return 1
        return 0 if code == 0 else 1
    if action == 'run':
        return _jobs_run(config, registry, args)
    if action == 'daemon':
        scheduler = JobScheduler(
            config, verbose=not getattr(args, 'quiet', False))
        return scheduler.daemon(tick_seconds=getattr(args, 'tick', 15.0))
    print('Usage: polyglav jobs [list|status|show|add|approve|reject|enable|'
          'disable|edit|remove|run|daemon]')
    return 1


def _jobs_run(config: Config, registry: JobRegistry, args) -> int:
    job = registry.find(args.name)
    if job is None:
        print(f'Job not found: {args.name}', file=sys.stderr)
        return 1
    verbose = bool(getattr(args, 'verbose', False))
    scheduler = JobScheduler(config, verbose=verbose, stream=verbose)
    original_retries, original_backoff = job.retries, job.backoff
    try:
        if getattr(args, 'no_retry', False):
            job.retries, job.backoff = 0, 0
        run = scheduler.run_job(job)
    finally:
        job.retries, job.backoff = original_retries, original_backoff
        registry.save()
    print(f'Run {job.name}: {run.status} ({run.duration}s)')
    if not verbose and run.content:
        print(run.content)
    if run.reason:
        print(f'  reason: {run.reason}')
    if run.session:
        print(f'  session: {run.session}')
    pm = PluginManager(config)
    pm.load()
    memory = read_memory(config.local_path.parent.parent, job,
                         pm.service('memory'))
    if memory:
        print(f'  summary: {" ".join(memory.split())[:200]}')
    return 0 if run.status == 'verified' else 1
