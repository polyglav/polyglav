import os
import sys
import json
from pathlib import Path

from .. import get_version
from ..sessions.render import render_session, render_turn, turn_summary

SUB_INDENT = 4


def _command_label(name, aliases):
    label = '/' + name
    if aliases:
        label += ', /' + ', /'.join(aliases)
    return label


def _render_commands(registry, names, chat=None):
    metas = {n: registry.meta.get(n, {}) for n in names}
    labels = {n: _command_label(n, metas[n].get('aliases', [])) for n in names}
    max_label = max((len(l) for l in labels.values()), default=0)
    desc_col = 2 + max_label + 2
    for n in names:
        print(f'  {labels[n]:<{desc_col - 2}}{metas[n].get("description", "")}')
        subs = list(metas[n].get('subcommands', []))
        if chat is not None and n == 'tool':
            rows = _tool_rows(chat)
            if rows is None:
                subs.append(('(tool calling disabled)', ''))
            elif not rows:
                subs.append(('(no tools allowed)', ''))
            else:
                subs.extend(rows)
        for sub, sdesc in subs:
            print(f'{" " * SUB_INDENT}{sub:<{desc_col - SUB_INDENT}}{sdesc}')


def _tool_rows(chat):
    chat._init_tooling()
    if not chat._tool_registry or not chat._tool_policy:
        return None
    return [(n, chat._tool_registry.info(n)['short']) for n in sorted(
        n for n in chat._tool_registry.names()
        if chat._tool_policy.allowed(
            n, chat._tool_registry.permission_for(n)))]


def _render_models(models, provider, base_url):
    print(f'{len(models)} models available from {provider} ({base_url}):')
    for m in models:
        print(f'  - {m}')


def _active_model(chat, entry):
    return (entry.provider == chat.config.get('provider')
            and entry.model == chat.config.get('model'))


def _focus_manager(chat):
    return getattr(chat, '_focus', None) or getattr(chat, 'focus', None)


def _focus_label(engine):
    run = getattr(engine, 'current_run', None)
    prefix = f'#{run.id} ' if run is not None else ''
    role = engine.role or 'root'
    session_id = f' [{run.session_id}]' if run is not None and run.session_id else ''
    return f'{prefix}{role} ({engine.current_session.session_name}{session_id})'


def _focus_run_line(run, current_id, indent=0):
    mark = '*' if run.id == current_id else ' '
    role = run.role or 'root'
    task = (run.task or '').strip().splitlines()
    head = task[0][:60] if task else ''
    line = f'{"  " * indent}{mark} #{run.id} {role} [{run.status}] {run.session}'
    if run.session_id:
        line += f' {run.session_id}'
    if head:
        line += f'  {head}'
    if run.id != current_id:
        line += f'  ↔ Switch to {role}'
    return line


def _focus_tree(runs, run, current_id, indent=0):
    print(_focus_run_line(run, current_id, indent))
    for child in runs.children(run.id):
        _focus_tree(runs, child, current_id, indent + 1)


def _focus_index(arg):
    parts = arg.split()
    if len(parts) > 1 and parts[1].isdigit():
        return int(parts[1])
    return 1


def _focus_target(focus, runs, arg):
    current = getattr(focus.active, 'current_run', None)
    low = arg.lower()
    if low == 'back':
        return 'back', None
    if low == 'parent':
        if current is None or current.parent is None:
            return None, None
        return 'run', runs.get(current.parent)
    if low == 'child' or low.startswith('child '):
        if current is None:
            return None, None
        kids = runs.children(current.id)
        n = _focus_index(arg)
        return ('run', kids[n - 1]) if 1 <= n <= len(kids) else (None, None)
    if low == 'sibling' or low.startswith('sibling '):
        if current is None or current.parent is None:
            return None, None
        sibs = [r for r in runs.children(current.parent) if r.id != current.id]
        n = _focus_index(arg)
        return ('run', sibs[n - 1]) if 1 <= n <= len(sibs) else (None, None)
    if low in ('next', 'prev'):
        ordered = runs.runs()
        if current is None or current not in ordered:
            return None, None
        i = ordered.index(current) + (1 if low == 'next' else -1)
        return ('run', ordered[i]) if 0 <= i < len(ordered) else (None, None)
    if low == 'root':
        return 'run', focus.root.current_run
    explicit = arg.startswith('#')
    token = arg[1:] if explicit else arg
    if token.isdigit():
        run = runs.get(int(token))
        if run is not None:
            return 'run', run
        if not explicit:
            return None, None
    if explicit:
        return 'run', runs.find_by_session_id(token)
    if low.startswith('run:'):
        token = arg.split(':', 1)[1].strip()
        if token.isdigit():
            return 'run', runs.get(int(token))
        return 'run', runs.find_by_session_id(token)
    if low.startswith('session:'):
        name = arg.split(':', 1)[1].strip()
        found = next((r for r in runs.runs() if r.session == name), None)
        if found is not None:
            return 'run', found
        return 'session', name
    found = next((r for r in runs.runs() if r.session == arg), None)
    if found is not None:
        return 'run', found
    return None, None


def _focus_show(focus, runs):
    engine = focus.active
    current = getattr(engine, 'current_run', None)
    current_id = current.id if current is not None else -1
    print(f'Focused: {_focus_label(engine)}')
    print('Runs:')
    for run in runs.runs():
        if run.parent is None:
            _focus_tree(runs, run, current_id)
    print('Log:')
    for run in runs.runs():
        print('  ' + _focus_run_line(run, current_id))


def _focus_log(focus, parts):
    run = getattr(focus.active, 'current_run', None)
    if run is None:
        print('No focused run')
        return
    n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    lines = run.buffer_text().splitlines()
    if n and len(lines) > n:
        lines = lines[-n:]
    if not lines:
        print(f'Run #{run.id} has no buffered output')
        return
    header = f'Run #{run.id} {run.role or "root"} [{run.status}] ({run.session})'
    print(header)
    for line in lines:
        print(line)


def _live_session_for_run(chat, run_id):
    focus = _focus_manager(chat)
    engines = focus.engines() if focus is not None else [chat]
    for engine in engines:
        run = getattr(engine, 'current_run', None)
        if run is not None and run.id == run_id:
            return engine.current_session
    return None


