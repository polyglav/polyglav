import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from polyglav.skills import Skill, SkillRegistry
from polyglav.config import Config

from tests.helpers import make_chat


class StubPluginManager:
    def __init__(self, entries):
        self.entries = entries

    def register_skills(self, registry):
        for entry in self.entries:
            registry.add_plugin(entry)


class TestSkillRegistry(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.local = self.base / 'proj' / '.polyglav' / 'skills'

    def tearDown(self):
        self.tmp.cleanup()

    def reg(self, global_dir=None, local_dir=None):
        return SkillRegistry(global_dir=global_dir or self.base,
                             local_dir=local_dir or self.local)

    def test_paths(self):
        reg = self.reg()
        self.assertEqual(reg.global_dir,
                         self.base / '.config' / 'polyglav' / 'skills')
        self.assertEqual(reg.local_dir, self.local)

    def test_empty(self):
        self.assertEqual(self.reg().all(), [])
        self.assertEqual(self.reg().names(), [])

    def test_put_local_and_find(self):
        reg = self.reg()
        reg.put(Skill(name='writers', content='Produce clean prose.'))
        s = reg.find('writers')
        self.assertIsNotNone(s)
        self.assertEqual(s.content, 'Produce clean prose.')
        self.assertEqual(s.description, 'Produce clean prose.')
        self.assertEqual(reg.origin('writers'), 'local')
        self.assertIn('writers', reg.names())

    def test_put_creates_file_roundtrip(self):
        reg = self.reg()
        reg.put(Skill(name='x', content='first'), scope='local')
        path = self.local / 'x.md'
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), 'first')
        fresh = self.reg()
        self.assertEqual(fresh.find('x').content, 'first')

    def test_put_global_creates_global_file(self):
        reg = self.reg()
        reg.put(Skill(name='x', content='global'), scope='global')
        self.assertTrue((self.base / '.config' / 'polyglav' / 'skills'
                         / 'x.md').exists())
        self.assertFalse((self.local / 'x.md').exists())

    def test_scan_reads_existing_files(self):
        self.local.mkdir(parents=True)
        (self.local / 'a.md').write_text('first skill')
        (self.local / 'b.md').write_text('second skill')
        reg = self.reg()
        self.assertEqual(reg.names(), ['a', 'b'])
        self.assertEqual(reg.find('b').content, 'second skill')

    def test_global_and_local_merge_local_wins(self):
        reg = self.reg()
        reg.put(Skill(name='x', content='global version'), scope='global')
        reg.put(Skill(name='x', content='local version'), scope='local')
        self.assertEqual(reg.find('x').content, 'local version')
        self.assertEqual(reg.origin('x'), 'merged')

    def test_remove_local(self):
        reg = self.reg()
        reg.put(Skill(name='x', content='c'))
        self.assertTrue(reg.remove('x'))
        self.assertIsNone(reg.find('x'))
        self.assertFalse(reg.remove('x'))

    def test_all_sorted_by_name(self):
        reg = self.reg()
        reg.put(Skill(name='z', content=''))
        reg.put(Skill(name='a', content=''))
        self.assertEqual([s.name for s in reg.all()], ['a', 'z'])
        self.assertEqual(reg.names(), ['a', 'z'])

    def test_default_uses_config_global_dir(self):
        prev = Config.GLOBAL_DIR
        Config.GLOBAL_DIR = self.base
        try:
            reg = SkillRegistry(local_dir=self.local)
            self.assertEqual(reg.global_dir,
                             self.base / '.config' / 'polyglav' / 'skills')
        finally:
            Config.GLOBAL_DIR = prev

    def test_add_plugin_skill(self):
        reg = self.reg()
        reg.add_plugin({'name': 'plug', 'content': '# Plug\n\nBody.',
                        'description': 'd', 'tags': ['t']})
        s = reg.find('plug')
        self.assertIsNotNone(s)
        self.assertIn('Body', s.content)
        self.assertEqual(s.description, 'd')
        self.assertEqual(s.tags, ['t'])
        self.assertEqual(reg.origin('plug'), 'plugin')
        self.assertIn('plug', reg.names())

    def test_add_plugin_invalid_entry_ignored(self):
        reg = self.reg()
        reg.add_plugin({'content': 'no name'})
        reg.add_plugin('nope')
        self.assertEqual(reg.all(), [])

    def test_add_plugin_writes_nothing_to_disk(self):
        reg = self.reg()
        reg.add_plugin({'name': 'plug', 'content': 'x'})
        self.assertFalse(self.local.exists())
        self.assertFalse((self.base / '.config' / 'polyglav' / 'skills').exists())

    def test_global_overrides_plugin(self):
        reg = self.reg()
        reg.add_plugin({'name': 'x', 'content': 'plugin version'})
        reg.put(Skill(name='x', content='global version'), scope='global')
        self.assertEqual(reg.find('x').content, 'global version')
        self.assertEqual(reg.origin('x'), 'merged')
        reg.remove('x', scope='global')
        self.assertEqual(reg.find('x').content, 'plugin version')

    def test_local_overrides_plugin(self):
        reg = self.reg()
        reg.add_plugin({'name': 'x', 'content': 'plugin version'})
        reg.put(Skill(name='x', content='local version'), scope='local')
        self.assertEqual(reg.find('x').content, 'local version')
        self.assertEqual(reg.origin('x'), 'merged')

    def test_reload_rereads_disk(self):
        reg = self.reg()
        self.local.mkdir(parents=True)
        (self.local / 'x.md').write_text('on disk')
        reg.reload()
        self.assertEqual(reg.find('x').content, 'on disk')

    def test_reload_reapplies_plugin_contributions(self):
        reg = self.reg()
        reg.reload(StubPluginManager(
            [{'name': 'old', 'content': 'o'}]))
        self.assertIsNotNone(reg.find('old'))
        reg.reload(StubPluginManager(
            [{'name': 'new', 'content': 'n'}]))
        self.assertIsNone(reg.find('old'))
        self.assertIsNotNone(reg.find('new'))

    def test_reload_without_plugin_manager_clears_plugin_scope(self):
        reg = self.reg()
        reg.add_plugin({'name': 'plug', 'content': 'x'})
        reg.reload()
        self.assertIsNone(reg.find('plug'))


