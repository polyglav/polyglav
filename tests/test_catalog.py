import unittest

from polyglav.roles import Role

from tests.helpers import make_chat


class TestCatalogTool(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat._init_tooling()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _catalog(self, **args):
        return self.chat._tool_registry.execute('catalog', args)

    def test_registered(self):
        entry = self.chat._tool_registry.info('catalog')
        self.assertEqual(entry['category'], 'catalog')
        self.assertEqual(entry['permission'], 'catalog')
        params = entry['parameters']['properties']
        for key in ('action', 'kind', 'name', 'content', 'stages'):
            self.assertIn(key, params)

    def test_default_permission_is_allow(self):
        policy = self.chat._tool_policy
        self.assertEqual(
            policy.action('catalog', 'catalog', None, {'action': 'list'}), 'allow')
        self.assertTrue(policy.allowed('catalog', 'catalog'))

    def test_type_override_allows(self):
        perms = dict(self.chat.config.get('tool_permission'))
        perms['catalog'] = 'allow'
        self.chat.config.apply('tool_permission', perms)
        self.chat.roles.put(
            Role(name='composer', system_prompt='c',
                      tool_permission={'catalog': 'allow'}), scope='local')
        sub = self.chat._new_sub_engine('composer')
        sub._init_tooling()
        self.assertEqual(
            sub._tool_policy.action('catalog', 'catalog', None,
                                    {'action': 'list'}), 'allow')

    def test_list_types(self):
        out = self._catalog(action='list', kind='role')
        self.assertIn('leader', out)

    def test_list_teams(self):
        out = self._catalog(action='list', kind='team')
        self.assertIn('writing', out)
        self.assertIn('researcher > writer', out)

    def test_show_type(self):
        out = self._catalog(action='show', kind='role', name='leader')
        self.assertIn('system_prompt:', out)

    def test_show_team(self):
        out = self._catalog(action='show', kind='team', name='writing')
        self.assertIn('1. researcher', out)
        self.assertIn('task_hint:', out)

    def test_show_unknown(self):
        self.assertIn('unknown team', self._catalog(
            action='show', kind='team', name='ghost'))

    def test_save_type(self):
        out = self._catalog(action='save', kind='role', name='essayist',
                            system_prompt='You write essays.',
                            skills=['composing'], tags=['writing'])
        self.assertIn('Saved role: essayist', out)
        saved = self.chat.roles.find('essayist')
        self.assertEqual(saved.system_prompt, 'You write essays.')
        self.assertEqual(saved.skills, ['composing'])
        self.assertEqual(self.chat.roles.origin('essayist'), 'local')

    def test_save_team_with_stages(self):
        out = self._catalog(
            action='save', kind='team', name='thesis', description='writing',
            stages=[{'role': 'researcher', 'skills': ['sourcing']},
                    {'role': 'writer', 'handoff_note': 'draft'}])
        self.assertIn('Saved team: thesis', out)
        team = self.chat.teams.find('thesis')
        self.assertEqual([s.role for s in team.stages], ['researcher', 'writer'])
        self.assertEqual(team.stages[0].skills, ['sourcing'])
        self.assertEqual(team.stages[1].handoff_note, 'draft')

    def test_save_skill_writes_file(self):
        out = self._catalog(action='save', kind='skill', name='composing',
                            content='# composing\n\nCompose teams.')
        self.assertIn('Saved skill: composing', out)
        path = self.chat.config.local_path.parent / 'skills' / 'composing.md'
        self.assertTrue(path.exists())
        self.assertIn('Compose teams.', self.chat.skills.find('composing').content)

    def test_reload_picks_up_external_file(self):
        path = self.chat.config.local_path.parent / 'skills' / 'external.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('external skill')
        out = self._catalog(action='reload')
        self.assertIn('Reloaded', out)
        self.assertIsNotNone(self.chat.skills.find('external'))

    def test_remove_local(self):
        self._catalog(action='save', kind='team', name='tmp')
        out = self._catalog(action='remove', kind='team', name='tmp')
        self.assertIn('Removed team: tmp', out)
        self.assertIsNone(self.chat.teams.find('tmp'))

    def test_remove_bundled_rejected(self):
        out = self._catalog(action='remove', kind='team', name='writing')
        self.assertIn('bundled', out)
        self.assertIsNotNone(self.chat.teams.find('writing'))

    def test_remove_non_local_skill_rejected(self):
        self.chat.skills.add_plugin({'name': 'plug', 'content': 'x'})
        out = self._catalog(action='remove', kind='skill', name='plug')
        self.assertIn('not local', out)

    def test_unknown_kind(self):
        out = self._catalog(action='list', kind='nope')
        self.assertIn('Error: kind must be role, team, or skill', out)

    def test_type_alias_for_role(self):
        out = self._catalog(action='show', kind='type', name='leader')
        self.assertIn('system_prompt:', out)
        self.assertNotIn('Error', out)

    def test_missing_name(self):
        out = self._catalog(action='save', kind='role')
        self.assertIn('name is required', out)

    def test_cross_engine_reload(self):
        self.chat.teams
        sub = self.chat._new_sub_engine('leader')
        sub._init_tooling()
        sub._tool_registry.execute(
            'catalog', {'action': 'save', 'kind': 'team', 'name': 'built',
                        'stages': [{'role': 'researcher'}]})
        self.assertIsNone(self.chat.teams.find('built'))
        self.chat._reload_catalogs_if_changed()
        self.assertIsNotNone(self.chat.teams.find('built'))

    def test_unknown_action(self):
        out = self._catalog(action='dance', kind='role')
        self.assertIn('Error: action must be', out)

    def test_read_mode_gates_catalog_writes(self):
        policy = self.chat._tool_policy
        for read_action in ('list', 'show'):
            self.assertEqual(
                policy.action('catalog', 'catalog', None,
                              {'action': read_action}), 'allow')
        for write_action in ('save', 'remove', 'reload'):
            self.assertEqual(
                policy.action('catalog', 'catalog', None,
                              {'action': write_action}), 'deny')

    def test_write_mode_allows_catalog_writes(self):
        self.chat.current_session.mode = 'write'
        self.chat._init_tooling()
        policy = self.chat._tool_policy
        self.assertEqual(
            policy.action('catalog', 'catalog', None, {'action': 'save'}),
            'allow')
        self.assertEqual(
            policy.action('catalog', 'catalog', None, {'action': 'list'}),
            'allow')


if __name__ == '__main__':
    unittest.main()
