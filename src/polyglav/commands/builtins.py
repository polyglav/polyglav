import os
import sys
import json
from pathlib import Path

from .. import get_version
from ..config import (VERBOSITY_PRESETS, VERBOSITY_SCOPES, VERBOSITY_VALUES,
                       verbosity_level)
from ..config_service import ConfigError, ConfigService
from ..ui import DIM, RED, RESET

SUB_INDENT = 4


def _command_label(name, aliases):
    label = '/' + name
    if aliases:
        label += ', /' + ', /'.join(aliases)
    return label


def _render_commands(registry, names, chat=None):
    metas = {n: registry.meta.get(n, {}) for n in names}
    labels = {n: _command_label(n, metas[n].get('aliases', [])) for n in names}
    subs = {n: sorted(metas[n].get('subcommands', [])) for n in names}
    if chat is not None and 'tool' in subs:
        rows = _tool_rows(chat)
        if rows is None:
            subs['tool'].append(('(tool calling disabled)', ''))
        elif not rows:
            subs['tool'].append(('(no tools allowed)', ''))
        else:
            subs['tool'].extend(rows)
    max_label = max((len(l) for l in labels.values()), default=0)
    max_sub = max((len(s) + SUB_INDENT
                   for group in subs.values() for s, _ in group), default=0)
    desc_col = max(2 + max_label, max_sub) + 2
    for n in names:
        print(f'  {labels[n]:<{desc_col - 2}}{metas[n].get("description", "")}')
        for sub, sdesc in subs[n]:
            print(f'{" " * SUB_INDENT}{sub:<{desc_col - SUB_INDENT}}{sdesc}')


def _tool_rows(chat):
    chat._init_tooling()
    if not chat._tool_registry or not chat._tool_policy:
        return None
    return [(n, chat._tool_registry.info(n)['short']) for n in sorted(
        n for n in chat._tool_registry.names()
        if chat._tool_policy.allowed(
            n, chat._tool_registry.permission_for(n)))]


def _run_todo(chat, args):
    chat._init_tooling()
    if not chat._tool_registry:
        return 'Error: tool calling is disabled'
    return chat._tool_registry.execute('todo', args)


def _render_tool_detail(chat, name):
    info = chat._tool_registry.info(name)
    if not info:
        print(f'No help available for "{name}"')
        return
    action = chat._tool_policy.action(name, info['permission'])
    print(name)
    print(f'  {info["description"]}')
    print(f'  category: {info["category"]}')
    print(f'  permission: {info["permission"]}: {action}')
    props = info['parameters'].get('properties', {})
    required = info['parameters'].get('required', [])
    if props:
        print('  params:')
        for p, spec in props.items():
            req = 'required' if p in required else 'optional'
            print(f'    {p} ({req}): {spec.get("description", "")}')


