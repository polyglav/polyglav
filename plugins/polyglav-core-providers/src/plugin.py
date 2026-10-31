from polyglav.providers import PROVIDERS, detect_provider
from polyglav.providers.base import OpenAICompatibleProvider
from polyglav.ui import DIM, RED, RESET


def _render_models(models, provider, base_url):
    print(f'{len(models)} models available from {provider} ({base_url}):')
    for m in models:
        print(f'  - {m}')


def _active_model(chat, entry):
    return (entry.provider == chat.config.get('provider')
            and entry.model == chat.config.get('model'))


def _remove_model(chat, ref):
    if '/' not in ref:
        print('Usage: /models remove <provider>/<model>')
        return
    provider, _, model = ref.partition('/')
    provider = provider.strip()
    model = model.strip()
    if not provider or not model:
        print('Usage: /models remove <provider>/<model>')
        return
    entry = chat.models.find(provider, model)
    if entry is None:
        print(f'Model not in the registry: {provider}/{model}')
        return
    if _active_model(chat, entry):
        try:
            answer = input(
                f'  Remove the active model "{provider}/{model}"? [y/N] '
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if answer not in ('y', 'yes'):
            print('Kept')
            return
    chat.models.remove(provider, model)
    print(f'Removed model: {provider}/{model}')


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
            if e.last_error:
                status = '  (failed)'
            elif not e.ok_at:
                status = '  (unused)'
            else:
                status = ''
            print(f'  {active} {e.model}{key}{status}')


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
        print(f'{RED}✗ Failed to list models: {error}{RESET}')
        print(f'  probing {provider} ({base_url}) - run /connect to fix')
        return
    if not models:
        print(f'No models listed from {provider} ({base_url})')
        return
    _cache_models(chat, provider, models)
    _render_models(models, provider, base_url)
    model = chat.config.get('model')
    if model and model not in models:
        print(f'  (configured model "{model}" not in the model list)')


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


def _provider_names(chat, providers):
    names = set(providers) | {e.provider for e in chat.providers.all()}
    return sorted(names)


def _render_provider_status(chat, providers):
    names = _provider_names(chat, providers)
    if not names:
        print('  (no providers)')
        return
    active = chat.config.get('provider')
    print(f'{len(names)} providers:')
    for name in names:
        mark = '>' if name == active else ' '
        key = ' (key)' if chat.providers.api_key_for(name) else ''
        factory = providers.get(name)
        base = chat.providers.base_url_for(name) or (
            getattr(factory, 'DEFAULT_BASE_URL', '') if factory else '')
        tag = '' if factory else ' (custom)'
        base_col = f'  {base}' if base else ''
        print(f'  {mark} {name}{tag}{key}{base_col}')


def _cache_models(chat, provider, models):
    if not models:
        return
    cache = getattr(chat, '_model_cache', None)
    if cache is None:
        cache = {}
        chat._model_cache = cache
    cache[provider] = list(models)


def _connect_key_prompt(chat, provider):
    stored = chat.providers.api_key_for(provider)
    if stored:
        return input('  API key [<stored>]: ').strip() or stored
    return input('  API key (leave empty to skip): ').strip()


def _connect_save(chat, providers, provider, base_url, api_key):
    detected = detect_provider(base_url, providers)
    if (detected in providers and detected != 'openai-compatible'
            and detected != provider):
        print(f'  Detected provider "{detected}" from base URL - switching')
        provider = detected
    was_known = chat.providers.find(provider) is not None
    checkout = chat.config.get('connect_check', True)
    models: list[str] = []
    if checkout:
        ok, msg, _models = chat.check_connection(
            base_url=base_url, api_key=api_key, provider=provider)
        models = _models
        if not ok:
            print(f'  {RED}✗ Connection test failed: {msg}{RESET}')
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
    _cache_models(chat, provider, models)
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
        _connect_named(chat, providers, providers[provider], provider,
                       base_url=url)
    else:
        pname = name or _derive_provider_name(url)
        if not name:
            print(f'  New provider name: {pname}')
        api_key = _connect_key_prompt(chat, pname)
        _connect_save(chat, providers, pname, url, api_key)


def _connect_pick(chat, providers):
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


def _providers(chat):
    providers = dict(PROVIDERS)
    pm = getattr(chat, '_plugin_manager', None)
    if pm is not None:
        providers.update(pm.provider_classes())
    return providers


def register_commands(commands):
    chat = commands.chat_loop

    @commands.register(
        'connect',
        description='Connect a provider - /connect <name|url> [name]')
    def connect_cmd(arg=''):
        providers = _providers(chat)
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

    @commands.register('provider', description='Show or switch the active provider')
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

    @commands.register('providers', description='List provider connections')
    def providers_cmd(arg=''):
        _render_provider_status(chat, _providers(chat))

    @commands.register(
        'model',
        description=('Show or switch the active model; `/model <name>` sets it '
                     'on the current provider, `/model <provider>/<model>` '
                     'switches provider and model together'))
    def model_cmd(arg=''):
        arg = arg.strip()
        if not arg:
            provider = chat.config.get('provider')
            model = chat.config.get('model')
            print(f'{DIM}@ Model: {provider}/{model}{RESET}')
            return
        ref = chat.unfold_ref(arg)
        if ref is not None:
            provider, base_url, model = ref
            if chat._ensure_model_approved(provider, model):
                chat.config.set('model', f'{provider}/{model}')
                chat._reinit_provider()
                print(f'{DIM}@ Model: {provider}/{model}{RESET}')
            else:
                print(f'{RED}✗ Model not approved: {provider}/{model}{RESET}')
            return
        chat.config.set('model', arg)
        chat.provider.model = chat.config.get('model')
        chat.models.put(chat.config.get('provider'), arg)
        print(f'{DIM}@ Model: {chat.config.get("provider")}/{arg}{RESET}')

    @commands.register(
        'models',
        description=("List configured models, or probe a provider's available "
                     'models'),
        subcommands=[
            ('list', "Probe a provider's advertised models (list [provider], default current)"),
            ('remove', 'Remove a model from the registry (remove <provider>/<model>)'),
        ])
    def models_cmd(arg=''):
        arg = arg.strip()
        if not arg:
            _render_known_models(chat)
        elif arg == 'list':
            _render_online_models(chat, '')
        elif arg.startswith('list '):
            _render_online_models(chat, arg[len('list'):].strip())
        elif arg == 'remove' or arg.startswith('remove '):
            _remove_model(chat, arg[len('remove'):].strip())
        else:
            print('Usage: /models [list [provider]|remove <provider>/<model>]')


def _run_models(args):
    from polyglav.cli import cmd_models
    return cmd_models(args)


def register_cli(cli):
    import argparse
    p = cli.add_parser(
        'models',
        help="List configured models, or probe a provider's available models")
    p.add_argument('--path', default=argparse.SUPPRESS,
                   help='Project path (default: current directory)')
    g = p.add_subparsers(dest='action')
    gl = g.add_parser('list', help='Probe a provider advertised models (default: current provider)')
    gl.add_argument('provider', nargs='?', default='',
                    help='Provider name (default: current)')
    p.set_defaults(func=_run_models)
    _register_providers_cli(cli)


def _providers_cli(args):
    from polyglav.config import Config
    from polyglav.engine import Engine
    from polyglav.providers.registry import ProviderRegistry
    from polyglav.ui import NullUI
    config = Config(path=getattr(args, 'path', None))
    registry = ProviderRegistry()
    action = getattr(args, 'action', None)
    if action == 'list':
        entries = registry.all()
        if not entries:
            print('No provider connections configured')
            return 0
        active = config.get('provider')
        for entry in sorted(entries, key=lambda e: e.provider):
            mark = '>' if entry.provider == active else ' '
            key = ' (key)' if entry.api_key else ''
            base = f'  {entry.base_url}' if entry.base_url else ''
            print(f'  {mark} {entry.provider}{key}{base}')
        return 0
    if action == 'remove':
        ok = registry.remove(args.name)
        print(f'Removed provider: {args.name}' if ok else f'Provider not found: {args.name}')
        return 0 if ok else 1
    if action == 'probe':
        entry = registry.find(args.name)
        if entry is None:
            print(f'Provider not found: {args.name}')
            return 1
        engine = Engine(config, ui=NullUI())
        ok, msg, _ = engine.check_connection(
            base_url=entry.base_url, api_key=entry.api_key,
            provider=entry.provider)
        print(msg if ok else f'Failed: {msg}')
        return 0 if ok else 1
    if action == 'connect':
        base_url = getattr(args, 'base_url', '') or ''
        api_key = getattr(args, 'key', '') or ''
        if not base_url:
            entry = registry.find(args.name)
            base_url = entry.base_url if entry else ''
        if not base_url:
            print('Error: --base-url is required for a new provider')
            return 1
        if not api_key:
            entry = registry.find(args.name)
            api_key = entry.api_key if entry else ''
        registry.put(args.name, base_url, api_key)
        config.set('provider', args.name)
        config.set('base_url', base_url)
        print(f'Connected provider: {args.name} ({base_url})')
        return 0
    print('Usage: polyglav providers [list|connect|remove|probe]')
    return 1


def _register_providers_cli(cli):
    import argparse
    p = cli.add_parser('providers', help='Manage provider connections')
    p.add_argument('--path', default=argparse.SUPPRESS,
                   help='Project path (default: current directory)')
    g = p.add_subparsers(dest='action', required=True)
    g.add_parser('list', help='List provider connections')
    gp = g.add_parser('probe', help='Probe a provider connection')
    gp.add_argument('name')
    gr = g.add_parser('remove', help='Remove a provider connection')
    gr.add_argument('name')
    gc = g.add_parser('connect', help='Add or update a provider connection')
    gc.add_argument('name')
    gc.add_argument('--base-url', help='Provider base URL')
    gc.add_argument('--key', help='API key')
    p.set_defaults(func=_providers_cli)
