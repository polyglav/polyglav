import io
import json
import unittest
from unittest.mock import MagicMock, patch

from polyglav.engine import TurnResult

from tests.helpers import make_chat, seed_roles


class TestFocusOnDelegate(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        seed_roles(self.chat, 'writer')
        self.chat.config.set('mode', 'write')
        self.chat._init_tooling()
        self.run = self.chat.runs.start(role='writer', session='sub_1')
        self.chat.run_subagent = MagicMock(return_value=TurnResult(
            content='done', session='sub_1', status='ok', run_id=self.run.id))

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _delegate(self, role_name='writer'):
        return self.chat._run_tool('call',
                                   {'role': role_name, 'task': 'draft it'})

    def test_default_is_on(self):
        self.assertEqual(self.chat.config.get('focus_on_delegate'), 'on')

    def test_off_leaves_focus_alone(self):
        self.chat.config.set('focus_on_delegate', 'off')
        out = self._delegate()
        self.assertIsNone(self.chat._pending_focus)
        self.assertNotIn('focus follows', out)

    def test_on_sets_pending_focus(self):
        self.chat.config.set('focus_on_delegate', 'on')
        out = self._delegate()
        self.assertEqual(self.chat._pending_focus['run'], self.run.id)
        self.assertIn(f'[focus follows: writer #{self.run.id}]', out)

    def test_ask_confirmed_sets_pending_focus(self):
        self.chat.config.set('focus_on_delegate', 'ask')
        self.chat._ui.confirm = MagicMock(return_value=True)
        self._delegate()
        self.chat._ui.confirm.assert_called_once()
        self.assertEqual(self.chat._pending_focus['run'], self.run.id)

    def test_ask_declined_keeps_focus(self):
        self.chat.config.set('focus_on_delegate', 'ask')
        self.chat._ui.confirm = MagicMock(return_value=False)
        self._delegate()
        self.assertIsNone(self.chat._pending_focus)

    def test_ask_unattended_skips_prompt(self):
        self.chat.config.set('focus_on_delegate', 'ask')
        self.chat._unattended = True
        self.chat._ui.confirm = MagicMock(return_value=True)
        self._delegate()
        self.chat._ui.confirm.assert_not_called()
        self.assertIsNone(self.chat._pending_focus)

    def test_invalid_mode_treated_as_off(self):
        self.chat.config.set('focus_on_delegate', 'sometimes')
        self._delegate()
        self.assertIsNone(self.chat._pending_focus)

    def test_sub_agent_has_no_focus_manager(self):
        sub = self.chat._new_sub_engine('writer', task='draft')
        sub.config.apply('focus_on_delegate', 'on')
        sub._init_tooling()
        sub.run_subagent = MagicMock(return_value=TurnResult(
            content='done', session='sub_2', status='ok', run_id=self.run.id))
        out = sub._run_tool('call', {'role': 'writer', 'task': 'x'})
        self.assertNotIn('focus follows', out)
        self.assertIsNone(self.chat._pending_focus)


class TestFocusOnDelegateLoop(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        seed_roles(self.chat, 'writer')
        self.chat.config.set('mode', 'write')
        self.chat.config.set('delegate_echo', False)

    def tearDown(self):
        self.chat._tmp.cleanup()

    def test_pending_focus_does_not_stop_the_turn(self):
        self.chat.config.set('focus_on_delegate', 'on')
        run = self.chat.runs.start(role='writer', session='sub_1')
        self.chat.run_subagent = MagicMock(return_value=TurnResult(
            content='done', session='sub_1', status='ok', run_id=run.id))
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': [
                {'id': 'call_1', 'type': 'function',
                 'function': {'name': 'call',
                              'arguments': json.dumps({'role': 'writer',
                                                       'task': 'draft it'})}},
            ]}],
            [{'type': 'token', 'content': 'Delegated.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        with patch('sys.stdout', new=io.StringIO()):
            self.chat._agent_loop()
        self.assertEqual(self.chat.provider.chat.call_count, 2)
        self.assertEqual(self.chat._pending_focus['run'], run.id)

    def test_apply_pending_focus_after_turn(self):
        run = self.chat.runs.start(role='writer', session='sub_1')
        self.chat._pending_focus = {'run': run.id}
        with patch('sys.stdout', new=io.StringIO()):
            self.chat._apply_handoff()
        self.assertEqual(self.chat.active().role, 'writer')
        self.assertIsNone(self.chat._pending_focus)


if __name__ == '__main__':
    unittest.main()
