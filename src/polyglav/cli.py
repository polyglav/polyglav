from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .config import Config, verbosity_level
from .engine import Engine
from .ui import HeadlessUI


def _engine_from_args(args) -> Engine:
    config = Config(path=getattr(args, 'path', None))
    if getattr(args, 'provider', None):
        config.apply('provider', args.provider)
    if getattr(args, 'model', None):
        config.apply('model', args.model)
    if getattr(args, 'base_url', None):
        config.apply('base_url', args.base_url)
    if getattr(args, 'mode', None):
        config.apply('mode', args.mode)
    auto = 'allow' if getattr(args, 'approve', None) is True else 'deny'
    ui = HeadlessUI(auto=auto, verbose=getattr(args, 'verbose', False),
                    stream=getattr(args, 'output', 'json') == 'text',
                    thinking_level=verbosity_level(config, 'thinking'),
                    footer_level=verbosity_level(config, 'footer'),
                    footer_tokens=config.get('footer_tokens', ['context']))
    approve_models = bool(getattr(args, 'model', None)) or bool(
        getattr(args, 'approve_model', False))
    return Engine(config, ui=ui, approve_models=approve_models)


def cmd_run(args) -> int:
    engine = _engine_from_args(args)
    engine.load_or_create_session(None)
    result = engine.chat(args.prompt, origin='cli')
    if args.output == 'json':
        sys.stdout.write(json.dumps(result.to_dict(), indent=2) + '\n')
    return 0 if result.status in ('ok', 'truncated') else 1


def cmd_models(args) -> int:
    from .ui import NullUI
    config = Config(path=getattr(args, 'path', None))
    engine = Engine(config, ui=NullUI())
    if getattr(args, 'action', None) != 'list':
        entries = engine.models.all()
        if not entries:
            print('No models configured yet - run /connect to add one')
            return 0
        provider = config.get('provider')
        model = config.get('model')
        for group, items in engine.models.grouped():
            print(group + ':')
            for e in items:
                active = '>' if (e.provider == provider and e.model == model) else ' '
                key = ' (key)' if engine.providers.api_key_for(e.provider) else ''
                print(f'  {active} {e.model}{key}')
        return 0
    provider = (getattr(args, 'provider', '') or '').strip() or config.get('provider') or ''
    entry = engine.providers.find(provider)
    base_url = (entry.base_url if entry and entry.base_url else '') or \
        config.get('base_url') or ''
    api_key = engine.providers.api_key_for(provider)
    model = next((e.model for e in engine.models.all() if e.provider == provider),
                 None) or config.get('model')
    models, error = engine.list_models(provider=provider, base_url=base_url,
                                       api_key=api_key, model=model)
    if error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    if not models:
        print(f'No models listed from {provider} ({base_url})')
        return 0
    print(f'{len(models)} models available from {provider} ({base_url}):')
    for m in models:
        print(f'  - {m}')
    return 0


def cmd_mcp(args) -> int:
    config = Config(path=args.path)
    ui = HeadlessUI(auto='deny', verbose=False, stream=False,
                    thinking_level=verbosity_level(config, 'thinking'),
                    footer_level=verbosity_level(config, 'footer'),
                    footer_tokens=config.get('footer_tokens', ['context']))
    engine = Engine(config, ui=ui)
    pm = getattr(engine, '_plugin_manager', None)
    service = pm.service('mcp_server') if pm is not None else None
    if service is None:
        print('MCP server unavailable - polyglav-core-mcp plugin not loaded',
              file=sys.stderr)
        return 1
    service.serve_stdio(engine)
    return 0


def _parse_config_value(value: str | None):
    if value is None:
        return _MISSING_VALUE
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


_MISSING_VALUE = object()


def cmd_config(args) -> int:
    config = Config(path=getattr(args, 'path', None))
    from .config_service import ConfigError, ConfigService
    service = ConfigService(config)
    scope = 'global' if getattr(args, 'global_', False) else 'local'
    action = getattr(args, 'action', None)

    if action == 'get':
        keys = getattr(args, 'key', None)
        if getattr(args, 'json_', False):
            if not keys:
                service.render_json()
            else:
                if isinstance(keys, str):
                    keys = [keys]
                service.render_json(keys, grouped=False)
            return 0
        if not keys:
            keys = list(config.data)
        elif isinstance(keys, str):
            keys = [keys]
        for key in keys:
            try:
                value = service.get(key)
            except ConfigError as e:
                print(f'Error: {e}', file=sys.stderr)
                return 1
            line = f'{key} = {value}'
            if getattr(args, 'show_origin', False):
                line += f'  ({service.origin(key)})'
            print(line)
        return 0

    if action == 'set':
        value = _parse_config_value(args.value)
        if value is _MISSING_VALUE:
            print(f'Error: a value is required to set "{args.key}"', file=sys.stderr)
            return 1
        try:
            service.set(args.key, value, scope=scope)
        except ConfigError as e:
            print(f'Error: {e}', file=sys.stderr)
            return 1
        print(f'{args.key} = {value} (saved to {scope} config)')
        return 0

    if action == 'unset':
        try:
            service.unset(args.key, scope=scope)
        except ConfigError as e:
            print(f'Error: {e}', file=sys.stderr)
            return 1
        print(f'Unset {args.key} ({scope} config)')
        return 0

    if action == 'reload':
        service.reload()
        print('Config reloaded from disk')
        return 0

    return 0


