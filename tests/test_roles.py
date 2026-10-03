import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from polyglav import roles as roles_mod
from polyglav.roles import Role, RoleRegistry
from polyglav.config import Config

from tests.helpers import make_chat

BUNDLED = Path(roles_mod.__file__).with_name(
    RoleRegistry.BUNDLED_FILENAME)


class StubPluginManager:
    def __init__(self, entries):
        self.entries = entries

    def register_roles(self, registry):
        for entry in self.entries:
            registry.add_plugin(entry)


class TestRoleRegistry(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.local = self.base / 'proj' / '.polyglav' / 'roles.json'

    def tearDown(self):
        self.tmp.cleanup()

    def reg(self, global_dir=None, local_path=None, bundled_path=None):
        if bundled_path is None:
            bundled_path = self.base / 'nobundled' / 'roles.json'
        return RoleRegistry(global_dir=global_dir or self.base,
                            local_path=local_path or self.local,
                            bundled_path=bundled_path)

    def bundled(self, local_path=None):
        return RoleRegistry(global_dir=self.base,
                            local_path=local_path or self.local,
                            bundled_path=BUNDLED)

    def test_paths(self):
        reg = self.reg()
        self.assertEqual(reg.global_path,
                         self.base / '.config' / 'polyglav' / 'roles.json')
        self.assertEqual(reg.local_path, self.local)

    def test_empty(self):
        self.assertEqual(self.reg().all(), [])
        self.assertEqual(self.reg().names(), [])

    def test_put_local_and_find(self):
        reg = self.reg()
        reg.put(Role(name='researcher', system_prompt='Search the web.'))
        p = reg.find('researcher')
        self.assertIsNotNone(p)
        self.assertEqual(p.system_prompt, 'Search the web.')
        self.assertEqual(reg.origin('researcher'), 'local')

    def test_put_fields_roundtrip(self):
        reg = self.reg()
        reg.put(Role(name='writer', model='deepseek-r1',
                         skills=['writers'],
                         tool_permission={'delegate': 'ask'}))
        p = reg.find('writer')
        self.assertEqual(p.model, 'deepseek-r1')
        self.assertEqual(p.skills, ['writers'])
        self.assertEqual(p.tool_permission, {'delegate': 'ask'})

    def test_global_and_local_merge_local_wins(self):
        g = RoleRegistry(global_dir=self.base,
                         local_path=Path(self.tmp.name) / 'g' / 't.json')
        g.put(Role(name='x', system_prompt='global prompt', model='m1'),
              scope='global')
        reg = self.reg()
        reg.put(Role(name='x', system_prompt='local prompt'), scope='local')
        p = reg.find('x')
        self.assertEqual(p.system_prompt, 'local prompt')
        self.assertEqual(p.model, 'm1')
        self.assertEqual(reg.origin('x'), 'merged')

    def test_local_only_does_not_add_to_global(self):
        reg = self.reg()
        reg.put(Role(name='only-local'), scope='local')
        fresh = RoleRegistry(global_dir=self.base,
                             local_path=Path(self.tmp.name) / 'z' / 't.json')
        self.assertIsNone(fresh.find('only-local'))

    def test_remove_local(self):
        reg = self.reg()
        reg.put(Role(name='x'))
        self.assertTrue(reg.remove('x'))
        self.assertIsNone(reg.find('x'))
        self.assertFalse(reg.remove('x'))

    def test_reload_from_disk(self):
        self.reg().put(Role(name='x', system_prompt='p'))
        reg2 = self.reg()
        self.assertEqual(reg2.find('x').system_prompt, 'p')

    def test_all_sorted_by_name(self):
        reg = self.reg()
        reg.put(Role(name='z'))
        reg.put(Role(name='a'))
        self.assertEqual([p.name for p in reg.all()], ['a', 'z'])
        self.assertEqual(reg.names(), ['a', 'z'])

    def test_default_uses_config_global_dir(self):
        prev = Config.GLOBAL_DIR
        Config.GLOBAL_DIR = self.base
        try:
            reg = RoleRegistry(local_path=self.local)
            self.assertEqual(reg.global_path,
                             self.base / '.config' / 'polyglav' / 'roles.json')
        finally:
            Config.GLOBAL_DIR = prev

    def test_bad_json_ignored(self):
        self.local.parent.mkdir(parents=True, exist_ok=True)
        self.local.write_text('{invalid')
        self.assertEqual(self.reg().all(), [])

    def test_bundled_defaults_loaded(self):
        reg = self.bundled()
        names = reg.names()
        self.assertEqual(len(names), 10)
        for expected in ('composer', 'leader', 'researcher',
                         'writer', 'referencer', 'editor', 'planner',
                         'programmer', 'tester', 'code-reviewer'):
            self.assertIn(expected, names)
        self.assertEqual(reg.origin('researcher'), 'bundled')
        researcher = reg.find('researcher')
        self.assertEqual(researcher.tool_permission['edit'], 'deny')
        self.assertEqual(researcher.tool_permission['web'], 'allow')
        self.assertEqual(reg.find('programmer').tool_permission['bash'], 'allow')
        self.assertEqual(reg.find('editor').tool_permission['edit'], 'deny')
        composer = reg.find('composer')
        self.assertEqual(composer.tool_permission['catalog'], 'allow')
        self.assertEqual(composer.tool_permission['edit'], 'deny')
        self.assertEqual(composer.tool_permission['delegate'], 'deny')
        leader = reg.find('leader')
        self.assertEqual(leader.tool_permission['edit'], 'deny')
        self.assertEqual(leader.tool_permission['bash'], 'deny')
        self.assertEqual(leader.grant_permission['edit'], 'allow')
        self.assertEqual(leader.grant_permission['bash'], 'allow')

    def test_bundled_tags(self):
        reg = self.bundled()
        self.assertEqual(reg.find('researcher').tags, ['research', 'writing'])
        self.assertEqual(reg.find('writer').tags, ['writing'])
        self.assertEqual(reg.find('editor').tags, ['writing', 'review'])
        self.assertEqual(reg.find('code-reviewer').tags,
                         ['programming', 'review'])
        self.assertEqual(reg.find('programmer').tags, ['programming'])

    def test_tags_roundtrip(self):
        reg = self.reg()
        reg.put(Role(name='x', tags=['writing', 'review']))
        p = reg.find('x')
        self.assertEqual(p.tags, ['writing', 'review'])

    def test_tags_merge_local_replaces_bundled(self):
        reg = self.bundled()
        reg.put(Role(name='researcher', tags=['custom']), scope='local')
        p = reg.find('researcher')
        self.assertEqual(p.tags, ['custom'])
        self.assertEqual(reg.origin('researcher'), 'merged')
        self.assertTrue(reg.remove('researcher'))
        self.assertEqual(reg.find('researcher').tags, ['research', 'writing'])

    def test_bundled_overridden_by_global_and_local(self):
        reg = self.bundled()
        reg.put(Role(name='researcher', system_prompt='global variant'),
                scope='global')
        p = reg.find('researcher')
        self.assertEqual(p.system_prompt, 'global variant')
        self.assertEqual(p.tool_permission['edit'], 'deny')
        self.assertEqual(reg.origin('researcher'), 'merged')
        reg.put(Role(name='researcher', system_prompt='local variant'),
                scope='local')
        self.assertEqual(reg.find('researcher').system_prompt, 'local variant')

    def test_bundled_restored_after_override_removed(self):
        reg = self.bundled()
        bundled_prompt = reg.find('researcher').system_prompt
        reg.put(Role(name='researcher', system_prompt='mine'), scope='local')
        self.assertEqual(reg.find('researcher').system_prompt, 'mine')
        self.assertTrue(reg.remove('researcher'))
        p = reg.find('researcher')
        self.assertEqual(p.system_prompt, bundled_prompt)
        self.assertEqual(reg.origin('researcher'), 'bundled')

    def test_add_plugin_type(self):
        reg = self.reg()
        reg.add_plugin({'name': 'helper', 'system_prompt': 'from a plugin',
                        'tags': ['plugin']})
        p = reg.find('helper')
        self.assertIsNotNone(p)
        self.assertEqual(p.system_prompt, 'from a plugin')
        self.assertEqual(p.tags, ['plugin'])
        self.assertEqual(reg.origin('helper'), 'plugin')
        self.assertIn('helper', reg.names())

    def test_add_plugin_invalid_entry_ignored(self):
        reg = self.reg()
        reg.add_plugin({'system_prompt': 'no name'})
        reg.add_plugin('nope')
        self.assertEqual(reg.all(), [])

    def test_add_plugin_writes_nothing_to_disk(self):
        reg = self.reg()
        reg.add_plugin({'name': 'helper', 'system_prompt': 'x'})
        self.assertFalse(self.local.exists())
        reg.put(Role(name='mine', system_prompt='p'), scope='local')
        import json as _json
        saved = _json.loads(self.local.read_text())
        self.assertEqual(list(saved), ['mine'])

    def test_plugin_overrides_bundled(self):
        reg = self.bundled()
        reg.add_plugin({'name': 'researcher', 'system_prompt': 'plugin variant'})
        p = reg.find('researcher')
        self.assertEqual(p.system_prompt, 'plugin variant')
        self.assertEqual(p.tool_permission['edit'], 'deny')
        self.assertEqual(reg.origin('researcher'), 'merged')

    def test_global_overrides_plugin(self):
        reg = self.reg()
        reg.add_plugin({'name': 'x', 'system_prompt': 'plugin prompt'})
        reg.put(Role(name='x', system_prompt='global prompt'), scope='global')
        self.assertEqual(reg.find('x').system_prompt, 'global prompt')
        self.assertEqual(reg.origin('x'), 'merged')
        reg.remove('x', scope='global')
        self.assertEqual(reg.find('x').system_prompt, 'plugin prompt')

    def test_local_overrides_plugin(self):
        reg = self.reg()
        reg.add_plugin({'name': 'x', 'system_prompt': 'plugin prompt'})
        reg.put(Role(name='x', system_prompt='local prompt'), scope='local')
        self.assertEqual(reg.find('x').system_prompt, 'local prompt')
        self.assertEqual(reg.origin('x'), 'merged')

    def test_reload_rereads_disk(self):
        reg = self.reg()
        self.local.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        self.local.write_text(_json.dumps(
            {'x': {'name': 'x', 'system_prompt': 'on disk'}}))
        reg.reload()
        self.assertEqual(reg.find('x').system_prompt, 'on disk')

    def test_reload_rereads_global_and_bundled(self):
        reg = self.bundled()
        self.assertIsNone(reg.find('x'))
        reg.global_path.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        reg.global_path.write_text(_json.dumps(
            {'x': {'name': 'x', 'system_prompt': 'global'}}))
        reg.reload()
        self.assertEqual(reg.find('x').system_prompt, 'global')
        self.assertIsNotNone(reg.find('researcher'))

    def test_reload_reapplies_plugin_contributions(self):
        reg = self.reg()
        reg.reload(StubPluginManager([{'name': 'old', 'system_prompt': 'o'}]))
        self.assertIsNotNone(reg.find('old'))
        reg.reload(StubPluginManager([{'name': 'new', 'system_prompt': 'n'}]))
        self.assertIsNone(reg.find('old'))
        self.assertIsNotNone(reg.find('new'))

    def test_reload_without_plugin_manager_clears_plugin_scope(self):
        reg = self.reg()
        reg.add_plugin({'name': 'helper', 'system_prompt': 'x'})
        reg.reload()
        self.assertIsNone(reg.find('helper'))


class TestTypeCommand(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()
        self.tmp.cleanup()

    def _type(self, arg=''):
        with patch('sys.stdout', new=io.StringIO()) as buf:
            self.chat.registry.dispatch('/roles ' + arg)
        return buf.getvalue()

    def test_list_shows_bundled(self):
        out = self._type()
        self.assertIn('10 roles', out)
        self.assertIn('researcher', out)
        self.assertIn('(bundled)', out)

    def test_role_shows_active_role(self):
        self.chat.role = 'leader'
        with patch('sys.stdout', new=io.StringIO()) as buf:
            self.chat.registry.dispatch('/role')
        self.assertIn('Role: leader', buf.getvalue())

    def test_list_shows_tags(self):
        out = self._type()
        self.assertIn('tags=research,writing', out)
        self.assertIn('tags=programming', out)

    def test_list_filter_by_tag(self):
        out = self._type('list programming')
        self.assertIn('programmer', out)
        self.assertIn('code-reviewer', out)
        self.assertNotIn('researcher ', out)
        out = self._type('list review')
        self.assertIn('editor', out)
        self.assertIn('code-reviewer', out)

    def test_list_unknown_tag(self):
        out = self._type('list nonexistent')
        self.assertIn('no roles tagged "nonexistent"', out)
        self.assertIn('known tags', out)

    def test_new_then_list(self):
        self._type('new custom')
        out = self._type()
        self.assertIn('custom', out)

    def test_show(self):
        self._type('new researcher Web search agent')
        out = self._type('show researcher')
        self.assertIn('Web search agent', out)

    def test_new_overrides_existing(self):
        self._type('new x one')
        out = self._type('new x two')
        self.assertIn('Overrode role: x', out)
        out = self._type('show x')
        self.assertIn('two', out)

    def test_remove_local(self):
        self._type('new x')
        out = self._type('remove x')
        self.assertIn('Removed role: x', out)

    def test_remove_bundled_rejected(self):
        out = self._type('remove researcher')
        self.assertIn('bundled with polyglav', out)

    def test_override_bundled_then_remove(self):
        self._type('new researcher local text')
        out = self._type('show researcher')
        self.assertIn('local text', out)
        out = self._type('remove researcher')
        self.assertIn('Removed role: researcher', out)


if __name__ == '__main__':
    unittest.main()