def register_builtins(registry):
    chat = registry.chat_loop

    @registry.register('help',
                       description='Show available commands and tools (use /help <cmd|tool> for details)')
    def help_cmd(arg=''):
        arg = arg.strip().lstrip('/')
        if arg:
            canonical = registry.canonical(arg)
            if canonical:
                _render_commands(registry, [canonical], chat)
                return
            chat._init_tooling()
            if chat._tool_registry and chat._tool_registry.info(arg):
                _render_tool_detail(chat, arg)
                return
            print(f'No help available for "{arg}"')
            return
        print('Available commands:')
        _render_commands(registry, sorted(registry.meta), chat)
        rows = _tool_rows(chat)
        if rows:
            print('\nAvailable tools:')
            name_w = max(len(n) for n, _ in rows)
            for n, tdesc in rows:
                print(f'  {n:<{name_w + 2}}{tdesc}')
            print('Use /help <tool> for details')

    @registry.register('exit', aliases=['quit'], description='Exit the REPL')
    def exit_cmd(_=None):
        chat.session_auto_save()
        sys.exit(0)

    @registry.register('continue',
                       description='Resume the last active paused turn, or a parent or session ID')
    def continue_cmd(arg=''):
        target = arg.strip()
        if target:
            name = ''
            if target == 'parent':
                name = getattr(chat.current_session, 'parent_id', '') or ''
            else:
                run, resolved = chat.resolve_target(target)
                name = resolved or ''
            if not name:
                print(f'{RED}✗ Session not found: {target}{RESET}')
                return
            session = chat.sessions.read(name)
            if session is None:
                print(f'{RED}✗ Session not found: {name}{RESET}')
                return
            chat.session_auto_save()
            chat.current_session = session
            if hasattr(chat, '_sync_output_log'):
                chat._sync_output_log()
        result = chat.continue_turn()
        if result is not None and result.content:
            print(result.content)

    @registry.register('cancel', description='Cancel a paused turn')
    def cancel_cmd(_=None):
        chat.cancel_turn()

    @registry.register('status', description='Show the current session, runs, jobs, and plugins')
    def status_cmd(_=None):
        from ..modes import mode_name
        polyglav_dir = chat.config.local_path.parent
        n, chars = chat._context_size()
        mode = mode_name(chat.config, chat.current_session.mode or None)
        print(f'{DIM}@ Status{RESET}')
        print(f'  model:    {chat.config.get("provider")}/{chat.config.get("model")}')
        print(f'  mode:     {mode}')
        print(f'  session:  {chat.current_session.session_name} '
              f'({len(chat.current_session.turns)} turns, '
              f'{chat._human_chars(chars)} context)')
        runs = chat.runs.runs()
        active = [r for r in runs if r.status == 'running']
        print(f'  runs:     {len(runs)} total, {len(active)} active')
        for run in runs[-5:]:
            role = run.role or 'root'
            duration = f' {run.duration:.1f}s' if run.duration else ''
            print(f'    #{run.id} {role} [{run.status}]{duration} {run.session}')
        plugins = chat._plugin_manager.status() if getattr(chat, '_plugin_manager', None) else []
        if plugins:
            loaded = sum(1 for p in plugins if p.status == 'loaded')
            errors = sum(1 for p in plugins if p.status == 'error')
            print(f'  plugins:  {loaded} loaded, {len(plugins) - loaded} inactive, '
                  f'{errors} errors')
        jobs_path = polyglav_dir / 'jobs.json'
        if jobs_path.exists():
            try:
                jobs = json.loads(jobs_path.read_text()).get('jobs', [])
                enabled = sum(1 for j in jobs if j.get('enabled'))
                print(f'  jobs:     {len(jobs)} configured, {enabled} enabled')
            except (OSError, json.JSONDecodeError):
                print('  jobs:     unreadable jobs.json')
        fleet_path = polyglav_dir / 'fleet.state.json'
        if fleet_path.exists():
            try:
                state = json.loads(fleet_path.read_text()).get('agents', {})
                running = sum(1 for a in state.values()
                              if a.get('status') in ('running', 'ok'))
                print(f'  fleet:    {len(state)} agents, {running} running')
            except (OSError, json.JSONDecodeError):
                print('  fleet:    unreadable fleet.state.json')

    @registry.register('new', description='Start a new session')
    def new_cmd(_=None):
        chat.new_session()

    @registry.register('version', description='Show the Polyglav version')
    def version_cmd(_=None):
        print(f'Polyglav {get_version()}')

    @registry.register('verbosity', aliases=['verbose'],
                       description='Show or set display scopes')
    def verbosity_cmd(arg=''):
        parts = arg.strip().split()
        if not parts:
            print(f'{DIM}@ Verbosity: {chat.config.get("verbosity")}{RESET}')
            for scope in VERBOSITY_SCOPES:
                value = verbosity_level(chat.config, scope)
                options = '|'.join(VERBOSITY_VALUES[scope])
                print(f'  {scope:<10} {value:<10} {DIM}{options}{RESET}')
            return
        if parts[0] in ('preset', 'profile'):
            name = parts[1].lower() if len(parts) > 1 else ''
            if name not in VERBOSITY_PRESETS:
                print('Usage: /verbosity preset quiet|normal|verbose')
                return
            chat.config.set('verbosity', name)
            print(f'{DIM}@ Verbosity: {name}{RESET}')
            return
        if parts[0] == 'reset':
            if len(parts) == 1:
                for scope in VERBOSITY_SCOPES:
                    chat.config.unset(f'verbosity.{scope}')
                chat.config.unset('verbosity')
                print(f'{DIM}@ Verbosity: reset{RESET}')
                return
            scope = parts[1].lower()
            if scope not in VERBOSITY_SCOPES:
                print('Usage: /verbosity reset [thinking|output|status|tools|footer]')
                return
            chat.config.unset(f'verbosity.{scope}')
            print(f'{DIM}@ Verbosity {scope}: {verbosity_level(chat.config, scope)}{RESET}')
            return
        scope = parts[0].lower()
        if scope not in VERBOSITY_SCOPES:
            print('Usage: /verbosity [thinking|output|status|tools|footer] [value]')
            return
        value = parts[1].lower() if len(parts) > 1 else ''
        if not value:
            current = verbosity_level(chat.config, scope)
            options = ' | '.join(VERBOSITY_VALUES[scope])
            print(f'{DIM}@ Verbosity {scope}: {current}{RESET}')
            print(f'  options: {options}')
            return
        if value not in VERBOSITY_VALUES[scope]:
            options = ' | '.join(VERBOSITY_VALUES[scope])
            print(f'Usage: /verbosity {scope} [{options}]')
            return
        chat.config.set(f'verbosity.{scope}', value)
        print(f'{DIM}@ Verbosity {scope}: {value}{RESET}')

    @registry.register('thinking', aliases=['reasoning'],
                       description='Show or set reasoning scope (off, assistant, agent, all)')
    def thinking_cmd(arg=''):
        arg = arg.strip().lower()
        current = verbosity_level(chat.config, 'thinking')
        if arg in ('on', '1', 'true', 'yes', 'show'):
            new = 'all'
        elif arg in ('off', '0', 'false', 'no', 'hide'):
            new = 'off'
        elif arg in ('assistant', 'agent', 'all'):
            new = arg
        elif arg in ('', '?', 'status'):
            new = None
        else:
            print('Usage: /thinking [off|assistant|agent|all]'
                  f'  (current: {current})')
            return
        if new is None:
            print(f'{DIM}@ Thinking: {current}{RESET}')
        else:
            chat.config.set('verbosity.thinking', new)
            print(f'{DIM}@ Thinking: {new}{RESET}')

    @registry.register('mode', description='Show or switch the agent mode for this session (read or write)')
    def mode_cmd(arg=''):
        from ..modes import resolve_mode
        session_mode = chat.current_session.mode or None
        current, names = resolve_mode(chat.config, session_mode)
        arg = arg.strip()
        if not arg or arg in ('?', 'status'):
            print(f'{DIM}@ {current.name.capitalize()} mode{RESET}')
            return
        if arg not in names:
            print(f'{RED}✗ Unknown mode "{arg}" - valid modes: ' + ', '.join(names) + RESET)
            return
        chat.current_session.mode = arg
        chat.session_auto_save()
        print(f'{DIM}@ {arg.capitalize()} mode{RESET}')

    @registry.register('modes', description='List the available agent modes, or show one mode\'s instruction')
    def modes_cmd(arg=''):
        from ..modes import mode_list, resolve_mode
        arg = arg.strip()
        verbose = False
        if arg in ('--verbose', '-v'):
            verbose = True
            arg = ''
        elif arg.startswith(('--verbose ', '-v ')):
            verbose = True
            arg = arg.split(' ', 1)[1].strip()
        specs = {m.name: m for m in mode_list(chat.config)}
        if arg:
            spec = specs.get(arg)
            if spec is None:
                valid = ', '.join(sorted(specs))
                print(f'{RED}✗ Unknown mode "{arg}" - valid modes: {valid}{RESET}')
                return
            if verbose and spec.description:
                print(f'  {spec.description}')
            if spec.instruction:
                for line in spec.instruction.splitlines():
                    print(f'  {line}')
            else:
                print('  (no instruction)')
            return
        session_mode = chat.current_session.mode or None
        current, _ = resolve_mode(chat.config, session_mode)
        for mode in sorted(specs.values(), key=lambda m: m.name):
            label = '  ' + mode.name
            if verbose and mode.description:
                label += f'  {mode.description}'
            if mode.name == current.name:
                label += '  <-- current'
            print(label)

    @registry.register('config', description='Show, get, set, or unset config values (--global for the global config, --verbose for descriptions)')
    def config_cmd(arg=''):
        scope = 'local'
        verbose = False
        as_json = False
        text = arg.strip()
        while text:
            if text.startswith('--global'):
                scope = 'global'
                text = text[len('--global'):].lstrip()
            elif text.startswith('--local'):
                scope = 'local'
                text = text[len('--local'):].lstrip()
            elif text == '-v' or text == '--verbose':
                verbose = True
                text = ''
            elif text.startswith('--verbose '):
                verbose = True
                text = text[len('--verbose'):].lstrip()
            elif text.startswith('-v '):
                verbose = True
                text = text[len('-v'):].lstrip()
            elif text == '--json':
                as_json = True
                text = ''
            elif text.startswith('--json '):
                as_json = True
                text = text[len('--json'):].lstrip()
            else:
                break
        parts = text.split(maxsplit=1)
        if not text:
            service = ConfigService(chat.config)
            if as_json:
                service.render_json()
            else:
                service.render_listing(verbose=verbose)
            return
        key = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ''

        if key == 'reload' and not rest:
            old = {k: chat.config.get(k) for k in ('provider', 'base_url', 'model')}
            chat.config.reload()
            print('Config reloaded from disk')
            for k in ('provider', 'base_url', 'model'):
                if chat.config.get(k) != old[k]:
                    print(f'  {k}: {old[k]} → {chat.config.get(k)} - run /provider or /connect to apply')
            return

        if key == 'unset' and rest:
            k = rest.split(maxsplit=1)[0]
            try:
                ConfigService(chat.config).unset(k, scope=scope)
            except ConfigError as e:
                print(f'{RED}✗ {e}{RESET}')
                return
            print(f'Unset {k} ({scope} config)')
            return

        if not rest:
            if as_json:
                print(json.dumps(chat.config.get(key), indent=2))
            else:
                ConfigService(chat.config).render_detail(key)
            return

        if rest in ('-a', '-r') or rest.startswith('-a ') or rest.startswith('-r '):
            op = rest[:2]
            items = rest[2:].strip().split()
            current = chat.config.get(key)
            if not isinstance(current, list):
                print(f'Config {key} is not a list - cannot add/remove items')
                return
            changed = False
            for it in items:
                if op == '-a' and it not in current:
                    current.append(it)
                    changed = True
                elif op == '-r' and it in current:
                    current.remove(it)
                    changed = True
            if changed:
                try:
                    ConfigService(chat.config).set(key, current, scope=scope)
                except ConfigError as e:
                    print(f'{RED}✗ {e}{RESET}')
                    return
                print(f'Config {key} = {current} ({scope})')
            else:
                print(f'Config {key} unchanged ({current})')
            return

        try:
            value = json.loads(rest)
        except json.JSONDecodeError:
            value = rest
        try:
            ConfigService(chat.config).set(key, value, scope=scope)
        except ConfigError as e:
            print(f'{RED}✗ {e}{RESET}')
            return
        print(f'Config {key} = {value} ({scope})')

    @registry.register('session', description='Show or switch the active session', subcommands=[
        ('new', 'Start a new session'),
        ('load', 'Load a session'),
        ('save', 'Save the current session'),
    ])
    def session_cmd(arg=''):
        parts = arg.strip().split(maxsplit=2)
        action = parts[0] if parts else ''

        if not action:
            n, chars = chat._context_size()
            print(f'Current session: {chat.current_session.session_name} '
                  f'({n} messages · {chat._human_chars(chars)} context)')
            return

        if action == 'new':
            chat.new_session()
        elif action == 'load':
            name = parts[1] if len(parts) > 1 else ''
            if not name:
                print('Usage: /session load <name>')
                return
            s = chat.sessions.load(name)
            if s:
                chat.current_session = s
                n, chars = chat._context_size()
                print(f'Loaded session: {name} - {n} messages · '
                      f'{chat._human_chars(chars)} context')
                chat.preview_session(name, session=s)
                chat.current_session.add_command(f'/session load {name}')
                try:
                    answer = input(
                        '  Summarize & trim history before continuing? [Y/n] '
                    ).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return
                if answer not in ('n', 'no'):
                    chat.compact_session()
            else:
                print(f'Session not found: {name}')
        elif action == 'save':
            chat.session_auto_save()
            print('Session saved')
        else:
            _render_commands(registry, ['session'])

    @registry.register('compact',
                       description='Summarize the conversation and trim the context')
    def compact_cmd(_=None):
        chat.compact_session()

    @registry.register('summary',
                       description='Summarize the session without trimming the context')
    def summary_cmd(_=None):
        chat.summary_session()

    @registry.register('plugins', aliases=['plugin'],
                       description='Manage plugins', subcommands=[
        ('list', 'List installed plugins'),
        ('enable', 'Enable a plugin'),
        ('disable', 'Disable a plugin'),
        ('install', 'Install a plugin from a git URL or local path'),
        ('update', 'Update an installed plugin'),
        ('uninstall', 'Remove an installed plugin'),
    ])
    def plugins_cmd(arg=''):
        from ..plugins.manager import PluginManager, PluginError
        pm = getattr(chat, '_plugin_manager', None)
        if pm is None:
            pm = PluginManager(chat.config)
            pm.load()
        parts = arg.strip().split(maxsplit=2)
        if not arg or (parts and parts[0] == 'list'):
            _render_plugins(pm)
            return
        action = parts[0]
        if action in ('enable', 'disable'):
            if len(parts) < 2:
                print(f'Usage: /plugins {action} <name>')
                return
            _toggle_plugin(chat, pm, parts[1], action)
        elif action == 'install':
            _install_plugin(chat, pm, parts[1:])
        elif action == 'update':
            if len(parts) < 2:
                print('Usage: /plugins update <name>')
                return
            _update_plugin(chat, pm, parts[1])
        elif action == 'uninstall':
            if len(parts) < 2:
                print('Usage: /plugins uninstall <name>')
                return
            _uninstall_plugin(chat, pm, parts[1])
        elif pm.get(action):
            _render_plugin_detail(pm, pm.get(action))
        else:
            print(f'Unknown /plugins action or plugin: {action}')
            print('Usage: /plugins [list|enable|disable|install|update|uninstall|<name>]')

