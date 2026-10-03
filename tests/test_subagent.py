import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from polyglav.roles import Role
from polyglav.ui import BufferUI

from tests.helpers import make_chat


class TestSubAgentEngine(unittest.TestCase):

    def setUp(self):
        self.tmp = MagicMock()
        self.chat = make_chat()
        self.sessions_dir = self.chat.config.local_path.parent / 'sessions'

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _delegate_log(self, role_name):
        files = sorted(
            f for f in self.sessions_dir.glob('sub_*.json')
            if json.loads(f.read_text()).get('parent_id')
            == self.chat.current_session.session_name)
        self.assertTrue(files,
                        f'no sub_* child of {self.chat.current_session.session_name} saved')
        return json.loads(files[-1].read_text())

    def _tool_call(self, name='run_command', args='{"command": "echo hi"}'):
        return [{
            'id': 'call_sub001',
            'type': 'function',
            'function': {'name': name, 'arguments': args},
        }]

    def test_subagent_inherits_provider_and_plugins(self):
        sub = self.chat._new_sub_engine('writer')
        self.assertEqual(sub.role, 'writer')
        self.assertEqual(sub.current_session.role, 'writer')
        self.assertIs(sub.provider, self.chat.provider)
        self.assertIs(sub._plugin_manager, self.chat._plugin_manager)
        self.assertTrue(sub.current_session.session_name.startswith('sub_'))
        self.assertEqual(len(sub.current_session.session_id), 6)
        self.assertTrue(sub.current_session.session_name.endswith(
            f'_{sub.current_session.session_id}'))
        self.assertEqual(sub.current_run.session_id, sub.current_session.session_id)
        self.assertEqual(sub.current_session.parent_id,
                         self.chat.current_session.session_name)

    def test_sub_session_name_embeds_id(self):
        from polyglav.engine import _sub_session_name
        from polyglav.sessions.manager import session_id_from_name
        name = _sub_session_name('ses_20260825_110000_ab12cd',
                                 self.sessions_dir)
        self.assertTrue(name.startswith('sub_'))
        code = session_id_from_name(name)
        self.assertEqual(len(code), 6)
        self.assertTrue(name.endswith(f'_{code}'))

    def test_sub_session_name_is_unique(self):
        from polyglav.engine import _sub_session_name
        names = {_sub_session_name('parent', self.sessions_dir)
                 for _ in range(10)}
        self.assertEqual(len(names), 10)

    def test_subagent_applies_type_prompt_mode_permissions(self):
        sub = self.chat._new_sub_engine('writer')
        self.assertEqual(sub.config.get('mode'), 'read')
        self.assertTrue(sub.config.get('system_prompt').startswith(
            'You are the writer.'))
        tp = sub.config.get('tool_permission')
        self.assertEqual(tp['edit'], 'allow')
        self.assertEqual(tp['bash'], 'deny')
        self.assertEqual(tp['web'], 'deny')

    def test_subagent_inherits_session_mode(self):
        self.chat.current_session.mode = 'write'
        sub = self.chat._new_sub_engine('writer')
        self.assertEqual(sub.config.get('mode'), 'write')
        self.assertEqual(sub.current_session.mode, 'write')

    def test_subagent_injects_type_skills(self):
        from polyglav.skills import Skill
        self.chat.roles.put(
            Role(name='researcher', system_prompt='You are the researcher.',
                    skills=['finders', 'filters']),
            scope='local')
        self.chat.skills.put(
            Skill(name='finders', content='Find sources and evaluate them.'))
        self.chat.skills.put(
            Skill(name='filters', content='Filter for credible, on-topic sources.'))
        sub = self.chat._new_sub_engine('researcher')
        prompt = sub.config.get('system_prompt')
        self.assertIn('You are the researcher.', prompt)
        self.assertIn('## Skills', prompt)
        self.assertIn('### finders', prompt)
        self.assertIn('Find sources and evaluate them.', prompt)
        self.assertIn('### filters', prompt)

    def test_subagent_skips_missing_skills(self):
        from polyglav.skills import Skill
        self.chat.roles.put(
            Role(name='x', system_prompt='prompt',
                    skills=['present', 'deleted']),
            scope='local')
        self.chat.skills.put(Skill(name='present', content='Present skill body.'))
        sub = self.chat._new_sub_engine('x')
        prompt = sub.config.get('system_prompt')
        self.assertIn('Present skill body.', prompt)
        self.assertNotIn('deleted', prompt)
        self.assertNotIn('## Skills\n\n### deleted', prompt)

    def test_subagent_without_skills_prompt_unchanged(self):
        self.chat.roles.put(
            Role(name='plain', system_prompt='plain prompt', skills=[]),
            scope='local')
        sub = self.chat._new_sub_engine('plain')
        self.assertEqual(sub.config.get('system_prompt'), 'plain prompt')

    def test_subagent_skills_only_prompt(self):
        from polyglav.skills import Skill
        self.chat.roles.put(
            Role(name='solo', system_prompt='', skills=['one']),
            scope='local')
        self.chat.skills.put(Skill(name='one', content='Skill only body.'))
        sub = self.chat._new_sub_engine('solo')
        prompt = sub.config.get('system_prompt')
        self.assertEqual(prompt, '## Skills\n\n### one\n\nSkill only body.')

    def test_subagent_merges_invocation_skills(self):
        from polyglav.skills import Skill
        self.chat.roles.put(
            Role(name='dev', system_prompt='You are a developer.',
                      skills=['base']),
            scope='local')
        self.chat.skills.put(Skill(name='base', content='Base experience.'))
        self.chat.skills.put(Skill(name='django', content='Use Django.'))
        sub = self.chat._new_sub_engine('dev', skills=['django'])
        prompt = sub.config.get('system_prompt')
        self.assertIn('You are a developer.', prompt)
        self.assertIn('Base experience.', prompt)
        self.assertIn('Use Django.', prompt)
        self.assertLess(prompt.index('Base experience.'),
                        prompt.index('Use Django.'))

    def test_subagent_invocation_skills_dedupe(self):
        from polyglav.skills import Skill
        self.chat.roles.put(
            Role(name='dev', system_prompt='p', skills=['base']),
            scope='local')
        self.chat.skills.put(Skill(name='base', content='Base experience.'))
        sub = self.chat._new_sub_engine('dev', skills=['base', 'base'])
        prompt = sub.config.get('system_prompt')
        self.assertEqual(prompt.count('### base'), 1)

    def test_subagent_invocation_skills_ignores_empty_names(self):
        from polyglav.skills import Skill
        self.chat.roles.put(
            Role(name='dev', system_prompt='p'), scope='local')
        self.chat.skills.put(Skill(name='extra', content='Extra skill body.'))
        sub = self.chat._new_sub_engine('dev', skills=['', None, 'extra'])
        self.assertIn('Extra skill body.', sub.config.get('system_prompt'))

    def test_run_subagent_passes_invocation_skills(self):
        from polyglav.skills import Skill
        self.chat.roles.put(
            Role(name='plain2', system_prompt='plain prompt'),
            scope='local')
        self.chat.skills.put(Skill(name='extra', content='Extra skill body.'))
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'ok'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self.chat.run_subagent('plain2', 'do it', skills=['extra'])
        messages = self.chat.provider.chat.call_args[0][0]
        system = next(m for m in messages if m.get('role') == 'system')
        self.assertIn('Extra skill body.', system['content'])

    def test_subagent_uses_buffer_ui(self):
        sub = self.chat._new_sub_engine('writer')
        self.assertIsInstance(sub.ui, BufferUI)
        self.assertIs(sub.ui.run, sub.current_run)

    def test_model_override_applies(self):
        self.chat.roles.put(
            Role(name='special', system_prompt='sp', model='deepseek-r1'),
            scope='local')
        sub = self.chat._new_sub_engine('special')
        self.assertEqual(sub.config.get('model'), 'deepseek-r1')
        self.assertEqual(sub.provider.model, 'deepseek-r1')

    def test_inherits_shared_worktree(self):
        sub = self.chat._new_sub_engine('writer')
        self.assertEqual(sub.config.local_path.parent.parent,
                         self.chat.config.local_path.parent.parent)

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            self.chat._new_sub_engine('nope')

    def test_run_subagent_returns_result_and_persists(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'Draft ready.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        result = self.chat.run_subagent('writer', 'write the doc')
        self.assertEqual(result.content, 'Draft ready.')
        self.assertTrue(result.session.startswith('sub_'))
        from polyglav.sessions.manager import session_id_from_name
        self.assertEqual(len(session_id_from_name(result.session)), 6)
        data = self._delegate_log('writer')
        parts = [p for t in data['turns'] for p in t.get('parts') or []]
        self.assertEqual(parts[0]['type'], 'user')
        self.assertEqual(parts[-1]['type'], 'text')
        self.assertEqual(parts[-1]['text'], 'Draft ready.')
        self.assertEqual(data['parent_id'], self.chat.current_session.session_name)
        self.assertIn(result.session, self.chat.current_session.sub_sessions)
        self.chat.sessions.save(self.chat.current_session)
        parent = self.chat.sessions.read(self.chat.current_session.session_name)
        self.assertIn(result.session, parent.sub_sessions)

    def test_run_subagent_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            self.chat.run_subagent('nope', 'anything')

    def test_ask_gated_tool_denied_without_prompt(self):
        self.chat.config.set('mode', 'write')
        self.chat.roles.put(
            Role(name='defaults', system_prompt='plain agent'),
            scope='local')
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._tool_call()}],
            [{'type': 'token', 'content': 'final'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        result = self.chat.run_subagent('defaults', 'run the build')
        self.assertEqual(self.chat.provider.chat.call_count, 2)
        data = self._delegate_log('defaults')
        tools = [p for t in data['turns'] for p in t.get('parts') or []
                 if p['type'] == 'tool']
        self.assertTrue(tools)
        self.assertIn('permission denied', tools[0]['output'])
        self.assertNotIn('[cancelled]', tools[0]['output'])
        self.assertTrue(tools[0]['is_error'])
        self.assertEqual(result.content, 'final')

    def test_subagent_stops_after_repeated_denials(self):
        self.chat.config.set('mode', 'write')
        self.chat.roles.put(
            Role(name='loopless', system_prompt='plain'), scope='local')
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._tool_call()}],
            [{'type': 'tool_calls', 'tool_calls': self._tool_call()}],
            [{'type': 'tool_calls', 'tool_calls': self._tool_call()}],
        ]
        result = self.chat.run_subagent('loopless', 'run the build')
        self.assertEqual(result.status, 'error')
        self.assertEqual(self.chat.provider.chat.call_count, 3)

    def test_subagent_prompt_warns_on_auto_denied_categories(self):
        self.chat.config.apply('grant_permission', {'bash': 'ask'})
        self.chat.roles.put(
            Role(name='tester2', system_prompt='You test.',
                 tool_permission={'bash': 'allow'}), scope='local')
        sub = self.chat._new_sub_engine('tester2')
        prompt = sub.config.get('system_prompt')
        self.assertIn('no interactive confirmation', prompt)
        self.assertIn('bash', prompt)


if __name__ == '__main__':
    unittest.main()