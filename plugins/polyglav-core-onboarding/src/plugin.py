import getpass
import re
import sys
from urllib.parse import urlparse

WELCOME = ("Welcome to Polyglav. Let's set up this project together.\n"
           "I will ask about your provider, model, and how you want the "
           "assistant to work.\nPress Enter to accept a default.")
PROMPT_PURPOSE = 'What is this project for? '
PROMPT_PERSONA = 'How should the assistant introduce itself and work? '
PROMPT_OUTPUT = 'Create a file with everything printed to the terminal? [y/N] '
PROMPT_PROVIDER = 'Provider [{default}]: '
PROMPT_BASE_URL = 'Base URL [{default}]: '
PROMPT_KEY = 'API key [{default}]: '
PROMPT_KEY_EMPTY = 'API key (leave empty to skip): '
PROMPT_MODEL = 'Model [{default}]: '
PROMPT_MODE = 'Mode [read/write] ({default}): '
PROMPT_SAVE_ANYWAY = 'Save this provider anyway? [Y/n] '

DEFAULT_PERSONA = ("You are the assistant for this project and the "
                   "user's single point of contact.")
OPERATING = ('Delegate work bigger than one step: create the roles, teams, and '
             'skills you need with the catalog tool, call the next role or team, '
             'and report back. Before composing a team, confirm the design with the '
             'user: the deliverable, whether the manager is a sequential stage '
             'or a hierarchical orchestrator that calls roles, and the per-role '
             'permissions. Keep answers short.')

HINT = ('You can change provider, model, and mode later with /connect, /model, '
        'and /modes. For temperature, max tokens, and tool permissions, use '
        '/config --verbose.')


def compose_prompt(purpose: str, persona: str) -> str:
    purpose = (purpose or '').strip()
    persona = (persona or '').strip()
    parts = [persona or DEFAULT_PERSONA]
    if purpose:
        parts.append(f'Project purpose: {purpose}')
    parts.append(OPERATING)
    return '\n\n'.join(parts)


