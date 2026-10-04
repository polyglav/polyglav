import sys

WELCOME = 'Welcome to Polyglav. A few questions to set up this project.'
PROMPT_PURPOSE = 'What is this project for? '
PROMPT_PERSONA = 'How should the assistant introduce itself and work? '
PROMPT_FOLLOW = 'Follow delegated runs automatically? [Y/n] '
PROMPT_LABEL = 'Show the active role in the prompt? [y/N] '

DEFAULT_PERSONA = ("You are the assistant for this project and the "
                   "operator's single point of contact.")
OPERATING = ('Delegate work bigger than one step: create the roles, teams, and '
             'skills you need with the catalog tool, hand the task off, and '
             'report back. Keep answers short.')


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
        answer = str(ask(prompt)).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return answer or default


def _info(chat, message: str) -> None:
    ui = getattr(chat, '_ui', None)
    if ui is not None and hasattr(ui, 'info'):
        ui.info(message)
    else:
        print(message)


def run(chat, force: bool = False, ask=input) -> bool:
    if not force and not should_run(chat):
        return False
    if chat._is_unattended():
        return False
    _info(chat, WELCOME)
    purpose = _ask(ask, PROMPT_PURPOSE)
    persona = _ask(ask, PROMPT_PERSONA)
    follow = _ask(ask, PROMPT_FOLLOW, 'y')
    label = _ask(ask, PROMPT_LABEL, 'n')
    config = chat.config
    config.set('system_prompt', compose_prompt(purpose, persona), scope='local')
    config.set('focus_on_delegate',
               'off' if str(follow).strip().lower().startswith('n') else 'on',
               scope='local')
    config.set('prompt_role',
               str(label).strip().lower().startswith('y'), scope='local')
    _info(chat, f'Saved project setup to {config.local_path}')
    return True


def register_startup(hooks: list) -> None:
    hooks.append(run)


def register_commands(registry) -> None:
    def onboard_cmd(arg: str = ''):
        run(registry.chat_loop, force=True)

    registry.register(
        'onboard', handler=onboard_cmd,
        description='Set up this project (purpose, assistant, focus)')
