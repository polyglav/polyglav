import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from polyglav.teams import Team, TeamRegistry, TeamStage
from polyglav.config import Config

from tests.helpers import make_chat


class StubPluginManager:
    def __init__(self, entries):
        self.entries = entries

    def register_teams(self, registry):
        for entry in self.entries:
            registry.add_plugin(entry)


class TestTeamRegistry(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.local = self.base / 'proj' / '.polyglav' / 'teams.json'

    def tearDown(self):
        self.tmp.cleanup()

    def reg(self, global_dir=None, local_path=None):
        return TeamRegistry(global_dir=global_dir or self.base,
                            local_path=local_path or self.local)

    def test_paths(self):
        reg = self.reg()
        self.assertEqual(reg.global_path,
                         self.base / '.config' / 'polyglav' / 'teams.json')
        self.assertEqual(reg.local_path, self.local)

    def test_empty(self):
        self.assertEqual(self.reg().all(), [])
        self.assertEqual(self.reg().names(), [])

    def test_put_local_and_find(self):
        reg = self.reg()
        reg.put(Team(name='writing', stages=[
            TeamStage(role='researcher', task_hint='gather'),
            TeamStage(role='writer', handoff_note='pass the draft'),
        ]))
        t = reg.find('writing')
        self.assertIsNotNone(t)
        self.assertEqual([s.role for s in t.stages],
                         ['researcher', 'writer'])
        self.assertEqual(t.stages[0].task_hint, 'gather')
        self.assertEqual(t.stages[1].handoff_note, 'pass the draft')
        self.assertEqual(reg.origin('writing'), 'local')

    def test_put_fields_roundtrip(self):
        reg = self.reg()
        reg.put(Team(name='x', description='d', tags=['writing'],
                     stages=[TeamStage(role='p', mode='plan',
                                       task_hint='h', handoff_note='n')]))
        t = reg.find('x')
        self.assertEqual(t.description, 'd')
        self.assertEqual(t.tags, ['writing'])
        self.assertEqual(t.stages[0].mode, 'plan')
        s = t.stages[0]
        self.assertEqual((s.role, s.mode, s.task_hint, s.handoff_note),
                         ('p', 'plan', 'h', 'n'))

    def test_stage_skills_roundtrip(self):
        reg = self.reg()
        reg.put(Team(name='x', stages=[
            TeamStage(role='writer', skills=['latex', 'de'])]))
        t = reg.find('x')
        self.assertEqual(t.stages[0].skills, ['latex', 'de'])

    def test_short_string_stage(self):
        reg = self.reg()
        reg.put(Team(name='x', stages=[TeamStage(role='p')]))
        t = reg.find('x')
        self.assertEqual(t.stages[0].role, 'p')

    def test_global_and_local_merge_local_wins(self):
        g = TeamRegistry(global_dir=self.base,
                         local_path=Path(self.tmp.name) / 'g' / 't.json')
        g.put(Team(name='x', description='global description'), scope='global')
        reg = self.reg()
        reg.put(Team(name='x', description='local description'), scope='local')
        t = reg.find('x')
        self.assertEqual(t.description, 'local description')
        self.assertEqual(reg.origin('x'), 'merged')

    def test_stage_fields_inherit_on_field_merge(self):
        reg = self.reg()
        reg.put(Team(name='x', stages=[TeamStage(role='p')]), scope='global')
        reg.put(Team(name='x'), scope='local')
        t = reg.find('x')
        self.assertEqual([s.role for s in t.stages], ['p'])

    def test_local_stages_replace_wholesale(self):
        reg = self.reg()
        reg.put(Team(name='x', stages=[TeamStage(role='a')]), scope='global')
        reg.put(Team(name='x', stages=[TeamStage(role='b')]), scope='local')
        t = reg.find('x')
        self.assertEqual([s.role for s in t.stages], ['b'])

    def test_local_only_does_not_add_to_global(self):
        reg = self.reg()
        reg.put(Team(name='only-local'), scope='local')
        fresh = TeamRegistry(global_dir=self.base,
                             local_path=Path(self.tmp.name) / 'z' / 't.json')
        self.assertIsNone(fresh.find('only-local'))

    def test_remove_local(self):
        reg = self.reg()
        reg.put(Team(name='x'))
        self.assertTrue(reg.remove('x'))
        self.assertIsNone(reg.find('x'))
        self.assertFalse(reg.remove('x'))

    def test_all_sorted_by_name(self):
        reg = self.reg()
        reg.put(Team(name='z'))
        reg.put(Team(name='a'))
        self.assertEqual([t.name for t in reg.all()], ['a', 'z'])
        self.assertEqual(reg.names(), ['a', 'z'])

    def test_default_uses_config_global_dir(self):
        prev = Config.GLOBAL_DIR
        Config.GLOBAL_DIR = self.base
        try:
            reg = TeamRegistry(local_path=self.local)
            self.assertEqual(reg.global_path,
                             self.base / '.config' / 'polyglav' / 'teams.json')
        finally:
            Config.GLOBAL_DIR = prev

    def test_bad_json_ignored(self):
        self.local.parent.mkdir(parents=True, exist_ok=True)
        self.local.write_text('{invalid')
        self.assertEqual(self.reg().all(), [])

    def test_add_plugin_team(self):
        reg = self.reg()
        reg.add_plugin({'name': 'plug', 'stages': [{'role': 'writer'}],
                        'description': 'from a plugin'})
        t = reg.find('plug')
        self.assertIsNotNone(t)
        self.assertEqual([s.role for s in t.stages], ['writer'])
        self.assertEqual(reg.origin('plug'), 'plugin')
        self.assertIn('plug', reg.names())

    def test_add_plugin_invalid_entry_ignored(self):
        reg = self.reg()
        reg.add_plugin({'stages': []})
        reg.add_plugin('nope')
        self.assertEqual(reg.all(), [])

    def test_add_plugin_writes_nothing_to_disk(self):
        reg = self.reg()
        reg.add_plugin({'name': 'plug', 'stages': []})
        self.assertFalse(self.local.exists())
        reg.put(Team(name='mine'), scope='local')
        saved = json.loads(self.local.read_text())
        self.assertEqual(list(saved), ['mine'])

    def test_global_overrides_plugin(self):
        reg = self.reg()
        reg.add_plugin({'name': 'x', 'description': 'plugin desc'})
        reg.put(Team(name='x', description='global desc'), scope='global')
        self.assertEqual(reg.find('x').description, 'global desc')
        self.assertEqual(reg.origin('x'), 'merged')
        reg.remove('x', scope='global')
        self.assertEqual(reg.find('x').description, 'plugin desc')

    def test_reload_rereads_disk(self):
        reg = self.reg()
        self.local.parent.mkdir(parents=True, exist_ok=True)
        self.local.write_text(json.dumps(
            {'x': {'name': 'x', 'stages': [{'role': 'p'}]}}))
        reg.reload()
        self.assertEqual([s.role for s in reg.find('x').stages], ['p'])

    def test_reload_reapplies_plugin_contributions(self):
        reg = self.reg()
        reg.reload(StubPluginManager([{'name': 'old', 'stages': []}]))
        self.assertIsNotNone(reg.find('old'))
        reg.reload(StubPluginManager([{'name': 'new', 'stages': []}]))
        self.assertIsNone(reg.find('old'))
        self.assertIsNotNone(reg.find('new'))

    def test_reload_without_plugin_manager_clears_plugin_scope(self):
        reg = self.reg()
        reg.add_plugin({'name': 'plug', 'stages': []})
        reg.reload()
        self.assertIsNone(reg.find('plug'))


class TestTeamCommand(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()
        self.tmp.cleanup()

    def _team(self, arg=''):
        with patch('sys.stdout', new=io.StringIO()) as buf:
            self.chat.registry.dispatch('/teams ' + arg)
        return buf.getvalue()

    def _seed(self):
        self.chat.teams.put(Team(
            name='writing', description='Document pipeline',
            tags=['research', 'writing'],
            stages=[TeamStage(role='researcher', task_hint='gather',
                              handoff_note='pass to writer'),
                    TeamStage(role='writer')]))
        self.chat.teams.put(Team(name='programming', tags=['programming'],
                                 stages=[TeamStage(role='planner')]))

    def test_list_empty(self):
        out = self._team()
        self.assertIn('no teams configured', out)

    def test_list_shows_local(self):
        self._seed()
        out = self._team()
        self.assertIn('2 teams', out)
        self.assertIn('writing', out)
        self.assertIn('(local)', out)
        self.assertIn('researcher > writer', out)

    def test_list_shows_tags(self):
        self._seed()
        out = self._team()
        self.assertIn('tags=research,writing', out)
        self.assertIn('tags=programming', out)

    def test_list_filter_by_tag(self):
        self._seed()
        out = self._team('list programming')
        self.assertIn('programming', out)
        self.assertNotIn('writing', out)
        out = self._team('list writing')
        self.assertIn('writing', out)

    def test_list_unknown_tag(self):
        self._seed()
        out = self._team('list nonexistent')
        self.assertIn('no teams tagged "nonexistent"', out)
        self.assertIn('known tags', out)

    def test_new_then_list(self):
        self._team('new custom my team')
        out = self._team()
        self.assertIn('custom', out)

    def test_show(self):
        self._team('new custom doc team')
        out = self._team('show custom')
        self.assertIn('doc team', out)
        self.assertIn('stages: (none)', out)

    def test_show_stages(self):
        self._seed()
        out = self._team('show writing')
        self.assertIn('1. researcher', out)
        self.assertIn('task_hint:', out)
        self.assertIn('handoff_note:', out)

    def test_new_overrides_existing(self):
        self._team('new x one')
        out = self._team('new x two')
        self.assertIn('Overrode team: x', out)
        out = self._team('show x')
        self.assertIn('two', out)

    def test_remove_local(self):
        self._team('new x')
        out = self._team('remove x')
        self.assertIn('Removed team: x', out)

    def test_remove_unknown(self):
        out = self._team('remove writing')
        self.assertIn('No local team to remove: writing', out)

    def test_override_then_remove(self):
        self._seed()
        self._team('new writing local variant')
        out = self._team('show writing')
        self.assertIn('local variant', out)
        out = self._team('remove writing')
        self.assertIn('Removed team: writing', out)
        out = self._team('show writing')
        self.assertIn('Team not found', out)


if __name__ == '__main__':
    unittest.main()