from __future__ import annotations

import json
import sys

from .config import Config, verbosity_level
from .engine import Engine
from .ui import HeadlessUI


def _engine_from_args(args) -> Engine:
    config = Config(path=getattr(args, 'path', None))
    provider = (getattr(args, 'provider', None) or '').strip()
    model = (getattr(args, 'model', None) or '').strip()
    if model:
        config.apply('model', f'{provider}/{model}' if provider and '/' not in model
                     else model)
    elif provider:
        current = str(config.get('model') or '')
        bare = current.split('/', 1)[-1] if current else ''
        if bare:
            config.apply('model', f'{provider}/{bare}')
    if getattr(args, 'base_url', None):
        config.apply('base_url', args.base_url)
    if getattr(args, 'mode', None):
        config.apply('mode', args.mode)
    auto = 'allow' if getattr(args, 'approve', None) is True else 'deny'
    ui = HeadlessUI(auto=auto, verbose=getattr(args, 'verbose', False),
                    stream=getattr(args, 'output', 'json') == 'text',
                    thinking_level=verbosity_level(config, 'thinking'),
                    footer_level=verbosity_level(config, 'footer'))
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


def _format_tokens(value: int) -> str:
    if value >= 1_000_000:
        text = f'{value / 1_000_000:.1f}M'
        return text.replace('.0M', 'M')
    if value >= 1_000:
        return f'{value / 1_000:.0f}k'
    return str(value)


def cmd_models(args) -> int:
    from .ui import NullUI
    config = Config(path=getattr(args, 'path', None))
    engine = Engine(config, ui=NullUI())
    action = getattr(args, 'action', None)
    if action == 'context':
        ref = (getattr(args, 'ref', '') or '').strip()
        try:
            tokens = int(getattr(args, 'tokens', 0) or 0)
        except (TypeError, ValueError):
            tokens = 0
        if not ref or tokens <= 0:
            print('Usage: polyglav models context <provider/model> <tokens>',
                  file=sys.stderr)
            return 1
        provider, _, model = engine.model_target(ref)
        if not model:
            print(f'Cannot resolve model: {ref}', file=sys.stderr)
            return 1
        if engine.models.find(provider, model) is None:
            engine.models.put(provider, model)
        engine.models.set_context_window(provider, model, tokens)
        print(f'{provider}/{model}: context budget {tokens:,} tokens')
        return 0
    if action != 'list':
        entries = engine.models.all()
        if not entries:
            print('No models configured yet - run /connect to add one')
            return 0
        provider, _, model = engine.model_target()
        for group, items in engine.models.grouped():
            print(group + ':')
            for e in items:
                active = '>' if (e.provider == provider and e.model == model) else ' '
                key = ' (key)' if engine.providers.api_key_for(e.provider) else ''
                budget = getattr(e, 'context_window', 0) or 0
                ctx = f' (ctx={_format_tokens(budget)})' if budget else ''
                print(f'  {active} {e.model}{key}{ctx}')
        return 0
    target_provider, target_url, target_model = engine.model_target()
    provider = (getattr(args, 'provider', '') or '').strip() or target_provider
    entry = engine.providers.find(provider)
    base_url = (entry.base_url if entry and entry.base_url else '') or target_url
    api_key = engine.providers.api_key_for(provider)
    model = next((e.model for e in engine.models.all() if e.provider == provider),
                 None) or target_model
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
                    footer_level=verbosity_level(config, 'footer'))
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