def cmd_plugins(args) -> int:
    from .plugins.manager import PluginManager, PluginError, load_plugin_test_suite
    config = Config(path=getattr(args, 'path', None))
    pm = PluginManager(config)
    pm.load()
    if args.action == 'test':
        return _plugins_run_tests(pm, args)
    if args.action == 'list':
        infos = sorted(pm.status(), key=lambda i: i.name)
        if not infos:
            print('(no plugins installed)')
            return 0
        for info in infos:
            parts = [f'{info.name} v{info.version}', info.origin, info.status]
            if info.error:
                parts.append(info.error)
            missing = [p for p, ok in pm.dep_status(info) if not ok]
            if missing:
                parts.append('needs: ' + ', '.join(missing))
            print('  ' + ' - '.join(parts))
        return 0
    if args.action in ('enable', 'disable'):
        if pm.get(args.name) is None:
            print(f'Plugin not installed: {args.name}', file=sys.stderr)
            return 1
        plugins = [str(n) for n in (config.get('plugins') or [])]
        if args.action == 'enable':
            if args.name not in plugins:
                plugins.append(args.name)
            print(f'Plugin {args.name} enabled (applies on next start)')
        else:
            if args.name in plugins:
                plugins.remove(args.name)
            print(f'Plugin {args.name} disabled (applies on next start)')
        config.set('plugins', plugins)
        return 0
    try:
        if args.action == 'install':
            info = pm.install(args.source, global_=getattr(args, 'global_', False),
                              deps=getattr(args, 'deps', False))
            plugins = [str(n) for n in (config.get('plugins') or [])]
            if info.name not in plugins:
                plugins.append(info.name)
                config.set('plugins', plugins)
            print(f'Installed {info.name} v{info.version} ({info.status})')
            if info.status in ('incompatible', 'error', 'disabled'):
                print(f'{info.status}: {info.error or "not loaded"}', file=sys.stderr)
        elif args.action == 'update':
            info = pm.update(args.name)
            print(f'Updated {info.name} to v{info.version} ({info.status})')
        elif args.action == 'uninstall':
            pm.uninstall(args.name)
            plugins = [n for n in (config.get('plugins') or []) if n != args.name]
            config.set('plugins', plugins)
            print(f'Uninstalled plugin: {args.name}')
    except PluginError as e:
        print(f'Error: {e}', file=sys.stderr)
        return 1
    return 0


def _plugins_run_tests(pm, args) -> int:
    import unittest

    from .plugins.manager import load_plugin_test_suite

    name = getattr(args, 'name', None)
    infos = [pm.get(name)] if name else [i for i in pm.status()]
    if name and infos[0] is None:
        print(f'Plugin not found: {name}', file=sys.stderr)
        return 1
    failed = False
    for info in infos:
        suite = load_plugin_test_suite(info.directory)
        count = suite.countTestCases()
        if name and count == 0:
            print(f'Plugin has no test suite: {info.name}', file=sys.stderr)
            return 1
        if count == 0:
            continue
        print(f'Running {info.name} tests ({count})...')
        result = unittest.TextTestRunner(
            stream=sys.stderr, verbosity=2 if getattr(args, 'verbose', False) else 1,
        ).run(suite)
        failed = failed or not result.wasSuccessful()
    return 1 if failed else 0


def cmd_jobs(args) -> int:
    from .jobs import (Job, JobRegistry, publish, render_list, render_show,
                       render_status, validate_schedule)
    config = Config(path=getattr(args, 'path', None))
    registry = JobRegistry(config.local_path.parent / 'jobs.json')
    action = getattr(args, 'action', None)

    if action == 'list':
        render_list(registry)
        return 0
    if action == 'status':
        render_status(registry)
        return 0
    if action == 'show':
        return 0 if render_show(registry, args.name) else 1
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
            system_prompt=getattr(args, 'system_prompt', '') or '',
            task_file=_store_task_file(config.local_path.parent.parent, file_arg),
            tool_permission=tool_permission,
            tools_deny=list(getattr(args, 'tools_deny', []) or []),
            retries=getattr(args, 'retries', 3),
            backoff=getattr(args, 'backoff', 60.0),
            timeout=getattr(args, 'timeout', 0),
            require_approval=require_approval,
            approve_model=bool(getattr(args, 'approve_model', False)),
            enabled=args.approval == 'auto',
            status='approved' if args.approval == 'auto' else 'proposed',
        )
        if require_approval:
            job.status = 'waiting_approval'
            job.approval_pending = False
        if job.task_file:
            from .jobs import ensure_task_file
            ensure_task_file(config.local_path.parent.parent, job)
        publish(registry, job)
        return 0
    if action == 'edit':
        job = registry.find(args.name)
        if job is None:
            print(f'Job not found: {args.name}', file=sys.stderr)
            return 1
        from .jobs import ensure_task_file
        path = ensure_task_file(config.local_path.parent.parent, job)
        editor = os.environ.get('EDITOR') or os.environ.get('VISUAL') or 'vi'
        import shlex
        import subprocess
        try:
            code = subprocess.call(shlex.split(editor) + [str(path)])
        except OSError as e:
            print(f'Error opening editor "{editor}": {e}', file=sys.stderr)
            return 1
        return 0 if code == 0 else 1
    if action == 'run':
        return _jobs_run(config, registry, args)
    if action == 'daemon':
        from .scheduler import JobScheduler
        scheduler = JobScheduler(config,
                                 verbose=not getattr(args, 'quiet', False))
        return scheduler.daemon(tick_seconds=getattr(args, 'tick', 15.0))
    print('Usage: polyglav jobs [list|status|show|add|approve|reject|enable|'
          'disable|edit|remove|run|daemon]')
    return 1


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


def _jobs_run(config, registry, args) -> int:
    from .scheduler import JobScheduler
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
    from .jobs import read_memory
    memory = read_memory(config.local_path.parent.parent, job)
    if memory:
        print(f'  summary: {" ".join(memory.split())[:200]}')
    return 0 if run.status == 'verified' else 1
