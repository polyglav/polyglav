import getpass
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

WELCOME = ("Welcome to Polyglav.\n"
           "This short setup connects a model provider and sets how the assistant "
           "works in this project.\n"
           "It can read code, search the web, edit files, and run teams of "
           "specialists when a task is bigger than one step.\n"
           "Press Enter to accept any default.")
PROMPT_PURPOSE = 'What is this project for? '
PROMPT_PERSONA = 'How should the assistant introduce itself and work? '
PROMPT_OUTPUT = 'Create a file with everything printed to the terminal? [y/N] '
PROMPT_REASONING = 'Reasoning (off/summary/assistant/agent/all) [summary]: '
PROMPT_OUTPUT_SCOPE = 'Sub-run output (off/assistant/agent/all) [agent]: '
PROMPT_TOOL_STATS = 'Show tool time and tokens? [y/N] '
PROMPT_STATUS = 'Show live time and approximate tokens? [Y/n] '
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

HINT = ('Change these later with /connect, /model, /modes, and /config --verbose.')


def _say(message: str = '') -> None:
    print(message, flush=True)



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


def _secret(chat, secret, prompt: str, default: str = '') -> str:
    ui = getattr(chat, '_ui', None)
    reader = getattr(ui, 'secret', None)
    try:
        answer = reader(prompt) if callable(reader) else secret(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if answer is None:
        return default
    return str(answer).strip() or default


def _confirm(chat, ask, prompt: str, default: str = 'y') -> bool:
    ui = getattr(chat, '_ui', None)
    reader = getattr(ui, 'confirm_text', None)
    try:
        if callable(reader):
            return bool(reader(prompt, default=default))
        return _ask(ask, prompt, default).lower() not in ('n', 'no')
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _warn(chat, message: str) -> None:
    ui = getattr(chat, '_ui', None)
def _confirm(chat, ask, prompt: str, default: str = 'y') -> bool:
    ui = getattr(chat, '_ui', None)
    reader = getattr(ui, 'confirm_text', None)
    try:
        if callable(reader):
            return bool(reader(prompt, default=default))
        return _ask(ask, prompt, default).lower() not in ('n', 'no')
    except (EOFError, KeyboardInterrupt):
        print()
        return False


    if ui is not None and hasattr(ui, 'warning'):
        ui.warning(message)
    else:
        print(message, flush=True)


def _providers_path(chat) -> str:
    path = getattr(getattr(chat, 'providers', None), 'path', None)
    return str(path) if path else '~/.config/polyglav/providers.json'


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


PRESETS = {'lmstudio': 'http://localhost:1234/v1'}


def _current_provider(chat) -> str:
    try:
        provider, _, _ = chat.model_target()
        return str(provider or '')
    except Exception:
        return ''


def _current_model(chat) -> str:
    try:
        _, _, model = chat.model_target()
        return str(model or '')
    except Exception:
        return str(chat.config.get('model') or '').split('/', 1)[-1]


def _provider_names(chat):
    merged = chat._merged_providers()
    names = [n for n in sorted(merged) if n != 'openai-compatible']
    if 'ollama' in names:
        names.remove('ollama')
        names.insert(0, 'ollama')
    for name in PRESETS:
        if name not in names:
            names.append(name)
    names.append('openai-compatible')
    names.append('custom')
    extras = sorted({entry.provider for entry in chat.providers.all()}
                    - set(names))
    return names + extras, merged


def _pick_provider(chat, ask, names):
    current = _current_provider(chat) or names[0]
    print()
    _say('Choose a provider')
    _say('This is where the model runs. A stored key is marked (key).')
    for i, name in enumerate(names, 1):
        key = ' (key)' if chat.providers.api_key_for(name) else ''
        _say(f'{i}. {name}{key}')
    choice = _ask(ask, PROMPT_PROVIDER.format(default=current), current)
    if choice.isdigit():
        index = int(choice) - 1
        if 0 <= index < len(names):
            return names[index], ''
        _warn(chat, f'Unknown provider number "{choice}"')
        return current, ''
    if choice in names:
        return choice, ''
    if '.' in choice or '://' in choice:
        return '', choice
    _warn(chat, f'Unknown provider "{choice}"')
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
        if provider == 'custom':
            base_url = _ask(ask, 'Custom base URL: ', '')
        else:
            factory = merged.get(provider)
            base_url = PRESETS.get(provider) or (
                '' if provider == 'openai-compatible' else (
                    chat.providers.base_url_for(provider) or (
                        getattr(factory, 'DEFAULT_BASE_URL', '') if factory else '')))
        if not base_url:
            default_url = '' if provider == 'openai-compatible' else (
                chat.config.get('base_url') or '')
            prompt = (PROMPT_BASE_URL.format(default=default_url)
                      if default_url else 'Base URL: ')
            base_url = _ask(ask, prompt, default_url)
        if not base_url:
            _warn(chat, 'No base URL set; provider not saved.')
            return None

    stored = chat.providers.api_key_for(provider)
    print()
    _say(f'Enter the {provider} API key.')
    _say(f'It is stored in {_providers_path(chat)}, never in this project.')
    if stored:
        _say('Leave it empty to reuse the saved key.')
    else:
        _say('Leave it empty to skip this provider for now.')
    prompt = (PROMPT_KEY.format(default='stored') if stored
              else PROMPT_KEY_EMPTY)
    api_key = _secret(chat, secret, prompt, stored)
    if not api_key and not stored:
        _say('No API key entered.')

    models = []
    ok, message, models = chat.check_connection(
        base_url=base_url, api_key=api_key, provider=provider)
    if not ok:
        _warn(chat, f'Connection test failed: {message}')
        if not _confirm(chat, ask, PROMPT_SAVE_ANYWAY, 'y'):
            _warn(chat, 'Provider not saved.')
            return None

    chat.providers.put(provider, base_url, api_key)
    chat.config.set('base_url', base_url, scope='local')
    _say(f'Connected to {provider} ({base_url}).')
    return provider, base_url, api_key, models


def _pick_model(chat, provider, base_url, api_key, models, ask):
    current = _current_model(chat)
    if current.startswith(provider + '/'):
        current = current.split('/', 1)[1]
    elif '/' in current:
        current = ''
    print()
    _say('Choose a model')
    if models:
        _say(f'These are the models {provider} reports. The first 20 are listed.')
        for i, model in enumerate(models[:20], 1):
            _say(f'{i}. {model}')
        default = current if current in models else models[0]
        prompt = PROMPT_MODEL.format(default=default)
        choice = _ask(ask, prompt, default)
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < min(len(models), 20):
                return models[index]
            _warn(chat, f'Unknown model number "{choice}"')
            return default
        return choice
    _say('No model list was returned. Enter a model name, or leave it empty '
         'to set one later with /model.')
    prompt = PROMPT_MODEL.format(default=current) if current else 'Model: '
    return _ask(ask, prompt, current)


def run(chat, force: bool = False, ask=input, secret=getpass.getpass) -> bool:
    if not force and not should_run(chat):
        return False
    _say(WELCOME)

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
            chat.config.set('model', f'{provider}/{model}', scope='local')
        else:
            _say('No model selected; set one later with /model.')

    print()
    _say('Choose a mode')
    _say('read is read-only. write allows file edits and commands.')
    current_mode = chat.config.get('mode') or 'read'
    mode = _ask(ask, PROMPT_MODE.format(default=current_mode), current_mode)
    if mode not in ('read', 'write'):
        _warn(chat, f'Unknown mode "{mode}", keeping {current_mode}.')
        mode = current_mode
    chat.config.set('mode', mode, scope='local')

    print()
    _say('Describe this project and the assistant (optional).')
    purpose = _ask(ask, PROMPT_PURPOSE)
    persona = _ask(ask, PROMPT_PERSONA)
    reasoning = _ask(ask, PROMPT_REASONING, 'summary').lower()
    if reasoning not in ('off', 'summary', 'assistant', 'agent', 'all'):
        _warn(chat, f'Unknown reasoning scope "{reasoning}", keeping summary.')
        reasoning = 'summary'
    output_scope = _ask(ask, PROMPT_OUTPUT_SCOPE, 'agent').lower()
    if output_scope not in ('off', 'assistant', 'agent', 'all'):
        _warn(chat, f'Unknown output scope "{output_scope}", keeping agent.')
        output_scope = 'agent'
    tool_stats = _ask(ask, PROMPT_TOOL_STATS, 'n').lower().startswith('y')
    live_status = _ask(ask, PROMPT_STATUS, 'y').lower().startswith('y')
    output = _ask(ask, PROMPT_OUTPUT, 'n')

    config = chat.config
    config.set('system_prompt', compose_prompt(purpose, persona), scope='local')
    config.set('output_log',
               str(output).strip().lower().startswith('y'), scope='local')
    config.set('verbosity.thinking', reasoning, scope='local')
    config.set('verbosity.output', output_scope, scope='local')
    config.set('verbosity.tools', 'full' if tool_stats else 'summary',
               scope='local')
    config.set('verbosity.status', 'on' if live_status else 'off',
               scope='local')
    if provider:
        chat._reinit_provider()
    print()
    _say(f'Saved project setup to {config.local_path}')
    _say(HINT)
    if not (config.local_path.parent.parent / 'AGENTS.md').exists():
        _say('No AGENTS.md found - run /init to create one.')
    return True


def register_startup(hooks: list) -> None:
    hooks.append(run)


def register_commands(registry) -> None:
    def onboard_cmd(arg: str = ''):
        run(registry.chat_loop, force=True)

    registry.register(
        'onboard', handler=onboard_cmd,
        description='Set up this project (provider, model, mode, assistant, output log)')

    def init_cmd(arg: str = ''):
        tokens = arg.split()
        ok, message = write_agents_md(
            registry.chat_loop.config,
            force='--force' in tokens,
            update='--update' in tokens)
        print(message)
        if not ok:
            print('  /init --force rewrites, /init --update refreshes the generated block')

    registry.register(
        'init', handler=init_cmd,
        description='Generate an AGENTS.md skeleton for this project')


_START = '<!-- polyglav:init:start -->'
_END = '<!-- polyglav:init:end -->'

_STACK_FILES = (
    ('pyproject.toml', 'Python'),
    ('setup.py', 'Python'),
    ('package.json', 'Node'),
    ('Cargo.toml', 'Rust'),
    ('go.mod', 'Go'),
    ('composer.json', 'PHP'),
    ('Gemfile', 'Ruby'),
)

_TEST_COMMANDS = {
    'Python': 'python -m unittest discover',
    'Node': 'npm test',
    'Rust': 'cargo test',
    'Go': 'go test ./...',
    'PHP': 'vendor/bin/phpunit',
    'Ruby': 'bundle exec rake test',
}


def project_scan(root: Path) -> dict:
    stack = []
    for filename, label in _STACK_FILES:
        if (root / filename).exists() and label not in stack:
            stack.append(label)
    dirs = sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and not p.name.startswith('.')
        and p.name not in ('node_modules', 'vendor', '__pycache__')
    ) if root.exists() else []
    return {'stack': stack, 'dirs': dirs}