class TestSkillsSection(unittest.TestCase):

    def test_empty_when_no_names(self):
        from polyglav.skills import skills_section
        tmp = Path(tempfile.mkdtemp())
        reg = SkillRegistry(global_dir=tmp, local_dir=tmp / 'skills')
        self.assertEqual(skills_section(reg, []), '')

    def test_returns_empty_for_missing_skills(self):
        reg = SkillRegistry(global_dir=Path(tempfile.mkdtemp()),
                            local_dir=Path(tempfile.mkdtemp()))
        from polyglav.skills import skills_section
        self.assertEqual(skills_section(reg, ['nope']), '')

    def test_composes_section(self):
        from polyglav.skills import skills_section
        tmp = Path(tempfile.mkdtemp())
        reg = SkillRegistry(global_dir=tmp, local_dir=tmp / 'skills')
        reg.put(Skill(name='writers', content='Produce clean prose.'))
        reg.put(Skill(name='editors', content='Check consistency.'))
        section = skills_section(reg, ['writers', 'editors', 'nope'])
        self.assertIn('## Skills', section)
        self.assertIn('### writers', section)
        self.assertIn('Produce clean prose.', section)
        self.assertIn('### editors', section)
        self.assertNotIn('nope', section)


class TestSkillCommand(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()
        self.tmp.cleanup()

    def _skill(self, arg=''):
        with patch('sys.stdout', new=io.StringIO()) as buf:
            self.chat.registry.dispatch('/skills ' + arg)
        return buf.getvalue()

    def test_list_empty(self):
        out = self._skill()
        self.assertIn('no skills configured', out)

    def test_new_then_list_show(self):
        self._skill('new writers')
        out = self._skill('list')
        self.assertIn('writers', out)
        self.assertIn('(local)', out)
        out = self._skill('show writers')
        self.assertIn('writers (local)', out)
        self.assertIn('(empty)', out)

    def test_show_renders_content(self):
        self.chat.skills.put(Skill(name='x', content='# X\n\nBody text.'))
        out = self._skill('show x')
        self.assertIn('# X', out)
        self.assertIn('Body text.', out)

    def test_new_overrides(self):
        self._skill('new x')
        out = self._skill('new x')
        self.assertIn('Overrode skill: x', out)

    def test_remove_local(self):
        self._skill('new x')
        out = self._skill('remove x')
        self.assertIn('Removed skill: x', out)

    def test_remove_plugin_skill_rejected(self):
        self.chat.skills.add_plugin({'name': 'plug', 'content': 'x'})
        out = self._skill('remove plug')
        self.assertIn('comes from a plugin', out)
        self.assertIsNotNone(self.chat.skills.find('plug'))

    def test_remove_missing(self):
        out = self._skill('remove nosuch')
        self.assertIn('No local skill to remove', out)


if __name__ == '__main__':
    unittest.main()