def _target_session(chat, target):
    target = (target or '').strip()
    if not target:
        return None, 'Target not found: (empty)'
    if target.lower().startswith('session:'):
        name = target.split(':', 1)[1].strip()
        session = chat.sessions.read(name)
        return (session, '') if session is not None else _target_error(target)
    explicit = target.startswith('#')
    token = target[1:] if explicit else target
    run = chat.runs.get(int(token)) if token.isdigit() else None
    if run is None and explicit:
        run = chat.runs.find_by_session_id(token)
    if run is not None:
        session = _live_session_for_run(chat, run.id) or \
            chat.sessions.read(run.session)
        return (session, '') if session is not None else _target_error(target)
    if explicit:
        session = chat.sessions.find_by_session_id(token)
        return (session, '') if session is not None else _target_error(target)
    focus = _focus_manager(chat)
    if focus is not None:
        for run in chat.runs.runs():
            if run.role != target and run.session != target:
                continue
            engine = chat.runs.engine_for(run.id)
            if engine is not None:
                return engine.current_session, ''
            session = chat.sessions.read(run.session)
            return (session, '') if session is not None else _target_error(target)
    session = chat.sessions.read(target)
    return (session, '') if session is not None else _target_error(target)


def _target_error(target):
    return None, f'Target not found: {target}'


HISTORY_DEFAULT_LIMIT = 10
HISTORY_USAGE = ('Usage: /history [n|all] [--thoughts [all]] '
                 '[--run <target>]')


def _parse_history(arg):
    import shlex
    limit = HISTORY_DEFAULT_LIMIT
    thoughts: bool | str = False
    run_target = ''
    positional: list[str] = []
    tokens = shlex.split(arg)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == '--thoughts':
            thoughts = True
            if i + 1 < len(tokens) and tokens[i + 1] == 'all':
                thoughts = 'all'
                i += 2
                continue
            i += 1
        elif tok == '--run':
            if i + 1 >= len(tokens):
                return None, None, None, HISTORY_USAGE
            run_target = tokens[i + 1]
            i += 2
        elif tok.startswith('--run='):
            run_target = tok.split('=', 1)[1]
            i += 1
        else:
            positional.append(tok)
            i += 1
    if len(positional) > 1:
        return None, None, None, HISTORY_USAGE
    if positional:
        tok = positional[0]
        if tok == 'all':
            limit = 0
        elif tok.isdigit() and int(tok) > 0:
            limit = int(tok)
        else:
            return None, None, None, f'Unknown argument: {tok}'
    return limit, thoughts, run_target, ''


PRINT_USAGE = 'Usage: /print <n>[.<m>] [--full] [--run <target>]'


def _parse_print(arg):
    import shlex
    spec = ''
    full = False
    run_target = ''
    positional: list[str] = []
    tokens = shlex.split(arg)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == '--full':
            full = True
            i += 1
        elif tok == '--run':
            if i + 1 >= len(tokens):
                return None, None, None, PRINT_USAGE
            run_target = tokens[i + 1]
            i += 2
        elif tok.startswith('--run='):
            run_target = tok.split('=', 1)[1]
            i += 1
        else:
            positional.append(tok)
            i += 1
    if len(positional) > 1:
        return None, None, None, PRINT_USAGE
    if positional:
        spec = positional[0]
    if not spec:
        return None, None, None, PRINT_USAGE
    return spec, full, run_target, ''


def _parse_turn_ref(spec):
    token = spec[1:] if spec.startswith('#') else spec
    pieces = token.split('.', 1)
    n_str = pieces[0]
    m_str = pieces[1] if len(pieces) > 1 else ''
    if not n_str.isdigit() or int(n_str) <= 0:
        return None, None, f'Invalid turn: {spec}'
    m = None
    if m_str:
        if not m_str.isdigit() or int(m_str) <= 0:
            return None, None, f'Invalid part: {spec}'
        m = int(m_str)
    return int(n_str), m, ''


def _render_known_models(chat):
    entries = chat.models.all()
    if not entries:
        print('No models configured yet - run /connect to add one')
        return
    for group, items in chat.models.grouped():
        print(group + ':')
        for e in items:
            active = '>' if _active_model(chat, e) else ' '
            key = ' (key)' if chat.providers.api_key_for(e.provider) else ''
            print(f'  {active} {e.model}{key}')


def _render_online_models(chat, provider_arg):
    provider = (provider_arg.strip() or chat.config.get('provider')).strip()
    entry = chat.providers.find(provider)
    base_url = (entry.base_url if entry and entry.base_url else '') or \
        chat.config.get('base_url') or ''
    api_key = chat.providers.api_key_for(provider)
    model = next((e.model for e in chat.models.all() if e.provider == provider),
                 None) or chat.config.get('model')
    try:
        models, error = chat.list_models(provider=provider, base_url=base_url,
                                         api_key=api_key, model=model)
    except Exception as e:
        models, error = [], str(e)
    if error:
        print(f'[Error] Failed to list models: {error}')
        print(f'  probing {provider} ({base_url}) - run /connect to fix')
        return
    if not models:
        print(f'No models listed from {provider} ({base_url})')
        return
    _render_models(models, provider, base_url)
    model = chat.config.get('model')
    if model and model not in models:
        print(f'  (configured model "{model}" not in the model list)')


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


def _normalize_url(url):
    if '://' not in url:
        url = 'https://' + url
    return url


def _derive_provider_name(url):
    import re
    from urllib.parse import urlparse
    host = [label for label in (urlparse(url).hostname or '').lower().split('.') if label]
    if host[:1] == ['www']:
        host = host[1:]
    name = '-'.join(host[-2:]) if len(host) > 1 else (host[0] if host else '')
    name = re.sub(r'[^a-z0-9-]', '-', name)
    return name or 'custom'


def _ordered_provider_names(providers):
    names = [n for n in sorted(providers) if n != 'openai-compatible']
    if 'ollama' in names:
        names.remove('ollama')
        names.insert(0, 'ollama')
    names.append('openai-compatible')
    return names


def _render_provider_list(chat, providers):
    extras = [e.provider for e in chat.providers.all()
              if e.provider not in providers]
    for i, name in enumerate(_ordered_provider_names(providers) + extras, 1):
        key = ' (key)' if chat.providers.api_key_for(name) else ''
        print(f'  {i}. {name}{key}')


def _connect_key_prompt(chat, provider):
    stored = chat.providers.api_key_for(provider)
    if stored:
        return input('  API key [<stored>]: ').strip() or stored
    return input('  API key (leave empty to skip): ').strip()