def _render_plugins(pm):
    infos = sorted(pm.status(), key=lambda i: i.name)
    if not infos:
        print('  (no plugins installed)')
        print('  Install one from a git URL or local path: /plugins install <source>')
        return
    for info in infos:
        parts = [f'{info.name} v{info.version}', info.origin, info.status]
        if info.error:
            parts.append(info.error)
        if info.requires:
            missing = [p for p, ok in pm.dep_status(info) if not ok]
            if missing:
                parts.append('needs: ' + ', '.join(missing))
        if info.depends:
            parts.append('depends: ' + ', '.join(info.depends))
        print('  ' + ' - '.join(parts))


def _render_plugin_detail(pm, info):
    print(f'{info.name} v{info.version} ({info.status})')
    print(f'  origin: {info.origin}')
    print(f'  description: {info.description or "(none)"}')
    print(f'  source: {info.source or "(none)"}')
    print(f'  entry: {info.entry}')
    if info.polyglav_version:
        print(f'  polyglav_version: {info.polyglav_version}')
    if info.python:
        print(f'  python: {info.python}')
    if info.requires:
        print('  requires:')
        for pkg, ok in pm.dep_status(info):
            print(f'    {pkg} - {"installed" if ok else "missing"}')
    if info.depends:
        print('  depends: ' + ', '.join(info.depends))
    provides = info.provides or {}
    for kind in ('tools', 'providers', 'commands'):
        items = provides.get(kind, [])
        if items:
            print(f'  {kind}: ' + ', '.join(items))
    if info.error:
        print(f'  error: {info.error}')


