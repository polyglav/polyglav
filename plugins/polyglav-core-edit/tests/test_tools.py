import importlib.util
import sys
import unittest
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polyglav.tools.registry import ToolRegistry


def _load_plugin(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


edit_plugin = _load_plugin('polyglav_edit_plugin', SRC / 'plugin.py')


class TestEditTool(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.registry = ToolRegistry()
        edit_plugin.register_tools(self.registry)

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, name, **args):
        return self.registry.execute(name, args)

    def test_edit_replaces_first_occurrence(self):
        p = self.root / 'a.txt'
        p.write_text('one two one two\n')
        out = self.run_tool('file_edit', path=str(p), old='one', new='ONE')
        self.assertIn('Edited', out)
        self.assertIn('1 of 2 occurrences', out)
        self.assertEqual(p.read_text(), 'ONE two one two\n')

    def test_edit_replace_all(self):
        p = self.root / 'a.txt'
        p.write_text('one two one two\n')
        self.run_tool('file_edit', path=str(p), old='one', new='ONE', count=0)
        self.assertEqual(p.read_text(), 'ONE two ONE two\n')

    def test_edit_count_limits(self):
        p = self.root / 'a.txt'
        p.write_text('a a a\n')
        self.run_tool('file_edit', path=str(p), old='a', new='b', count=2)
        self.assertEqual(p.read_text(), 'b b a\n')

    def test_edit_delete_old(self):
        p = self.root / 'a.txt'
        p.write_text('hello world\n')
        self.run_tool('file_edit', path=str(p), old=' world', new='')
        self.assertEqual(p.read_text(), 'hello\n')

    def test_edit_missing_file(self):
        out = self.run_tool('file_edit', path=str(self.root / 'nope.txt'),
                            old='x', new='y')
        self.assertIn('not found', out)

    def test_edit_is_directory(self):
        out = self.run_tool('file_edit', path=str(self.root), old='x', new='y')
        self.assertIn('directory', out)

    def test_edit_old_not_found(self):
        p = self.root / 'a.txt'
        p.write_text('hello\n')
        out = self.run_tool('file_edit', path=str(p), old='zzz', new='y')
        self.assertIn('not found', out)
        self.assertEqual(p.read_text(), 'hello\n')

    def test_edit_empty_old(self):
        p = self.root / 'a.txt'
        p.write_text('hello\n')
        out = self.run_tool('file_edit', path=str(p), old='', new='y')
        self.assertIn('must not be empty', out)
        self.assertEqual(p.read_text(), 'hello\n')

    def test_edit_creates_no_parents(self):
        p = self.root / 'nope' / 'a.txt'
        out = self.run_tool('file_edit', path=str(p), old='x', new='y')
        self.assertIn('not found', out)

    def test_edit_alias_and_param_aliases(self):
        p = self.root / 'a.txt'
        p.write_text('one\n')
        self.assertTrue(self.registry.is_registered('edit'))
        out = self.run_tool('edit', file=str(p), old_text='one', new_text='two')
        self.assertIn('Edited', out)
        self.assertEqual(p.read_text(), 'two\n')

    def test_metadata_registered(self):
        self.assertEqual(self.registry.permission_for('file_edit'), 'edit')
        self.assertEqual(self.registry.path_arg_for('file_edit'), 'path')
        self.assertEqual(self.registry.key_arg_for('file_edit'), 'path')

    def test_edit_status_preview_diff(self):
        p = self.root / 'edit.md'
        p.write_text('old line\n')
        value, body = self.registry.status_parts(
            'file_edit', {'path': str(p), 'old': 'old', 'new': 'new'})
        self.assertEqual(value, str(p))
        self.assertIn('-old line', body)
        self.assertIn('+new line', body)
        self.assertEqual(body[-1],
                         f'({p.resolve()} - replacing 1 of 1 occurrences)')

    def test_edit_status_no_match(self):
        p = self.root / 'edit.md'
        p.write_text('old line\n')
        value, body = self.registry.status_parts(
            'file_edit', {'path': str(p), 'old': 'zzz', 'new': 'new'})
        self.assertEqual(value, f'{p} (no match for old text)')
        self.assertEqual(body, [])


if __name__ == '__main__':
    unittest.main()