def _connect_save(chat, providers, provider, base_url, api_key):
    from ..providers import detect_provider
    detected = detect_provider(base_url, providers)
    if detected in providers and detected != 'openai-compatible' and detected != provider:
        print(f'  Detected provider "{detected}" from base URL - switching')
        provider = detected
    was_known = chat.providers.find(provider) is not None
    checkout = chat.config.get('connect_check', True)
    if checkout:
        ok, msg, _models = chat.check_connection(
            base_url=base_url, api_key=api_key, provider=provider)
        if not ok:
            print(f'  [Error] Connection test failed: {msg}')
            try:
                answer = input('  Save anyway? [Y/n] ').strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if answer in ('n', 'no'):
                print('  Connection not saved - run /connect again with corrected values')
                return
    chat.providers.put(provider, base_url, api_key)
    chat.config.set('provider', provider)
    if base_url:
        chat.config.set('base_url', base_url)
    chat._reinit_provider()
    verb = 'Updated' if was_known else 'Added'
    if checkout:
        print(f'Connected to {provider} ({base_url}) - {msg}')
    else:
        print(f'Connected to {provider} ({base_url})')
    print(f'  {verb} provider "{provider}"')
    print(f'  Pick a model with /models list {provider} or /model {provider}/<model>')


def _connect_named(chat, providers, factory, name, base_url=None):
    if base_url is None:
        base_url = factory.DEFAULT_BASE_URL
    if not base_url:
        try:
            base_url = input(
                f'  Base URL [{chat.config.get("base_url")}]: '
            ).strip() or chat.config.get('base_url')
        except (EOFError, KeyboardInterrupt):
            print()
            return
    api_key = _connect_key_prompt(chat, name)
    _connect_save(chat, providers, name, base_url, api_key)


def _connect_url(chat, providers, url, name):
    from ..providers import detect_provider
    url = _normalize_url(url)
    provider = None
    detected = detect_provider(url, providers)
    if detected != 'openai-compatible':
        provider = detected
    else:
        for pname, factory in providers.items():
            default = getattr(factory, 'DEFAULT_BASE_URL', '')
            if default and url.rstrip('/') == default.rstrip('/'):
                provider = pname
                break
    if provider is not None:
        print(f'  Detected provider "{provider}" from base URL')
        _connect_named(chat, providers, providers[provider], provider, base_url=url)
    else:
        pname = name or _derive_provider_name(url)
        if not name:
            print(f'  New provider name: {pname}')
        api_key = _connect_key_prompt(chat, pname)
        _connect_save(chat, providers, pname, url, api_key)


def _connect_pick(chat, providers):
    from ..providers.base import OpenAICompatibleProvider
    extras = {e.provider: e for e in chat.providers.all()
              if e.provider not in providers}
    names = _ordered_provider_names(providers) + sorted(extras)
    current = chat.config.get('provider')
    for i, name in enumerate(names, 1):
        key = ' (key)' if chat.providers.api_key_for(name) else ''
        print(f'  {i}. {name}{key}')
    try:
        sel = input(f'  Provider [{current}]: ').strip() or current
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not sel:
        return
    if sel.isdigit():
        try:
            sel = names[int(sel) - 1]
        except IndexError:
            print(f'  Unknown provider number "{sel}"')
            return
    if sel in providers:
        _connect_named(chat, providers, providers[sel], sel)
    elif sel in extras:
        entry = extras[sel]
        _connect_named(chat, providers, OpenAICompatibleProvider, sel,
                       base_url=entry.base_url or chat.config.get('base_url'))
    elif '.' in sel or '://' in sel:
        _connect_url(chat, providers, sel, None)
    else:
        print(f'  Unknown provider "{sel}" - pass a name, a number, or a URL')


