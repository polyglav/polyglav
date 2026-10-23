import unittest

from polyglav.roles import Role
from polyglav.teams import Team, TeamStage

from tests.helpers import make_chat, seed_roles


class TestCallTarget(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        seed_roles(self.chat, 'writer')
        self.chat.config.set('mode', 'write')
        self.chat._init_tooling()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _result(self, text='done'):
        return [{'type': 'token', 'content': text},
                {'type': 'done', 'reason': 'stop'}]

    def test_call_role_target(self):
        self.chat.provider.chat.side_effect = [self._result('role done')]
        out = self.chat._run_tool('call', {'target': 'writer', 'task': 'x'})
        self.assertIn('[call writer] role done', out)

    def test_call_team_target(self):
        self.chat.teams.put(
            Team(name='doc', stages=[TeamStage(role='writer')]), scope='local')
        self.chat.provider.chat.side_effect = [self._result('team done')]
        out = self.chat._run_tool('call', {
            'target': 'doc', 'kind': 'team', 'task': 'x'})
        self.assertIn('[call doc] team done', out)

    def test_call_old_role_param(self):
        self.chat.provider.chat.side_effect = [self._result('role done')]
        out = self.chat._run_tool('call', {'role': 'writer', 'task': 'x'})
        self.assertIn('[call writer] role done', out)

    def test_call_schema_excludes_sibling(self):
        entry = self.chat._tool_registry.info('call')
        kinds = entry['parameters']['properties']['kind']['enum']
        self.assertNotIn('sibling', kinds)

    def test_call_unknown_target(self):
        out = self.chat._run_tool('call', {'target': 'ghost', 'task': 'x'})
        self.assertIn('disabled by tool policy', out)

    def test_call_schema_uses_target(self):
        entry = self.chat._tool_registry.info('call')
        props = entry['parameters']['properties']
        self.assertIn('target', props)
        self.assertIn('kind', props)
        self.assertNotIn('role', props)
        self.assertEqual(entry['permission'], 'call')

    def test_call_role_permission_denies(self):
        self.chat.roles.put(
            Role(name='writer', system_prompt='w',
                 tool_permission={'call': 'deny'}), scope='local')
        out = self.chat._run_tool('call', {'target': 'writer', 'task': 'x'})
        self.assertIn('disabled by tool policy', out)

    def test_call_team_permission_uses_call_key(self):
        self.chat.roles.put(
            Role(name='writer', system_prompt='w',
                 tool_permission={'call': 'deny'}), scope='local')
        self.chat.teams.put(
            Team(name='doc', stages=[TeamStage(role='writer')]), scope='local')
        out = self.chat._run_tool('call', {
            'target': 'doc', 'kind': 'team', 'task': 'x'})
        self.assertIn('disabled by tool policy', out)

    def test_call_team_ask_confirms(self):
        self.chat.roles.put(
            Role(name='writer', system_prompt='w',
                 tool_permission={'call': 'ask'}), scope='local')
        self.chat.teams.put(
            Team(name='doc', stages=[TeamStage(role='writer')]), scope='local')
        self.chat._ui.confirm = lambda name, label: False
        out = self.chat._run_tool('call', {
            'target': 'doc', 'kind': 'team', 'task': 'x'})
        self.assertIn('[cancelled]', out)


if __name__ == '__main__':
    unittest.main()
