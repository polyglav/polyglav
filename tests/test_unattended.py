import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from polyglav.config import Config, DEFAULT_CONFIG
from polyglav.engine import Engine
from polyglav.ui import ReplUI

from tests.helpers import make_chat
from tests.test_engine import make_engine


def _real_engine(config_data: dict) -> Engine:
    temp_dir = tempfile.TemporaryDirectory()
    Config.GLOBAL_DIR = Path(temp_dir.name) / 'global-home'
    data = {
        'provider': 'ollama',
        'model': 'test-model',
        'base_url': 'https://test.api.com',
        'api_key': '',
        'temperature': 0.7,
        'max_tokens': 2048,
    }
    data.update(config_data)
    config_dir = Path(temp_dir.name) / '.polyglav'
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / 'config.json').write_text(json.dumps(data))
    config = Config(path=temp_dir.name)
    engine = Engine(config, ui=ReplUI(None), provider=MagicMock(),
                    plugin_manager=MagicMock())
    engine._tmp = temp_dir
    return engine


class TestUnattendedConfig(unittest.TestCase):

    def test_defaults(self):
        self.assertFalse(DEFAULT_CONFIG['unattended'])
        self.assertEqual(DEFAULT_CONFIG['confirm_timeout'], 0)


class TestUnattendedAskUi(unittest.TestCase):

    def tearDown(self):
        if hasattr(self, '_engine'):
            self._engine._tmp.cleanup()

    def test_chatloop_unattended_drops_ask_ui(self):
        chat = make_chat({'unattended': True})
        try:
            self.assertIsNone(chat._ask_ui)
        finally:
            chat._tmp.cleanup()

    def test_chatloop_attended_keeps_ask_ui(self):
        chat = make_chat()
        try:
            self.assertIs(chat._ask_ui, chat._ui)
        finally:
            chat._tmp.cleanup()

    def test_engine_init_unattended_drops_ask_ui(self):
        engine = _real_engine({'unattended': True})
        self._engine = engine
        self.assertTrue(engine._is_unattended())
        self.assertIsNone(engine._ask_ui)

    def test_engine_init_attended_keeps_ask_ui(self):
        engine = _real_engine({})
        self._engine = engine
        self.assertFalse(engine._is_unattended())
        self.assertIsInstance(engine._ask_ui, ReplUI)

    def test_set_unattended_toggle_restores_ask_ui(self):
        chat = make_chat()
        try:
            chat.set_unattended(True)
            self.assertIsNone(chat._ask_ui)
            self.assertTrue(chat._is_unattended())
            chat.set_unattended(False)
            self.assertIs(chat._ask_ui, chat._ui)
            self.assertFalse(chat._is_unattended())
        finally:
            chat._tmp.cleanup()

    def test_subagent_inherits_unattended_and_no_ask_ui(self):
        from polyglav.roles import Role
        chat = make_chat({'unattended': True})
        try:
            chat.roles.put(Role(name='w', system_prompt='Writer'),
                           scope='local')
            sub = chat._new_sub_engine('w')
            self.assertTrue(sub.config.get('unattended'))
            self.assertTrue(sub._is_unattended())
            self.assertIsNone(sub._ask_ui)
        finally:
            chat._tmp.cleanup()