def agents_md_template(config, root: Path | None = None) -> str:
    root = root or config.local_path.parent.parent
    scan = project_scan(root)
    stack = scan['stack'] or ['Unknown']
    commands = [_TEST_COMMANDS[s] for s in stack if s in _TEST_COMMANDS]
    dirs = scan['dirs']
    lines = [
        _START,
        '# AGENTS.md',
        '',
        '## Project',
        'Describe what this project is for and who uses it.',
        '',
        '## Stack',
    ]
    lines.extend(f'- {item}' for item in stack)
    lines.extend(['', '## Commands'])
    if commands:
        lines.extend(f'- Test: `{cmd}`' for cmd in commands)
    else:
        lines.append('- Test: TODO')
    lines.extend(['', '## Structure'])
    if dirs:
        lines.extend(f'- `{name}/`' for name in dirs[:20])
    else:
        lines.append('- TODO')
    lines.extend([
        '',
        '## Conventions',
        '- TODO',
        '',
        '## Extension points',
        '- TODO',
        _END,
        '',
    ])
    return '\n'.join(lines)


def write_agents_md(config, force: bool = False, update: bool = False) -> tuple[bool, str]:
    root = config.local_path.parent.parent
    path = root / 'AGENTS.md'
    content = agents_md_template(config, root)
    if path.exists() and not force:
        old = path.read_text(encoding='utf-8', errors='replace')
        if update and _START in old and _END in old:
            before, _, rest = old.partition(_START)
            _, _, after = rest.partition(_END)
            path.write_text(before + content + after, encoding='utf-8')
            return True, f'Updated {path}'
        return False, f'{path} already exists - use /init --force to rewrite'
    path.write_text(content, encoding='utf-8')
    return True, f'Wrote {path}'