def _toggle_plugin(chat, pm, name, action):
    info = pm.get(name)
    if info is None:
        print(f'Plugin not installed: {name}')
        return
    plugins = [str(n) for n in (chat.config.get('plugins') or [])]
    if action == 'enable':
        if name not in plugins:
            plugins.append(name)
        print(f'Plugin {name} enabled (applies on next start)')
    else:
        if name in plugins:
            plugins.remove(name)
        print(f'Plugin {name} disabled (applies on next start)')
    chat.config.set('plugins', plugins)


def _refresh_registries(chat, pm):
    for name in ('roles', 'teams', 'skills'):
        registry = getattr(chat, name, None)
        if registry is not None:
            registry.reload(pm)


def _install_plugin(chat, pm, rest):
    if not rest:
        print('Usage: /plugins install <git-url|path> [--global] [--deps]')
        return
    from ..plugins.manager import PluginError
    source = rest[0]
    global_ = '--global' in rest
    deps = '--deps' in rest
    try:
        info = pm.install(source, global_=global_, deps=deps)
    except PluginError as e:
        print(f'Error installing plugin: {e}')
        return
    plugins = [str(n) for n in (chat.config.get('plugins') or [])]
    if info.name not in plugins:
        plugins.append(info.name)
        chat.config.set('plugins', plugins)
    _refresh_registries(chat, pm)
    print(f'Installed {info.name} v{info.version} - restart to activate')
    if info.status in ('incompatible', 'error', 'disabled'):
        print(f'  {info.status}: {info.error or "not loaded"}')
    if deps and info.requires:
        for pkg in info.requires:
            print(f'  dependency installed: {pkg}')


def _update_plugin(chat, pm, name):
    from ..plugins.manager import PluginError
    try:
        info = pm.update(name)
    except PluginError as e:
        print(f'Error updating plugin: {e}')
        return
    _refresh_registries(chat, pm)
    print(f'Updated {info.name} to v{info.version} - restart to apply')


def _uninstall_plugin(chat, pm, name):
    from ..plugins.manager import PluginError
    try:
        pm.uninstall(name)
    except PluginError as e:
        print(f'Error uninstalling plugin: {e}')
        return
    plugins = [n for n in (chat.config.get('plugins') or []) if n != name]
    chat.config.set('plugins', plugins)
    _refresh_registries(chat, pm)
    print(f'Uninstalled plugin: {name}')
