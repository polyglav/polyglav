import io
import json
import unittest
from unittest.mock import patch

from polyglav.roles import Role

from tests.helpers import make_chat
from tests.test_engine import make_engine


class TestAskTool(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.sessions_dir = self.chat.config.local_path.parent / 'sessions'

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _ask_call(self, question='which port?', **extra):
        args = {'question': question}
        args.update(extra)
        return [{
            'id': 'call_ask001',
            'type': 'function',
            'function': {'name': 'ask', 'arguments': json.dumps(args)},
        }]

    def _tool_msgs(self):
        return [p for t in self.chat.current_session.turns
                for p in t.get('parts') or [] if p['type'] == 'tool']

    def test_ask_registered_in_schema(self):
        schema = self.chat._init_tooling()
        names = [s['function']['name'] for s in schema]
        self.assertIn('ask', names)
        entry = self.chat._tool_registry.info('ask')
        self.assertEqual(entry['category'], 'ask')
        self.assertEqual(entry['permission'], 'ask')
        params = entry['parameters']['properties']
        self.assertIn('question', params)
        self.assertIn('context', params)
        self.assertIn('options', params)
        self.assertNotIn('target', params)

    def test_human_ask_returns_answer(self):
        self.chat._init_tooling()
        with patch('builtins.input', return_value='Use port 8080'):
            out = self.chat._run_tool('ask', {'question': 'which port?'})
        self.assertEqual(out, 'Use port 8080')

    def test_ask_not_confirm_gated(self):
        self.chat._init_tooling()
        with patch.object(self.chat._ui, 'confirm',
                          side_effect=AssertionError('ask was confirm-gated')):
            with patch('builtins.input', return_value='Use port 8080'):
                out = self.chat._run_tool('ask', {'question': 'which port?'})
        self.assertEqual(out, 'Use port 8080')

    def test_human_ask_empty_is_cancelled(self):
        self.chat._init_tooling()
        with patch('builtins.input', return_value=''):
            out = self.chat._run_tool('ask', {'question': 'which port?'})
        self.assertIn('[cancelled]', out)
        self.assertIn('decide autonomously', out)

    def test_human_ask_context_and_options_presented(self):
        ui = self.chat._ask_ui
        with patch('builtins.input', return_value='b'):
            with patch('sys.stdout', new=io.StringIO()) as buf:
                result = ui.ask('which?', context='ctx',
                                options=['a', 'b'], origin=self.chat.current_session.session_name)
        self.assertEqual(result, 'b')
        out = buf.getvalue()
        self.assertIn('which?', out)
        self.assertIn('ctx', out)
        self.assertIn('1) a', out)
        self.assertIn('2) b', out)

    def test_ask_no_ui_no_lead_errors(self):
        engine = make_engine()
        try:
            engine._init_tooling()
            out = engine._run_tool('ask', {'question': 'which port?'})
            self.assertIn('Error: ask has no one to answer', out)
        finally:
            engine._tmp.cleanup()

    def test_direction_ask_rejects_degenerate_question(self):
        self.chat._init_tooling()
        with patch.object(self.chat._ask_ui, 'ask',
                          side_effect=AssertionError('user was asked')):
            out = self.chat._run_tool('ask', {'question': 'probe'})
        self.assertIn('too short', out)

    def test_direction_ask_short_with_context_accepted(self):
        self.chat._init_tooling()
        with patch('builtins.input', return_value='answer'):
            out = self.chat._run_tool('ask', {'question': 'probe',
                                              'context': 'some context'})
        self.assertEqual(out, 'answer')

    def test_direction_ask_guard_disabled(self):
        chat = make_chat({'ask_min_question_chars': 0})
        try:
            chat._init_tooling()
            with patch('builtins.input', return_value='answer'):
                out = chat._run_tool('ask', {'question': 'x'})
            self.assertEqual(out, 'answer')
        finally:
            chat._tmp.cleanup()

    def test_permission_ask_prompts_root(self):
        self.chat.current_session.mode = 'write'
        self.chat._init_tooling()
        with patch.object(self.chat._ask_ui, 'ask',
                          return_value='Approve once') as ask:
            out = self.chat._run_tool('ask', {
                'question': 'may I use the catalog?', 'kind': 'permission',
                'permission': 'catalog'})
        self.assertIn('[granted]', out)
        self.assertTrue(ask.called)

    def test_permission_ask_parks_when_unattended(self):
        chat = make_chat({'unattended': True})
        try:
            chat._init_tooling()
            with patch('builtins.input',
                       side_effect=AssertionError('stdin must not be read')):
                out = chat._run_tool('ask', {
                    'question': 'may I use the catalog?', 'kind': 'permission',
                    'permission': 'catalog'})
            self.assertIn('[parked]', out)
        finally:
            chat._tmp.cleanup()

    def test_read_mode_catalog_ask_offers_mode_switch(self):
        self.chat._init_tooling()
        with patch.object(self.chat._ask_ui, 'ask',
                          return_value='Approve (switch to write)') as ask:
            out = self.chat._run_tool('ask', {
                'question': 'may I use the catalog?', 'kind': 'permission',
                'permission': 'catalog'})
        self.assertIn('Write mode enabled', out)
        self.assertEqual(self.chat.current_session.mode, 'write')
        self.assertIn('Approve (switch to write)',
                      ask.call_args.kwargs['options'])

    def test_read_mode_permission_ask_switches_on_approval(self):
        self.chat._init_tooling()
        with patch('builtins.input', return_value='y'):
            with patch('sys.stdout', new=io.StringIO()):
                out = self.chat._run_tool('ask', {
                    'question': 'need the shell', 'kind': 'permission',
                    'permission': 'bash'})
        self.assertIn('[granted]', out)
        self.assertEqual(self.chat.current_session.mode, 'write')

    def test_read_mode_permission_ask_declined(self):
        self.chat._init_tooling()
        with patch('builtins.input', return_value='n'):
            with patch('sys.stdout', new=io.StringIO()):
                out = self.chat._run_tool('ask', {
                    'question': 'need the shell', 'kind': 'permission',
                    'permission': 'bash'})
        self.assertIn('[denied]', out)
        self.assertEqual(self.chat.current_session.mode, '')

    def test_read_mode_permission_ask_headless_points_at_mode_switch(self):
        engine = make_engine()
        try:
            engine._init_tooling()
            out = engine._run_tool('ask', {
                'question': 'need the shell', 'kind': 'permission',
                'permission': 'bash'})
            self.assertIn('needs write mode', out)
        finally:
            engine._tmp.cleanup()

    def test_subagent_user_ask_reaches_user(self):
        self.chat.roles.put(
            Role(name='w', system_prompt='Writer agent'), scope='local')
        sub = self.chat._new_sub_engine('w')
        self.assertIs(sub._ask_ui, self.chat._ask_ui)
        sub._init_tooling()
        with patch('builtins.input', return_value='use port 1234'):
            out = sub._run_tool('ask', {'question': 'which port?'})
        self.assertEqual(out, 'use port 1234')

    def test_subagent_default_ask_routes_to_user(self):
        self.chat.roles.put(
            Role(name='w', system_prompt='Writer agent'), scope='local')
        sub = self.chat._new_sub_engine('w')
        sub._init_tooling()
        with patch.object(self.chat._ask_ui, 'ask',
                          return_value='user decision'):
            out = sub._run_tool('ask', {'question': 'which option?'})
        self.assertEqual(out, 'user decision')
        self.chat.provider.chat_nonstreaming.assert_not_called()

    def test_subagent_direction_policy_user_prompts(self):
        self.chat.roles.put(
            Role(name='w', system_prompt='Writer agent',
                 ask_policy={'direction': 'user'}), scope='local')
        sub = self.chat._new_sub_engine('w')
        sub._init_tooling()
        with patch('builtins.input', return_value='from user'):
            out = sub._run_tool('ask', {'question': 'which option?'})
        self.assertEqual(out, 'from user')
        self.chat.provider.chat_nonstreaming.assert_not_called()

    def test_subagent_user_policy_prompts(self):
        self.chat.roles.put(
            Role(name='w', system_prompt='Writer agent'), scope='local')
        sub = self.chat._new_sub_engine('w')
        sub._init_tooling()
        with patch('builtins.input', return_value='from user'):
            out = sub._run_tool('ask', {'question': 'which option?'})
        self.assertEqual(out, 'from user')
        self.chat.provider.chat_nonstreaming.assert_not_called()

    def test_root_default_direction_prompts_user(self):
        self.chat._init_tooling()
        with patch('builtins.input', return_value='user decision'):
            out = self.chat._run_tool('ask', {'question': 'which option?'})
        self.assertEqual(out, 'user decision')

    def test_full_loop_persists_answer_and_continues(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._ask_call()}],
            [{'type': 'token', 'content': 'Final answer.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        with patch('builtins.input', return_value='Use 8080'):
            with patch('sys.stdout', new=io.StringIO()):
                self.chat._agent_loop()
        tools = self._tool_msgs()
        self.assertEqual(len(tools), 1)
        self.assertIn('Use 8080', tools[0]['output'])
        self.assertEqual(self.chat.provider.chat.call_count, 2)


if __name__ == '__main__':
    unittest.main()
