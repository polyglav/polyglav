import json
import tempfile
import unittest
from pathlib import Path

from polyglav.roles import Role, RoleRegistry, parse_frontmatter


class TestRoleFiles(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.local = self.base / 'proj' / '.polyglav' / 'roles.json'
        self.roles_dir = self.base / 'proj' / '.polyglav' / 'roles'

    def tearDown(self):
        self.tmp.cleanup()

    def reg(self):
        return RoleRegistry(global_dir=self.base, local_path=self.local)

    def _write_index(self, entries):
        self.local.parent.mkdir(parents=True, exist_ok=True)
        self.local.write_text(json.dumps(entries))

    def _write_md(self, name, text):
        self.roles_dir.mkdir(parents=True, exist_ok=True)
        (self.roles_dir / name).write_text(text)

    def test_parse_frontmatter(self):
        meta, body = parse_frontmatter(
            '---\nmodel: m1\ntags: ["a", "b"]\n---\n\nBody text\n')
        self.assertEqual(meta, {'model': 'm1', 'tags': ['a', 'b']})
        self.assertEqual(body, 'Body text')

    def test_parse_frontmatter_absent(self):
        meta, body = parse_frontmatter('Just a prompt.\n')
        self.assertEqual(meta, {})
        self.assertEqual(body, 'Just a prompt.\n')

    def test_markdown_body_is_prompt(self):
        self._write_index({'writer': {'name': 'writer'}})
        self._write_md('writer.md', 'You are the writer.\n')
        role = self.reg().find('writer')
        self.assertEqual(role.system_prompt, 'You are the writer.')

    def test_json_prompt_wins_over_markdown(self):
        self._write_index({'writer': {'name': 'writer',
                                      'system_prompt': 'json prompt'}})
        self._write_md('writer.md', 'markdown prompt\n')
        self.assertEqual(self.reg().find('writer').system_prompt, 'json prompt')

    def test_frontmatter_fills_missing_fields(self):
        self._write_index({'writer': {'name': 'writer'}})
        self._write_md('writer.md',
                       '---\nmodel: deepseek\ntags: ["writing"]\n---\n'
                       'Body prompt\n')
        role = self.reg().find('writer')
        self.assertEqual(role.model, 'deepseek')
        self.assertEqual(role.tags, ['writing'])
        self.assertEqual(role.system_prompt, 'Body prompt')

    def test_json_wins_frontmatter(self):
        self._write_index({'writer': {'name': 'writer', 'model': 'json-model'}})
        self._write_md('writer.md', '---\nmodel: md-model\n---\nBody\n')
        self.assertEqual(self.reg().find('writer').model, 'json-model')

    def test_explicit_instructions_reference(self):
        self._write_index({'writer': {'name': 'writer',
                                      'instructions': 'custom.md'}})
        self._write_md('custom.md', 'Custom prompt.\n')
        self.assertEqual(self.reg().find('writer').system_prompt,
                         'Custom prompt.')

    def test_instructions_path_traversal_ignored(self):
        self._write_index({'writer': {'name': 'writer',
                                      'instructions': '../secret.md'}})
        (self.local.parent / 'secret.md').write_text('secret')
        self.assertEqual(self.reg().find('writer').system_prompt, '')

    def test_put_writes_index_and_markdown(self):
        reg = self.reg()
        reg.put(Role(name='writer', system_prompt='Long detailed prompt.',
                     description='writes'))
        index = json.loads(self.local.read_text())
        self.assertEqual(index['writer']['instructions'], 'writer.md')
        self.assertNotIn('system_prompt', index['writer'])
        self.assertEqual(index['writer']['description'], 'writes')
        self.assertEqual((self.roles_dir / 'writer.md').read_text(),
                         'Long detailed prompt.\n')
        self.assertEqual(reg.find('writer').system_prompt,
                         'Long detailed prompt.')

    def test_remove_deletes_markdown(self):
        reg = self.reg()
        reg.put(Role(name='writer', system_prompt='p'))
        self.assertTrue((self.roles_dir / 'writer.md').exists())
        self.assertTrue(reg.remove('writer'))
        self.assertFalse((self.roles_dir / 'writer.md').exists())


if __name__ == '__main__':
    unittest.main()