def register_builtins(registry):
    chat = registry.chat_loop

    @registry.register('help', aliases=['h'],
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

    @registry.register('exit', aliases=['quit', 'q'], description='Exit the REPL')
    def exit_cmd(_=None):
        chat.session_auto_save()
        sys.exit(0)

    @registry.register('version', aliases=['v'], description='Show the Polyglav version')
    def version_cmd(_=None):
        print(f'Polyglav {get_version()}')

    @registry.register('model', description='Show or switch the active model; `/model <name>` sets it on the current provider, `/model <provider>/<model>` switches provider and model together')
    def model_cmd(arg=''):
        arg = arg.strip()
        if not arg:
            print(f'Current model: {chat.config.get("model")} '
                  f'({chat.config.get("provider")} @ {chat.config.get("base_url")})')
            return
        ref = chat.unfold_ref(arg)
        if ref is not None:
            provider, base_url, model = ref
            if chat._ensure_model_approved(provider, model):
                chat.config.set('provider', provider)
                chat.config.set('base_url', base_url)
                chat.config.set('model', model)
                chat._reinit_provider()
                print(f'Model set to: {provider}/{model}')
            else:
                print(f'Model not approved: {provider}/{model}')
            return
        chat.config.set('model', arg)
        chat.provider.model = chat.config.get('model')
        chat.models.put(chat.config.get('provider'), arg)
        print(f'Model set to: {arg}')

    @registry.register('provider', description='Show or switch the active provider')
    def provider_cmd(arg=''):
        if arg:
            chat.config.set('provider', arg.strip())
            chat._reinit_provider()
            print(f'Provider set to: {chat.config.get("provider")}')
            if chat.config.get('connect_check', True):
                ok, msg, _ = chat.check_connection()
                if not ok:
                    print(f'  Warning: connection test failed - {msg}')
                    print('  Run /connect to fix provider settings')
        else:
            print(f'Current provider: {chat.config.get("provider")}')

    @registry.register('thinking', aliases=['reasoning'],
                       description='Show or toggle streaming of thinking/reasoning tokens')
    def thinking_cmd(arg=''):
        arg = arg.strip().lower()
        current = chat.config.get('show_thinking', False)
        if arg in ('on', '1', 'true', 'yes', 'show'):
            new = True
        elif arg in ('off', '0', 'false', 'no', 'hide'):
            new = False
        elif arg in ('', '?', 'status'):
            new = None
        else:
            print(f"Usage: /thinking [on|off]  (current: {'on' if current else 'off'})")
            return
        if new is None:
            print(f'Thinking streaming: {"on" if current else "off"}')
        else:
            chat.config.set('show_thinking', new)
            print(f'Thinking streaming: {"on" if new else "off"}')

    @registry.register('unattended',
                       description='Show or toggle unattended mode (no stdin from any depth: '
                                   'confirms auto-deny, user asks route to the caller or '
                                   'return without pausing)')
    def unattended_cmd(arg=''):
        arg = arg.strip().lower()
        current = chat._is_unattended() if hasattr(chat, '_is_unattended') \
            else chat.config.get('unattended', False)
        if arg in ('on', '1', 'true', 'yes', 'enable'):
            new = True
        elif arg in ('off', '0', 'false', 'no', 'disable'):
            new = False
        elif arg in ('', '?', 'status'):
            new = None
        else:
            print(f"Usage: /unattended [on|off]  (current: {'on' if current else 'off'})")
            return
        if new is None:
            print(f'Unattended mode: {"on" if current else "off"}')
        else:
            chat.config.set('unattended', new)
            if hasattr(chat, 'set_unattended'):
                chat.set_unattended(new)
            print(f'Unattended mode: {"on" if new else "off"}')

    @registry.register('mode', description='Show or switch the agent mode for this session (read = read-only, write); persist with /config mode')
    def mode_cmd(arg=''):
        from ..modes import mode_list, resolve_mode
        session_mode = chat.current_session.mode or None
        current, names = resolve_mode(chat.config, session_mode)
        arg = arg.strip()
        if not arg or arg in ('?', 'status'):
            print(f'Current mode: {current.name}')
            specs = {m.name: m for m in mode_list(chat.config)}
            for m in sorted(specs.values(), key=lambda s: s.name):
                label = '  ' + m.name + ('  <-- current' if m.name == current.name else '')
                print(f'{label}')
                if m.instruction:
                    print(f'    {m.instruction.splitlines()[0][:80]}')
            return
        if arg not in names:
            print(f'Unknown mode "{arg}" - valid modes: ' + ', '.join(names))
            return
        chat.current_session.mode = arg
        chat.session_auto_save()
        print(f'Mode set to: {arg} (this session)')
        print(f'  Persist with: /config mode {arg}')

    @registry.register('models', description='List configured models, or probe a provider\'s available models', subcommands=[
        ('list', 'Probe a provider\'s advertised models (list [provider], default current)'),
    ])
    def models_cmd(arg=''):
        arg = arg.strip()
        if not arg:
            _render_known_models(chat)
        elif arg == 'list':
            _render_online_models(chat, '')
        elif arg.startswith('list '):
            _render_online_models(chat, arg[len('list'):].strip())
        else:
            print('Usage: /models [list [provider]]')

    @registry.register('roles', description='Manage roles', subcommands=[
        ('list', 'List roles (list <tag> filters by tag)'),
        ('show', 'Show a role definition'),
        ('new', 'Create or override a role (local)'),
        ('remove', 'Remove a role'),
    ])
    def role_cmd(arg=''):
        from ..roles import Role
        tr = chat.roles
        parts = arg.strip().split(maxsplit=1)
        action = parts[0] if parts else ''
        if not action or action == 'list':
            tag = ''
            if action == 'list' and len(parts) > 1:
                tag = parts[1].strip()
            roles = tr.all()
            if tag:
                roles = [t for t in roles if tag in t.tags]
            if not roles:
                if tag:
                    print(f'  (no roles tagged "{tag}")')
                    known = ', '.join(sorted({t for t in tr.all()
                                              for t in t.tags}))
                    if known:
                        print(f'  known tags: {known}')
                else:
                    print('  (no roles configured)')
                    print('  Create one with /roles new <name>, or edit '
                          f'{tr.local_path}')
                return
            label = f' tagged "{tag}"' if tag else ''
            print(f'{len(roles)} roles{label}:')
            for t in roles:
                model = f' [{t.model}]' if t.model else ''
                tags = f' tags={",".join(t.tags)}' if t.tags else ''
                origin = f' ({tr.origin(t.name)})'
                print(f'  - {t.name}{model}{tags}{origin}')
            return
        if action == 'show':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /roles show <name>')
                return
            t = tr.find(name)
            if t is None:
                print(f'Role not found: {name}')
                return
            print(f'{t.name} ({tr.origin(t.name)})')
            if t.description:
                print(f'  description: {t.description}')
            print(f'  system_prompt: {t.system_prompt or "(empty)"}')
            if t.instructions:
                print(f'  instructions: {t.instructions}')
            if t.tags:
                print(f'  tags: {", ".join(t.tags)}')
            if t.model:
                print(f'  model: {t.model}')
            if t.skills:
                print(f'  skills: {", ".join(t.skills)}')
            if t.tool_permission:
                print('  tool_permission: '
                      + json.dumps(t.tool_permission))
            return
        if action == 'new':
            rest = parts[1].strip() if len(parts) > 1 else ''
            if not rest:
                print('Usage: /roles new <name> [system prompt]')
                return
            name = rest.split(maxsplit=1)[0]
            prompt = rest[len(name):].strip()
            existing = tr.find(name)
            prev_origin = tr.origin(name)
            tr.put(Role(name=name, system_prompt=prompt), scope='local')
            target = (tr.local_path.parent / 'roles' / f'{name}.md'
                      if prompt else tr.local_path)
            if existing is not None:
                print(f'Overrode role: {name} (was {prev_origin}) - '
                      f'edit {target}')
            else:
                print(f'Created role: {name} (local) - edit {target}')
            return
        if action == 'remove':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /roles remove <name>')
                return
            if tr.remove(name):
                print(f'Removed role: {name} (local)')
            else:
                print(f'No local role to remove: {name}')
            return
        print('Usage: /roles [list|show <name>|new <name> [prompt]|remove <name>]')

    @registry.register('role', description='Show the current role')
    def current_role_cmd(arg=''):
        engine = chat.active() if hasattr(chat, 'active') else chat
        role = str(getattr(engine, 'role', '') or '')
        session = getattr(engine.current_session, 'session_name', '')
        if role:
            print(f'Role: {role} ({session})')
        else:
            print(f'Role: (root, no role bound) ({session})')

    @registry.register('teams', description='Manage teams', subcommands=[
        ('list', 'List teams (list <tag> filters by tag)'),
        ('show', 'Show a team definition'),
        ('new', 'Create or override a team (local)'),
        ('remove', 'Remove a team'),
        ('run', 'Run a team (run <name> <task>)'),
    ])
    def team_cmd(arg=''):
        from ..teams import Team
        tr = chat.teams
        parts = arg.strip().split(maxsplit=1)
        action = parts[0] if parts else ''
        if not action or action == 'list':
            tag = ''
            if action == 'list' and len(parts) > 1:
                tag = parts[1].strip()
            teams = tr.all()
            if tag:
                teams = [t for t in teams if tag in t.tags]
            if not teams:
                if tag:
                    print(f'  (no teams tagged "{tag}")')
                    known = ', '.join(sorted({t for t in tr.all()
                                              for t in t.tags}))
                    if known:
                        print(f'  known tags: {known}')
                else:
                    print('  (no teams configured)')
                    print('  Create one with /teams new <name>, or edit '
                          f'{tr.local_path}')
                return
            label = f' tagged "{tag}"' if tag else ''
            print(f'{len(teams)} teams{label}:')
            for t in teams:
                stages = ' > '.join(s.role for s in t.stages)
                tags = f' tags={",".join(t.tags)}' if t.tags else ''
                origin = f' ({tr.origin(t.name)})'
                print(f'  - {t.name}{tags}{origin}')
                if stages:
                    print(f'      {stages}')
            return
        if action == 'show':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /teams show <name>')
                return
            t = tr.find(name)
            if t is None:
                print(f'Team not found: {name}')
                return
            print(f'{t.name} ({tr.origin(t.name)})')
            if t.description:
                print(f'  description: {t.description}')
            if t.tags:
                print(f'  tags: {", ".join(t.tags)}')
            if not t.stages:
                print('  stages: (none)')
                return
            print('  stages:')
            for i, s in enumerate(t.stages, 1):
                print(f'    {i}. {s.role}'
                      + (f' [mode={s.mode}]' if s.mode else ''))
                if s.task_hint:
                    print(f'       task_hint: {s.task_hint}')
                if s.handoff_note:
                    print(f'       handoff_note: {s.handoff_note}')
            return
        if action == 'new':
            rest = parts[1].strip() if len(parts) > 1 else ''
            if not rest:
                print('Usage: /teams new <name> [description]')
                return
            name = rest.split(maxsplit=1)[0]
            description = rest[len(name):].strip()
            existing = tr.find(name)
            prev_origin = tr.origin(name)
            tr.put(Team(name=name, description=description), scope='local')
            if existing is not None:
                print(f'Overrode team: {name} (was {prev_origin}) - '
                      f'edit {tr.local_path} for stages')
            else:
                print(f'Created team: {name} (local) - edit {tr.local_path} '
                      'to add stages')
            return
        if action == 'remove':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /teams remove <name>')
                return
            if tr.remove(name):
                print(f'Removed team: {name} (local)')
            else:
                print(f'No local team to remove: {name}')
            return
        if action == 'run':
            rest = parts[1].strip() if len(parts) > 1 else ''
            name = rest.split(maxsplit=1)[0] if rest else ''
            task = rest[len(name):].strip() if name else ''
            if not name or not task:
                print('Usage: /teams run <name> <task>')
                return
            t = tr.find(name)
            if t is None:
                print(f'Team not found: {name}')
                return
            print(f'Running team {name} ({len(t.stages)} stages)')
            result = chat.run_team(t, task)
            for i, res in enumerate(result.stages, 1):
                dur = f' {res.duration:.1f}s' if res.duration else ''
                print(f'  {i}. {t.stages[i - 1].role:<16} {res.status}{dur}')
            if result.errors:
                msgs = [e.get('message', '') for e in result.errors
                        if isinstance(e, dict) and e.get('message')]
                if msgs:
                    print('  errors: ' + '; '.join(msgs))
            if result.content:
                print('--- final result ---')
                print(result.content)
            if result.memory:
                print(f'  team memory: {result.memory}')
            return
        print('Usage: /teams [list|show <name>|new <name> [description]|remove <name>|run <name> <task>]')

    @registry.register('skills', description='Manage skills', subcommands=[
        ('list', 'List skills'),
        ('show', 'Show a skill definition'),
        ('new', 'Create or override a skill (local)'),
        ('remove', 'Remove a skill'),
    ])
    def skill_cmd(arg=''):
        from ..skills import Skill
        sr = chat.skills
        parts = arg.strip().split(maxsplit=1)
        action = parts[0] if parts else ''
        if not action or action == 'list':
            skills = sr.all()
            if not skills:
                print('  (no skills configured)')
                print(f'  Create one with /skills new <name>, or add a '
                      f'<name>.md file to {sr.local_dir}')
                return
            print(f'{len(skills)} skills:')
            for s in skills:
                desc = f' - {s.description}' if s.description else ''
                origin = f' ({sr.origin(s.name)})'
                print(f'  - {s.name}{desc}{origin}')
            return
        if action == 'show':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /skills show <name>')
                return
            s = sr.find(name)
            if s is None:
                print(f'Skill not found: {name}')
                return
            print(f'{s.name} ({sr.origin(s.name)})')
            if s.tags:
                print(f'  tags: {", ".join(s.tags)}')
            if s.content:
                print(s.content.rstrip())
            else:
                print('  (empty)')
            return
        if action == 'new':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /skills new <name>')
                return
            existing = sr.find(name)
            prev_origin = sr.origin(name)
            sr.put(Skill(name=name, content=''), scope='local')
            if existing is not None:
                print(f'Overrode skill: {name} (was {prev_origin}) - '
                      f'edit {sr.local_dir / (name + ".md")}')
            else:
                print(f'Created skill: {name} (local) - '
                      f'edit {sr.local_dir / (name + ".md")}')
            return
        if action == 'remove':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /skills remove <name>')
                return
            if sr.remove(name):
                print(f'Removed skill: {name} (local)')
            elif sr.origin(name) == 'plugin':
                print(f'{name} comes from a plugin - override it with '
                      '/skills new <name>, or edit the local skills dir, '
                      'instead of removing')
            else:
                print(f'No local skill to remove: {name}')
            return
        print('Usage: /skills [list|show <name>|new <name>|remove <name>]')

    @registry.register('connect', description='Connect a provider - /connect <name|url> [name]')
    def connect_cmd(arg=''):
        from ..providers import PROVIDERS
        providers = dict(PROVIDERS)
        pm = getattr(chat, '_plugin_manager', None)
        if pm is not None:
            providers.update(pm.provider_classes())
        text = arg.strip()
        if not text:
            _connect_pick(chat, providers)
        elif text in providers:
            _connect_named(chat, providers, providers[text], text)
        else:
            url, _, name = text.partition(' ')
            url = url.strip()
            name = name.strip()
            if url and ('.' in url or '://' in url):
                _connect_url(chat, providers, url, name or None)
            else:
                print(f'Unknown provider "{text}" - pass a provider name or a URL '
                      '(e.g. /connect ollama or /connect https://...):')
                _render_provider_list(chat, providers)

    @registry.register('config', description='Show, get, set, or unset config values (--global for the global config)')
    def config_cmd(arg=''):
        scope = 'local'
        text = arg.strip()
        while text.startswith('--global') or text.startswith('--local'):
            scope = 'global' if text.startswith('--global') else 'local'
            flag_len = len('--global') if text.startswith('--global') else len('--local')
            text = text[flag_len:].lstrip()
        parts = text.split(maxsplit=1)
        if not text:
            for k, v in chat.config.data.items():
                print(f'  {k}: {v}  ({chat.config.origin(k)})')
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
            chat.config.unset(k, scope=scope)
            print(f'Unset {k} ({scope} config)')
            return

        if not rest:
            val = chat.config.get(key)
            print(f'  {key}: {val}  ({chat.config.origin(key)})')
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
                chat.config.set(key, current, scope=scope)
                print(f'Config {key} = {current} ({scope})')
            else:
                print(f'Config {key} unchanged ({current})')
            return

        if key not in chat.config.data:
            try:
                answer = input(
                    f'Unknown config key "{key}". Store anyway? [Y/n] '
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if answer in ('n', 'no'):
                print('Skipped')
                return

        try:
            value = json.loads(rest)
        except json.JSONDecodeError:
            value = rest
        chat.config.set(key, value, scope=scope)
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
            chat.current_session = chat.sessions.create(
                role=getattr(chat, 'role', ''))
            print(f'New session: {chat.current_session.session_name}')
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

    @registry.register('focus', description='Show and switch the focused agent run', subcommands=[
        ('', 'Show the current run, the run tree, and the run log'),
        ('<id|#id>', 'Attach to the run with that id'),
        ('#<session_id>', 'Attach to the run with that session id'),
        ('log [n]', "Print the focused run's buffered output"),
        ('session:<name>', 'Attach to the run using that session'),
        ('root', 'Attach to the root run'),
        ('parent', 'Attach to the parent run'),
        ('child [n]', 'Attach to the nth child run'),
        ('sibling [n]', 'Attach to the nth sibling run'),
        ('next', 'Attach to the next run in the call log'),
        ('prev', 'Attach to the previous run in the call log'),
        ('back', 'Return to the previous focus'),
    ])
    def focus_cmd(arg=''):
        focus = _focus_manager(chat)
        if focus is None:
            print('Focus is only available in the REPL')
            return
        arg = arg.strip()
        if not arg:
            _focus_show(focus, chat.runs)
            return
        if arg == 'log' or arg.startswith('log '):
            _focus_log(focus, arg.split())
            return
        kind, value = _focus_target(focus, chat.runs, arg)
        if kind == 'back':
            engine = focus.back()
            print(f'Focused: {_focus_label(engine)}')
            return
        if kind is None or value is None:
            print(f'Focus target not found: {arg}')
            return
        try:
            if kind == 'session':
                engine = focus.focus_session(value)
            else:
                engine = focus.enter(value.id)
        except ValueError as e:
            print(f'Cannot focus: {e}')
            return
        print(f'Focused: {_focus_label(engine)}')

    @registry.register('sessions', description='List or manage saved sessions', subcommands=[
        ('list', 'List saved sessions'),
        ('preview', 'Show a structural preview of a session'),
        ('delete', 'Delete a session'),
        ('export', 'Export a session to Markdown'),
    ])
    def sessions_cmd(arg=''):
        parts = arg.strip().split(maxsplit=2)
        action = parts[0] if parts else ''

        if not action or action == 'list':
            sessions = chat.sessions.list()
            if sessions:
                current = chat.sessions.current.session_name if chat.sessions.current else ''
                for s in sessions:
                    marker = '  <-- current' if s == current else ''
                    child = ''
                    if s.startswith('sub_'):
                        data = chat.sessions.read(s)
                        if data and getattr(data, 'parent_id', ''):
                            child = f'  (child of {data.parent_id})'
                    print(f'  {s}{marker}{child}')
            else:
                print('  No sessions found')
            return
        if action == 'preview':
            name = parts[1] if len(parts) > 1 else ''
            if not name:
                print('Usage: /sessions preview <name>')
                return
            s = chat.preview_session(name)
            if s is None:
                print(f'Session not found: {name}')
        elif action == 'delete':
            name = parts[1] if len(parts) > 1 else ''
            if not name:
                print('Usage: /sessions delete <name>')
                return
            if chat.sessions.delete(name):
                print(f'Deleted session: {name}')
            else:
                print(f'Session not found: {name}')
        elif action == 'export':
            name = parts[1] if len(parts) > 1 else ''
            out = parts[2] if len(parts) > 2 else ''
            if not name:
                print('Usage: /sessions export <name> [out]')
                return
            s = chat.sessions.read(name)
            if s is None:
                print(f'Session not found: {name}')
                return
            markdown = render_session(s)
            if out == '-':
                sys.stdout.write(markdown)
                return
            if out:
                path = Path(out)
            else:
                path = chat.sessions.sessions_dir.parent / 'exports' / f'{name}.md'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(markdown)
            print(f'Exported session: {name} -> {path}')
        else:
            _render_commands(registry, ['sessions'])

    @registry.register('history',
                       description='List the session turns as a numbered index '
                                   '(/history [n|all] [--thoughts [all]] [--run <target>])')
    def history_cmd(arg=''):
        limit, thoughts, run_target, error = _parse_history(arg)
        if error:
            print(error)
            return
        session = chat.current_session
        if run_target:
            session, error = _target_session(chat, run_target)
            if session is None:
                print(error)
                return
        turns = session.turns or []
        shown = turns if limit == 0 else turns[-limit:]
        role = f' [{session.role}]' if session.role else ''
        session_id = f' [{session.session_id}]' if session.session_id else ''
        print(f'{session.session_name} - {len(turns)} turns{role}{session_id}')
        for turn in shown:
            print(turn_summary(turn, thoughts=thoughts))
        print('/print <n> reprints a turn')

    @registry.register('print',
                       description='Reprint a turn (or one part) in full - '
                                   '/print <n>[.<m>] [--full] [--run <target>]')
    def print_cmd(arg=''):
        spec, full, run_target, error = _parse_print(arg)
        if error:
            print(error)
            return
        n, m, error = _parse_turn_ref(spec)
        if error:
            print(error)
            return
        session = chat.current_session
        if run_target:
            session, error = _target_session(chat, run_target)
            if session is None:
                print(error)
                return
        turn = next((t for t in (session.turns or [])
                     if t.get('index') == n), None)
        if turn is None:
            print(f'Turn not found: {n}')
            return
        parts = turn.get('parts') or []
        if m is not None and m > len(parts):
            print(f'Turn {n} has no part {m} (1-{len(parts)})')
            return
        cap = chat.config.get('print_max_chars', 4000)
        print(render_turn(turn, part=m, full=full, cap=cap))

    @registry.register('asks', description='List parked asks and answer them', subcommands=[
        ('list', 'List parked asks (list [all|pending|answered])'),
        ('show', 'Show a parked ask in full (show <id>)'),
        ('answer', 'Answer a parked ask (answer <id> <text>)'),
    ])
    def asks_cmd(arg=''):
        store = chat.asks
        parts = arg.strip().split(maxsplit=1)
        action = parts[0] if parts else ''
        rest = parts[1].strip() if len(parts) > 1 else ''

        if not action or action == 'list':
            scope = (rest or 'pending').lower()
            if scope not in ('pending', 'answered', 'all'):
                print('Usage: /asks list [all|pending|answered]')
                return
            asks = store.list(None if scope == 'all' else scope)
            if not asks:
                print(f'  No {scope} asks')
                return
            for a in asks:
                mark = '' if a.status == 'pending' else f'  ({a.status})'
                preview = a.question.replace('\n', ' ')[:70]
                print(f'  #{a.id}  {preview}{mark}')
            return
        if action == 'show':
            if not rest:
                print('Usage: /asks show <id>')
                return
            try:
                a = store.find(int(rest))
            except ValueError:
                print('Usage: /asks show <id>')
                return
            if a is None:
                print(f'Ask not found: {rest}')
                return
            print(f'#{a.id}  [{a.kind}{(": " + a.permission) if a.permission else ""}]'
                  f'  {a.status}')
            print(f'  origin:    {a.origin}')
            print(f'  question:  {a.question}')
            if a.context:
                print(f'  context:   {a.context}')
            if a.options:
                print('  options:   ' + ' / '.join(a.options))
            if a.answer:
                print(f'  answer:    {a.answer}')
            return
        if action == 'answer':
            aid, _, text = rest.partition(' ')
            if not aid or not text.strip():
                print('Usage: /asks answer <id> <text>')
                return
            try:
                target = store.find(int(aid))
            except ValueError:
                print('Usage: /asks answer <id> <text>')
                return
            if target is None:
                print(f'Ask not found: {aid}')
                return
            answered = store.answer(int(aid), text.strip())
            if answered is None:
                print(f'Ask not found: {aid}')
                return
            from ..asks import inject_answer
            injected = inject_answer(store, answered)
            if injected and chat.current_session.session_name == answered.origin:
                chat.load_or_create_session(answered.origin)
            note = f' -> resumed in session {answered.origin}' if injected \
                else ' (origin session missing)'
            print(f'Answered ask #{answered.id}{note}')
            return
        _render_commands(registry, ['asks'])

    @registry.register('compact', aliases=['c'],
                       description='Summarize the conversation and trim the context')
    def compact_cmd(_=None):
        chat.compact_session()

    @registry.register('memorize', description='Summarize the run into role, team, or job memory', subcommands=[
        ('', 'Memorize the active run into the active role memory'),
        ('<role|team|job> [name]', 'Memorize into a named scope'),
    ])
    def memorize_cmd(arg=''):
        parts = arg.strip().split(maxsplit=1)
        scope = parts[0] if parts else 'role'
        name = parts[1].strip() if len(parts) > 1 else ''
        print(chat.memorize(scope, name))

    @registry.register('tool', description='Run a tool directly (no args lists tools)')
    def tool_cmd(arg=''):
        chat._init_tooling()
        if not chat._tool_registry or not chat._tool_policy:
            print('Tool calling is disabled (tool_calling: false)')
            return
        parts = arg.strip().split(maxsplit=1)
        if not arg:
            rows = _tool_rows(chat)
            if rows is None:
                print('Tool calling is disabled (tool_calling: false)')
                return
            if not rows:
                print('No tools allowed')
                return
            print('Available tools:')
            name_w = max(len(n) for n, _ in rows)
            for n, tdesc in rows:
                print(f'  {n:<{name_w + 2}}{tdesc}')
            print('Use /help <tool> for details')
            return
        name = parts[0]
        args_str = parts[1] if len(parts) > 1 else '{}'
        try:
            arguments = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            print('Usage: /tool <name> {"key": "value"}')
            return
        if chat._tool_registry.loop_for(name):
            chat.chat_tool(name, arguments)
            return
        print(chat._run_tool(name, arguments, echo=False))

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

    @registry.register('jobs', description='Manage scheduled and durable jobs', subcommands=[
        ('list', 'List configured jobs'),
        ('status', 'Runtime summary per job (fired count, last error, uptime)'),
        ('show', 'Show a job and its run history'),
        ('add', 'Add a job (starts proposed, approve to activate)'),
        ('approve', 'Approve a job so it runs on schedule'),
        ('reject', 'Reject a proposed job'),
        ('enable', 'Enable a disabled job'),
        ('disable', 'Disable a job'),
        ('stop', 'Stop a job - same as disable'),
        ('edit', 'Open the job task file in $EDITOR (creates the template first)'),
        ('remove', 'Remove a job definition'),
        ('run', 'Run a job now'),
    ])
    def jobs_cmd(arg=''):
        from ..jobs import (Job, JobRegistry, parked_asks_for_run, publish,
                            read_memory, render_list, render_show,
                            render_status, validate_schedule)
        import shlex
        registry = JobRegistry(chat.config.local_path.parent / 'jobs.json')
        tokens = shlex.split(arg)
        action = tokens[0] if tokens else 'list'
        if action in ('list', 'status'):
            (render_status if action == 'status' else render_list)(registry)
            return
        if action == 'show':
            name = tokens[1] if len(tokens) > 1 else ''
            if not name:
                print('Usage: /jobs show <name>')
                return
            render_show(registry, name)
            return
        if action == 'remove':
            name = tokens[1] if len(tokens) > 1 else ''
            if not name:
                print('Usage: /jobs remove <name>')
                return
            if registry.remove(name):
                print(f'Removed job: {name}')
            else:
                print(f'Job not found: {name}')
            return
        if action in ('approve', 'reject', 'enable', 'disable', 'stop'):
            name = tokens[1] if len(tokens) > 1 else ''
            job = registry.find(name) if name else None
            if job is None:
                print(f'Usage: /jobs {action} <name>')
                return
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
            print(f'Job {name}: status={job.status}, '
                  f'{"enabled" if job.enabled else "disabled"}')
            return
        if action == 'run':
            from ..scheduler import JobScheduler
            name = tokens[1] if len(tokens) > 1 else ''
            job = registry.find(name) if name else None
            if job is None:
                print('Usage: /jobs run <name>')
                return
            run = JobScheduler(chat.config, verbose=False).run_job(job)
            print(f'Run {job.name}: {run.status} ({run.duration}s)')
            if run.content:
                print(run.content)
            if run.reason:
                print(f'  reason: {run.reason}')
            if run.session:
                print(f'  session: {run.session}')
            memory = read_memory(chat.config.local_path.parent.parent, job)
            if memory:
                print(f'  summary: {" ".join(memory.split())[:200]}')
            parked = parked_asks_for_run(chat.config.local_path.parent,
                                         run.session)
            if parked:
                print('  parked asks: '
                      + ', '.join(f'#{a["id"]}' for a in parked))
            return
        if action == 'add-supervisor':
            if len(tokens) < 2:
                print('Usage: /jobs add-supervisor <name> '
                      '[--at ISO | --interval N | --cron "expr"] '
                      '[--task "text" | --file path]')
                return
            opts = {}
            i = 2
            while i < len(tokens):
                tok = tokens[i]
                if tok in ('--at', '--interval', '--cron', '--task', '--file'):
                    opts[tok] = tokens[i + 1] if i + 1 < len(tokens) else ''
                    i += 2
                else:
                    i += 1
            schedule = {}
            if opts.get('--cron'):
                schedule['cron'] = opts['--cron']
            elif opts.get('--interval'):
                schedule['interval'] = int(opts['--interval'])
            elif opts.get('--at'):
                schedule['at'] = opts['--at']
            else:
                schedule['interval'] = 86400
            from ..jobs import add_supervisor_job, describe_schedule
            try:
                job = add_supervisor_job(
                    registry, tokens[1], chat.config.local_path.parent.parent,
                    schedule, task=opts.get('--task', ''),
                    task_file=opts.get('--file', ''))
            except ValueError as e:
                print(f'Error: {e}')
                return
            print(f'Added supervisor job: {job.name} [{job.status}]')
            print(f'  schedule:  {describe_schedule(job)}')
            print(f'  run now:   /jobs run {job.name}')
            return
        if action == 'add':
            if len(tokens) < 2:
                print('Usage: /jobs add <name> --cron "0 2 * * *" '
                      '[--prompt "text"|--file path] '
                      '[--interval N|--at ISO] [--approval auto]')
                return
            name = tokens[1]
            opts, after = {}, []
            i = 2
            while i < len(tokens):
                tok = tokens[i]
                if tok in ('--cron', '--interval', '--at', '--prompt', '--file',
                           '--session', '--mode', '--provider', '--model', '--role'):
                    opts[tok] = tokens[i + 1] if i + 1 < len(tokens) else ''
                    i += 2
                elif tok == '--approval':
                    opts[tok] = tokens[i + 1].lower() if i + 1 < len(tokens) else 'manual'
                    i += 2
                else:
                    after.append(tok)
                    i += 1
            prompt = opts.get('--prompt', '') or ''
            file_arg = opts.get('--file', '') or ''
            if not prompt and not file_arg:
                print('Usage: /jobs add <name> --prompt "text" --file path '
                      '(one of them required)')
                return
            schedule: dict = {}
            if opts.get('--cron'):
                schedule['cron'] = opts['--cron']
            elif opts.get('--interval'):
                try:
                    schedule['interval'] = int(opts['--interval'])
                except ValueError:
                    print('Invalid --interval value')
                    return
            elif opts.get('--at'):
                schedule['at'] = opts['--at']
            else:
                print('One of --cron, --interval, or --at is required')
                return
            try:
                validate_schedule(schedule)
            except ValueError as e:
                print(f'Error: {e}')
                return
            existing = registry.find(name)
            if existing is not None:
                print(f'Job already exists: {name}')
                return
            from ..cli import _store_task_file
            from ..jobs import ensure_task_file
            worktree = chat.config.local_path.parent.parent
            task_file = _store_task_file(worktree, file_arg)
            auto = opts.get('--approval') == 'auto'
            job = Job(
                name=name,
                schedule=schedule,
                prompt=prompt,
                session=opts.get('--session', '') or '',
                mode=opts.get('--mode', '') or '',
                provider=opts.get('--provider', '') or '',
                model=opts.get('--model', '') or '',
                role=opts.get('--role', '') or '',
                task_file=task_file,
                enabled=auto,
                status='approved' if auto else 'proposed',
            )
            if job.task_file:
                ensure_task_file(worktree, job)
            publish(registry, job)
            return
        if action == 'edit':
            name = tokens[1] if len(tokens) > 1 else ''
            job = registry.find(name) if name else None
            if job is None:
                print('Usage: /jobs edit <name>')
                return
            from ..jobs import ensure_task_file
            path = ensure_task_file(chat.config.local_path.parent.parent, job)
            editor = os.environ.get('EDITOR') or os.environ.get('VISUAL') or 'vi'
            import shlex
            import subprocess
            subprocess.call(shlex.split(editor) + [str(path)])
            return
        print('Usage: /jobs [list|status|show <name>|add <name> ...|approve <name>|'
              'reject <name>|enable <name>|disable <name>|stop <name>|'
              'edit <name>|remove <name>|run <name>]')


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