def should_run(chat) -> bool:
    config = getattr(chat, 'config', None)
    if config is None:
        return False
    try:
        if config.local_path.exists():
            return False
    except OSError:
        return False
    if chat._is_unattended():
        return False
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _ask(ask, prompt: str, default: str = '') -> str:
    try:
        answer = ask(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if answer is None:
        return default
    return str(answer).strip() or default


def _secret(secret, prompt: str, default: str = '') -> str:
    try:
        answer = secret(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if answer is None:
        return default
    return str(answer).strip() or default


def _info(chat, message: str) -> None:
    ui = getattr(chat, '_ui', None)
    if ui is not None and hasattr(ui, 'info'):
        ui.info(message)
    else:
        print(message)


def _normalize_url(url: str) -> str:
    if '://' not in url:
        url = 'https://' + url
    return url


def _derive_name(url: str) -> str:
    host = [label for label in (urlparse(url).hostname or '').lower().split('.')
            if label]
    if host[:1] == ['www']:
        host = host[1:]
    name = '-'.join(host[-2:]) if len(host) > 1 else (host[0] if host else '')
    name = re.sub(r'[^a-z0-9-]', '-', name)
    return name or 'custom'


def _provider_names(chat):
    merged = chat._merged_providers()
    names = [n for n in sorted(merged) if n != 'openai-compatible']
    if 'ollama' in names:
        names.remove('ollama')
        names.insert(0, 'ollama')
    names.append('openai-compatible')
    extras = sorted({entry.provider for entry in chat.providers.all()}
                    - set(names))
    return names + extras, merged


def _pick_provider(chat, ask, names):
    current = chat.config.get('provider') or names[0]
    print('  Providers:')
    for i, name in enumerate(names, 1):
        key = ' (key)' if chat.providers.api_key_for(name) else ''
        print(f'    {i}. {name}{key}')
    choice = _ask(ask, PROMPT_PROVIDER.format(default=current), current)
    if choice.isdigit():
        index = int(choice) - 1
        if 0 <= index < len(names):
            return names[index], ''
        _info(chat, f'Unknown provider number "{choice}"')
        return current, ''
    if choice in names:
        return choice, ''
    if '.' in choice or '://' in choice:
        return '', choice
    _info(chat, f'Unknown provider "{choice}"')
    return current, ''


def _provider_setup(chat, ask, secret):
    names, merged = _provider_names(chat)
    provider, url = _pick_provider(chat, ask, names)
    if url:
        from polyglav.providers import detect_provider
        url = _normalize_url(url)
        detected = detect_provider(url, merged)
        provider = detected if detected != 'openai-compatible' else _derive_name(url)
        base_url = url
    else:
        factory = merged.get(provider)
        base_url = '' if provider == 'openai-compatible' else (
            chat.providers.base_url_for(provider) or (
                getattr(factory, 'DEFAULT_BASE_URL', '') if factory else ''))
        if not base_url:
            default_url = '' if provider == 'openai-compatible' else (
                chat.config.get('base_url') or '')
            prompt = (PROMPT_BASE_URL.format(default=default_url)
                      if default_url else 'Base URL: ')
            base_url = _ask(ask, prompt, default_url)
        if not base_url:
            _info(chat, 'No base URL set; provider not saved.')
            return None

    stored = chat.providers.api_key_for(provider)
    prompt = (PROMPT_KEY.format(default='stored') if stored
              else PROMPT_KEY_EMPTY)
    api_key = _secret(secret, prompt, stored)

    models = []
    if chat.config.get('connect_check', True):
        ok, message, models = chat.check_connection(
            base_url=base_url, api_key=api_key, provider=provider)
        if not ok:
            _info(chat, f'! Connection test failed: {message}')
            if _ask(ask, PROMPT_SAVE_ANYWAY, 'y').lower() in ('n', 'no'):
                _info(chat, 'Provider not saved.')
                return None

    chat.providers.put(provider, base_url, api_key)
    chat.config.set('provider', provider, scope='local')
    chat.config.set('base_url', base_url, scope='local')
    _info(chat, f'Connected to {provider} ({base_url}).')
    return provider, base_url, api_key, models


def _pick_model(chat, provider, base_url, api_key, models, ask):
    current = chat.config.get('model') or ''
    if current.startswith(provider + '/'):
        current = current.split('/', 1)[1]
    elif '/' in current:
        current = ''
    if models:
        print('  Models:')
        for i, model in enumerate(models[:20], 1):
            print(f'    {i}. {model}')
        default = current if current in models else models[0]
        prompt = PROMPT_MODEL.format(default=default)
        choice = _ask(ask, prompt, default)
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < min(len(models), 20):
                return models[index]
            _info(chat, f'Unknown model number "{choice}"')
            return default
        return choice
    prompt = PROMPT_MODEL.format(default=current) if current else 'Model: '
    return _ask(ask, prompt, current)


def run(chat, force: bool = False, ask=input, secret=getpass.getpass) -> bool:
    if not force and not should_run(chat):
        return False
    if chat._is_unattended():
        return False
    _info(chat, WELCOME)

    setup = _provider_setup(chat, ask, secret)
    provider = ''
    base_url = ''
    api_key = ''
    models = []
    if setup is not None:
        provider, base_url, api_key, models = setup
        model = _pick_model(chat, provider, base_url, api_key, models, ask)
        if model:
            chat.models.put(provider, model)
            chat.config.set('model', model, scope='local')
        else:
            _info(chat, 'No model selected; set one later with /model.')

    current_mode = chat.config.get('mode') or 'read'
    mode = _ask(ask, PROMPT_MODE.format(default=current_mode), current_mode)
    if mode not in ('read', 'write'):
        _info(chat, f'Unknown mode "{mode}", keeping {current_mode}.')
        mode = current_mode
    chat.config.set('mode', mode, scope='local')

    purpose = _ask(ask, PROMPT_PURPOSE)
    persona = _ask(ask, PROMPT_PERSONA)
    output = _ask(ask, PROMPT_OUTPUT, 'n')

    config = chat.config
    config.set('system_prompt', compose_prompt(purpose, persona), scope='local')
    config.set('output_log',
               str(output).strip().lower().startswith('y'), scope='local')
    if provider:
        chat._reinit_provider()
    _info(chat, f'Saved project setup to {config.local_path}')
    _info(chat, HINT)
    return True


def register_startup(hooks: list) -> None:
    hooks.append(run)


def register_commands(registry) -> None:
    def onboard_cmd(arg: str = ''):
        run(registry.chat_loop, force=True)

    registry.register(
        'onboard', handler=onboard_cmd,
        description='Set up this project (provider, model, mode, assistant, output log)')
