import tempfile
import json
from pathlib import Path
from unittest.mock import MagicMock

from polyglav.config import Config
from polyglav.chat import ChatLoop
from polyglav.sessions.manager import SessionManager
from polyglav.runs import RunRegistry
from polyglav.commands.registry import CommandRegistry
from polyglav.commands.builtins import register_builtins
from polyglav.plugins.manager import PluginManager
from polyglav.ui import ReplUI


def seed_roles(chat: ChatLoop, *names: str) -> None:
    from polyglav.role_model import Role
    for name in names:
        chat.roles.put(Role(name=name, system_prompt=f'You are the {name}.'))


def make_chat(config_data: dict | None = None) -> ChatLoop:
    temp_dir = tempfile.TemporaryDirectory()
    Config.GLOBAL_DIR = Path(temp_dir.name) / 'global-home'
    data = {
        'tool_calling': True,
        'provider': 'ollama',
        'model': 'test-model',
        'base_url': 'https://test.api.com',
        'api_key': '',
        'temperature': 0.7,
        'max_tokens': 2048,
        'stream_retry_delay': 0,
    }
    if config_data:
        data.update(config_data)

    config_dir = Path(temp_dir.name) / '.polyglav'
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_dir / 'config.json', 'w') as f:
        json.dump(data, f)

    config = Config(path=temp_dir.name)

    chat = ChatLoop.__new__(ChatLoop)
    chat.config = config
    chat.provider = MagicMock()
    sessions_dir = config.local_path.parent / 'sessions'
    chat.sessions = SessionManager(sessions_dir)
    chat.current_session = chat.sessions.create()
    chat._tool_registry = None
    chat._ui = ReplUI(chat)
    chat._ask_ui = chat._ui
    chat._caller = None
    chat.role = ''
    chat.runs = RunRegistry()
    chat.current_run = chat.runs.start(
        role='', session=chat.current_session.session_name,
        session_id=chat.current_session.session_id)

    chat._plugin_manager = PluginManager(config)
    chat._plugin_manager.load()
    chat._perform_search = MagicMock(return_value='Mocked search context.')
    chat._show_tool_status = MagicMock()
    chat.session_auto_save = MagicMock()
    chat._tmp = temp_dir

    chat.registry = CommandRegistry(chat)
    register_builtins(chat.registry)
    chat._plugin_manager.register_commands(chat.registry)
    return chat


def role_registry_class():
    import importlib.util
    path = (Path(__file__).resolve().parents[1] / 'plugins'
            / 'polyglav-core-roles' / 'src' / 'registry.py')
    spec = importlib.util.spec_from_file_location(
        'polyglav_core_roles_registry_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RoleRegistry


def team_module():
    import importlib.util
    path = (Path(__file__).resolve().parents[1] / 'plugins'
            / 'polyglav-core-teams' / 'src' / 'teams.py')
    spec = importlib.util.spec_from_file_location(
        'polyglav_core_teams_models_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def team_runner_module():
    import importlib.util
    import sys
    src = (Path(__file__).resolve().parents[1] / 'plugins'
           / 'polyglav-core-teams' / 'src')
    added = False
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
        added = True
    try:
        import teams as models
        path = src / 'runner.py'
        spec = importlib.util.spec_from_file_location(
            'polyglav_core_teams_runner_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if added:
            sys.path.remove(str(src))


def skills_module():
    import importlib.util
    path = (Path(__file__).resolve().parents[1] / 'plugins'
            / 'polyglav-core-skills' / 'src' / 'skills.py')
    spec = importlib.util.spec_from_file_location(
        'polyglav_core_skills_models_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
