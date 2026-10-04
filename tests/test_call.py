import io
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from polyglav.roles import Role
from polyglav.sessions import turns as session_turns

from tests.helpers import make_chat, seed_roles


class TestDelegateTool(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        seed_roles(self.chat, 'writer', 'programmer')
        self.chat.config.set('mode', 'write')
        self.sessions_dir = self.chat.config.local_path.parent / 'sessions'

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _delegate_call(self, role_name='writer', task='write the doc'):
        return [{
            'id': 'call_del001',
            'type': 'function',
            'function': {'name': 'call',
                         'arguments': json.dumps({'role': role_name,
                                                  'task': task})},
        }]

    def _run(self):
        with patch('sys.stdout', new=io.StringIO()):
            self.chat._agent_loop()

    def _tool_msgs(self):
        return [p for t in self.chat.current_session.turns
                for p in t.get('parts') or [] if p['type'] == 'tool']

    def _allow_delegate(self, name='writer'):
        self.chat.roles.put(
            Role(name=name, system_prompt='Writer agent',
                      tool_permission={'call': 'allow'}), scope='local')

    def _delegate_logs(self, role_name):
        return sorted(
            f for f in self.sessions_dir.glob('sub_*.json')
            if json.loads(f.read_text()).get('parent_id')
            == self.chat.current_session.session_name)

    def _sub_footer_called(self):
        for c in self.chat._ui.footer.call_args_list:
            args = c[0]
            if len(args) == 2 and not args[1]:
                return True
        return False

    def test_allowed_type_runs_subagent(self):
        self._allow_delegate()
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._delegate_call()}],
            [{'type': 'token', 'content': 'Draft text.'},
             {'type': 'done', 'reason': 'stop'}],
            [{'type': 'token', 'content': 'Final answer.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        with patch('sys.stdout', new=io.StringIO()):
            self.chat._agent_loop()
        self.assertEqual(self.chat.provider.chat.call_count, 3)
        tools = self._tool_msgs()
        self.assertTrue(tools)
        self.assertIn('[call writer] Draft text.', tools[0]['output'])
        self.assertTrue(self._delegate_logs('writer'))

    def test_echo_on_prints_result_and_footer(self):
        self._allow_delegate()
        self.chat._ui.tool_result = MagicMock()
        self.chat._ui.footer = MagicMock()
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._delegate_call()}],
            [{'type': 'token', 'content': 'Draft text.'},
             {'type': 'done', 'reason': 'stop'}],
            [{'type': 'token', 'content': 'Final.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self._run()
        self.chat._ui.tool_result.assert_called()
        self.assertTrue(self._sub_footer_called())

    def test_echo_off_hides_result_and_footer(self):
        self._allow_delegate()
        self.chat.config.apply('delegate_echo', False)
        self.chat._ui.tool_result = MagicMock()
        self.chat._ui.footer = MagicMock()
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._delegate_call()}],
            [{'type': 'token', 'content': 'Draft text.'},
             {'type': 'done', 'reason': 'stop'}],
            [{'type': 'token', 'content': 'Final.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self._run()
        self.chat._ui.tool_result.assert_not_called()
        self.assertFalse(self._sub_footer_called())

    def test_default_allow_does_not_prompt(self):
        self.chat._ui.confirm = MagicMock()
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._delegate_call()}],
            [{'type': 'token', 'content': 'Draft text.'},
             {'type': 'done', 'reason': 'stop'}],
            [{'type': 'token', 'content': 'Final.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self._run()
        self.assertEqual(self.chat.provider.chat.call_count, 3)
        self.chat._ui.confirm.assert_not_called()
        self.assertIn('[call writer] Draft text.',
                      self._tool_msgs()[0]['output'])

    def test_type_ask_requires_confirm(self):
        self.chat.roles.put(
            Role(name='writer', system_prompt='W',
                      tool_permission={'call': 'ask'}), scope='local')
        self.chat._ui.confirm = MagicMock(return_value=False)
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._delegate_call()}],
            [{'type': 'token', 'content': 'Final.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self._run()
        self.assertEqual(self.chat.provider.chat.call_count, 2)
        tools = self._tool_msgs()
        self.assertTrue(tools)
        self.assertIn('[cancelled]', tools[0]['output'])
        self.assertFalse(self._delegate_logs('writer'))

    def test_confirm_granted_runs(self):
        self.chat.roles.put(
            Role(name='writer', system_prompt='W',
                      tool_permission={'call': 'ask'}), scope='local')
        self.chat._ui.confirm = MagicMock(return_value=True)
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._delegate_call()}],
            [{'type': 'token', 'content': 'Draft text.'},
             {'type': 'done', 'reason': 'stop'}],
            [{'type': 'token', 'content': 'Final.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self._run()
        self.assertEqual(self.chat.provider.chat.call_count, 3)
        self.assertIn('[call writer] Draft text.',
                      self._tool_msgs()[0]['output'])

    def test_unknown_type_denied(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._delegate_call('ghost')}],
            [{'type': 'token', 'content': 'Final.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self._run()
        self.assertEqual(self.chat.provider.chat.call_count, 2)
        tools = self._tool_msgs()
        self.assertTrue(tools)
        self.assertIn('disabled by tool policy', tools[0]['output'])
        self.assertFalse(self._delegate_logs('ghost'))

    def test_tool_command_delegates_single_print(self):
        self._allow_delegate()
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'Sub result.'},
             {'type': 'done', 'reason': 'stop'}],
            [{'type': 'token', 'content': 'Root summary.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        with patch('sys.stdout', new=io.StringIO()) as buf:
            self.chat.registry.dispatch(
                '/tool call {"role": "writer", "task": "write"}')
        out = buf.getvalue()
        self.assertEqual(out.count('[call writer] Sub result.'), 1)
        self.assertTrue(self._delegate_logs('writer'))

    def test_tool_command_delegate_runs_loop_turn(self):
        self._allow_delegate()
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'Sub result.'},
             {'type': 'done', 'reason': 'stop'}],
            [{'type': 'token', 'content': 'Root summary.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        with patch('sys.stdout', new=io.StringIO()):
            self.chat.registry.dispatch(
                '/tool call {"role": "writer", "task": "write"}')
        roles = [p['type'] for t in self.chat.current_session.turns
                 for p in t.get('parts') or []]
        self.assertIn('text', roles)
        self.assertIn('tool', roles)
        self.assertEqual(self.chat.provider.chat.call_count, 2)
        final = [p for t in self.chat.current_session.turns
                 for p in t.get('parts') or []
                 if p['type'] == 'text' and p.get('text')]
        self.assertTrue(final)
        self.assertEqual(final[-1]['text'], 'Root summary.')

    def test_forwards_skills_to_subagent(self):
        from types import SimpleNamespace
        self.chat.roles.put(
            Role(name='dev', system_prompt='Dev',
                      tool_permission={'call': 'allow'}), scope='local')
        with patch.object(self.chat, 'run_subagent', return_value=SimpleNamespace(
                status='ok', content='done', errors=[], session='sub_x',
                duration=0.0, usage=None)) as run:
            self.chat._init_tooling()
            self.chat._tool_registry.execute(
                'call', {'role': 'dev', 'task': 't',
                             'skills': ['django']})
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs.get('skills'), ['django'])

    def test_resolver_actions(self):
        self._allow_delegate()
        self.chat._init_tooling()
        policy = self.chat._tool_policy
        args_allow = {'role': 'writer', 'task': 't'}
        args_default = {'role': 'programmer', 'task': 't'}
        args_unknown = {'role': 'ghost', 'task': 't'}
        self.assertEqual(
            policy.action('call', 'call', None, args_allow), 'allow')
        self.assertEqual(
            policy.action('call', 'call', None, args_default), 'allow')
        self.assertEqual(
            policy.action('call', 'call', None, args_unknown), 'deny')
        self.assertTrue(policy.allowed('call', 'call'))

    def test_empty_result_uses_log_summary(self):
        from types import SimpleNamespace
        from polyglav.sessions.manager import Session
        from polyglav.tools.call import _format_result
        subname = 'sub_20260825_000000_ses_20260825_000000_parent'
        sess = Session(subname, turns_list=[self._summary_turn()])
        self.chat.sessions.save(sess)
        result = SimpleNamespace(status='ok', content='', session=subname,
                                 errors=[], usage=None)
        out = _format_result(self.chat, 'programmer', result)
        self.assertIn('no final text', out)
        self.assertIn('2 tool calls', out)
        self.assertIn('wrote:', out)
        self.assertIn('main.py', out)
        self.assertIn('last bash', out)

    def _summary_turn(self):
        turn = session_turns.new_turn(1)
        session_turns.add_part(turn, session_turns.user_part('build the dungeon'))
        p1 = session_turns.add_part(turn, session_turns.tool_part('file_write', {}))
        session_turns.finish_tool(
            p1, 'Created /tmp/x/main.py (40 lines, 900 chars)')
        p2 = session_turns.add_part(turn, session_turns.tool_part('bash', {}))
        session_turns.finish_tool(p2, '$ cd /tmp/x && pytest\n1 passed')
        session_turns.finish_turn(turn, 'ok')
        return turn


if __name__ == '__main__':
    unittest.main()