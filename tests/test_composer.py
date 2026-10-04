import json
import unittest

from polyglav.roles import Role
from tests.helpers import make_chat


class TestComposerType(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat.config.set('mode', 'write')
        self.chat.roles.put(Role(
            name='composer',
            system_prompt='You are the composer. Design teams.',
            tags=['management'],
            tool_permission={'bash': 'deny', 'catalog': 'allow',
                             'edit': 'deny', 'delegate': 'deny',
                             'list': 'allow', 'read': 'allow',
                             'web': 'allow'},
            ask_policy={'permission': 'auto', 'direction': 'user'}))

    def tearDown(self):
        self.chat._tmp.cleanup()

    def test_composer_definition(self):
        composer = self.chat.roles.find('composer')
        self.assertIsNotNone(composer)
        self.assertIn('composer', composer.system_prompt.lower())
        self.assertEqual(composer.tool_permission['catalog'], 'allow')
        self.assertEqual(composer.tool_permission['edit'], 'deny')
        self.assertEqual(composer.tool_permission['bash'], 'deny')
        self.assertEqual(composer.tool_permission['delegate'], 'deny')
        self.assertEqual(composer.tags, ['management'])

    def test_delegated_composer_can_manage_catalog(self):
        sub = self.chat._new_sub_engine('composer')
        sub._init_tooling()
        self.assertEqual(
            sub._tool_policy.action('catalog', 'catalog', None,
                                    {'action': 'list'}), 'allow')
        self.assertTrue(sub._tool_policy.allowed('catalog', 'catalog'))

    def test_composer_cannot_run_teams(self):
        sub = self.chat._new_sub_engine('composer')
        sub._init_tooling()
        self.assertFalse(sub._tool_policy.allowed('delegate', 'delegate'))
        self.assertTrue(sub._tool_policy.allowed('call', 'call'))

    def test_composer_saves_team_through_catalog(self):
        tool_call = [{
            'id': 'call_compose1',
            'type': 'function',
            'function': {'name': 'catalog', 'arguments': json.dumps({
                'action': 'save', 'kind': 'team', 'name': 'composed',
                'stages': [{'role': 'researcher'},
                           {'role': 'writer', 'skills': ['thesis']}]})},
        }]
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': tool_call}],
            [{'type': 'token', 'content': 'Team composed ready.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        result = self.chat.run_subagent('composer', 'build a writing team')
        self.assertEqual(result.content, 'Team composed ready.')
        team = self.chat.teams.find('composed')
        self.assertIsNotNone(team)
        self.assertEqual([s.role for s in team.stages],
                         ['researcher', 'writer'])
        self.assertEqual(team.stages[1].skills, ['thesis'])


if __name__ == '__main__':
    unittest.main()