class TestUnattendedNonBlocking(unittest.TestCase):

    def tearDown(self):
        if hasattr(self, '_engine'):
            self._engine._tmp.cleanup()

    def _no_input(self, *args):
        raise AssertionError('stdin must not be touched in unattended mode')

    def test_confirm_auto_denied_when_unattended(self):
        engine = make_engine({'unattended': True})
        self._engine = engine
        engine._ui = MagicMock()
        self.assertFalse(engine._confirm_tool('run_command', {'command': 'ls'}))
        engine.ui.confirm.assert_not_called()

    def test_root_human_ask_parks_when_unattended(self):
        chat = make_chat({'unattended': True})
        try:
            chat._init_tooling()
            with patch('builtins.input', side_effect=self._no_input):
                out = chat._run_tool('ask', {'question': 'which port?'})
            self.assertIn('[parked]', out)
            self.assertEqual(len(chat.asks.list()), 1)
        finally:
            chat._tmp.cleanup()

    def test_subagent_human_ask_parks_when_unattended(self):
        from polyglav.roles import Role
        chat = make_chat({'unattended': True})
        try:
            chat.roles.put(Role(name='w', system_prompt='Writer'),
                           scope='local')
            sub = chat._new_sub_engine('w')
            sub._init_tooling()
            with patch('builtins.input', side_effect=self._no_input):
                out = sub._run_tool('ask', {'question': 'which port?'})
            self.assertIn('[parked]', out)
            chat.provider.chat_nonstreaming.assert_not_called()
        finally:
            chat._tmp.cleanup()

    def test_run_command_confirm_auto_deny_in_loop(self):
        chat = make_chat({'unattended': True})
        try:
            tool_call = [{
                'id': 'call_run001',
                'type': 'function',
                'function': {'name': 'run_command',
                             'arguments': json.dumps({'command': 'echo hi'})},
            }]
            chat.provider.chat.side_effect = [
                [{'type': 'tool_calls', 'tool_calls': tool_call}],
                [{'type': 'token', 'content': 'Continuing.'},
                 {'type': 'done', 'reason': 'stop'}],
            ]
            with patch('builtins.input', side_effect=self._no_input):
                with patch('sys.stdout', new=io.StringIO()):
                    chat._agent_loop()
            tools = [p for t in chat.current_session.turns
                     for p in t.get('parts') or [] if p['type'] == 'tool']
            self.assertTrue(tools)
            self.assertIn('[cancelled] User declined the run_command call',
                          tools[0]['output'])
            self.assertEqual(chat.provider.chat.call_count, 2)
        finally:
            chat._tmp.cleanup()

    def test_model_approval_not_prompted_when_unattended(self):
        engine = make_engine({'unattended': True})
        self._engine = engine
        engine._ui = MagicMock()
        self.assertFalse(engine._ensure_model_approved('ollama', 'nope-model'))
        engine.ui.confirm.assert_not_called()

    def test_model_approval_unattended_honors_approve_models(self):
        engine = make_engine({'unattended': True})
        self._engine = engine
        engine.approve_models = True
        self.assertTrue(engine._ensure_model_approved('ollama', 'nope-model'))


class TestUnattendedCommand(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def test_command_shows_status(self):
        out = self._dispatch('/unattended')
        self.assertIn('Unattended mode: off', out)

    def test_command_toggle_on_drops_ask_ui(self):
        out = self._dispatch('/unattended on')
        self.assertIn('Unattended mode: on', out)
        self.assertTrue(self.chat.config.get('unattended'))
        self.assertIsNone(self.chat._ask_ui)

    def test_command_toggle_off_restores_ask_ui(self):
        self._dispatch('/unattended on')
        self._dispatch('/unattended off')
        self.assertFalse(self.chat.config.get('unattended'))
        self.assertIs(self.chat._ask_ui, self.chat._ui)


class TestConfirmTimeout(unittest.TestCase):

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _ui(self, timeout):
        self.chat = make_chat({'confirm_timeout': timeout})
        return self.chat._ui

    def test_confirm_denies_on_timeout(self):
        ui = self._ui(2)
        with patch('polyglav.ui.select.select', return_value=([], [], [])):
            with patch('builtins.input', side_effect=AssertionError(
                    'input must not be called on timeout')):
                with patch('sys.stdout', new=io.StringIO()) as buf:
                    self.assertFalse(ui.confirm('run_command', 'run_command ls'))
        self.assertIn('no answer in 2s, denied', buf.getvalue())

    def test_confirm_returns_answer_when_ready(self):
        ui = self._ui(2)
        with patch('polyglav.ui.select.select',
                   return_value=([sys.stdin], [], [])):
            with patch('builtins.input', return_value='y'):
                self.assertTrue(ui.confirm('run_command', 'run_command ls'))

    def test_confirm_zero_timeout_blocks(self):
        ui = self._ui(0)
        with patch('builtins.input', return_value='n'):
            self.assertFalse(ui.confirm('run_command', 'run_command ls'))

    def test_ask_returns_none_on_timeout(self):
        ui = self._ui(2)
        with patch('polyglav.ui.select.select', return_value=([], [], [])):
            with patch('sys.stdout', new=io.StringIO()):
                self.assertIsNone(ui.ask('which?',
                                         origin=self.chat.current_session.session_name))

    def test_ask_returns_answer_when_ready(self):
        ui = self._ui(2)
        with patch('polyglav.ui.select.select',
                   return_value=([sys.stdin], [], [])):
            with patch('builtins.input', return_value='use 8080'):
                self.assertEqual(
                    ui.ask('which?', origin=self.chat.current_session.session_name),
                    'use 8080')


if __name__ == '__main__':
    unittest.main()