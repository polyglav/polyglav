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


fs_plugin = _load_plugin('polyglav_fs_plugin', SRC / 'plugin.py')


class _Cfg:
    def __init__(self, **kw):
        self.data = kw

    def get(self, key, default=None):
        return self.data.get(key, default)


class TestFsTools(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.registry = ToolRegistry()
        fs_plugin.register_tools(self.registry)

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, name, **args):
        return self.registry.execute(name, args)

    def run_tool_cfg(self, name, config, **args):
        return self.registry.execute(name, args, config=config)

    def test_read_file_numbered(self):
        (self.root / 'a.txt').write_text('one\ntwo\nthree\n')
        out = self.run_tool('read_file', path=str(self.root / 'a.txt'))
        self.assertIn('1|one', out)
        self.assertIn('3|three', out)

    def test_read_file_offset_limit(self):
        (self.root / 'a.txt').write_text('\n'.join(f'line{i}' for i in range(1, 21)))
        out = self.run_tool('read_file', path=str(self.root / 'a.txt'), offset=5, limit=3)
        self.assertIn('5|line5', out)
        self.assertIn('7|line7', out)
        self.assertNotIn('line8', out)
        self.assertIn('20 lines', out)
        self.assertIn('(showing 5-7)', out)

    def test_read_file_header_reports_total(self):
        (self.root / 'a.txt').write_text('one\ntwo\nthree\n')
        out = self.run_tool('read_file', path=str(self.root / 'a.txt'))
        self.assertIn('3 lines', out)
        self.assertIn('14 chars', out)
        self.assertNotIn('(showing', out)
        self.assertIn('1|one', out)
        self.assertIn('3|three', out)

    def test_read_file_limit_zero_returns_header_probe(self):
        (self.root / 'a.txt').write_text('one\ntwo\nthree\n')
        out = self.run_tool('read_file', path=str(self.root / 'a.txt'), limit=0)
        self.assertIn('3 lines', out)
        self.assertIn('14 chars', out)
        self.assertNotIn('1|one', out)
        self.assertNotIn('... (truncated)', out)

    def test_read_file_unlimited_default_no_truncation(self):
        content = '\n'.join(f'line{i} line{i} line{i} line{i} line{i}'
                            for i in range(1, 201))
        (self.root / 'big.txt').write_text(content)
        out = self.run_tool('read_file', path=str(self.root / 'big.txt'))
        self.assertIn(f'{len(content)} chars', out)
        self.assertNotIn('... (truncated)', out)
        self.assertIn('200|', out)

    def test_read_file_cap_truncates(self):
        content = '\n'.join(f'line{i} line{i} line{i} line{i} line{i}'
                            for i in range(1, 201))
        (self.root / 'big.txt').write_text(content)
        out = self.run_tool_cfg('read_file', _Cfg(tool_max_result_chars=1000),
                                path=str(self.root / 'big.txt'))
        self.assertIn('... (truncated)', out)
        self.assertNotIn('200|', out)

    def test_read_file_default_cap_boundary(self):
        (self.root / 'huge.txt').write_text('x' * 150000)
        out = self.run_tool_cfg('read_file',
                                _Cfg(tool_max_result_chars=100000),
                                path=str(self.root / 'huge.txt'))
        self.assertIn('... (truncated)', out)

    def test_read_file_missing(self):
        out = self.run_tool('read_file', path=str(self.root / 'nope.txt'))
        self.assertIn('not found', out)

    def test_read_file_is_directory(self):
        out = self.run_tool('read_file', path=str(self.root))
        self.assertIn('directory', out)

    def test_list_dir(self):
        (self.root / 'b.txt').write_text('x')
        (self.root / 'sub').mkdir()
        out = self.run_tool('list_dir', path=str(self.root))
        self.assertIn('b.txt', out)
        self.assertIn('sub/', out)

    def test_list_dir_empty(self):
        out = self.run_tool('list_dir', path=str(self.root))
        self.assertIn('(empty directory)', out)

    def test_list_dir_missing(self):
        out = self.run_tool('list_dir', path=str(self.root / 'nope'))
        self.assertIn('not found', out)

    def test_list_dir_depth_recursive(self):
        (self.root / 'src' / 'deep').mkdir(parents=True)
        (self.root / 'src' / 'mod.py').write_text('x')
        (self.root / 'src' / 'deep' / 'leaf.py').write_text('y')
        out = self.run_tool('list_dir', path=str(self.root), depth=3)
        self.assertIn('src/', out)
        self.assertIn('  mod.py', out)
        self.assertIn('  deep/', out)
        self.assertIn('    leaf.py', out)

    def test_list_dir_depth_two_stops_below(self):
        (self.root / 'src' / 'deep').mkdir(parents=True)
        (self.root / 'src' / 'deep' / 'leaf.py').write_text('y')
        out = self.run_tool('list_dir', path=str(self.root), depth=2)
        self.assertIn('src/', out)
        self.assertIn('  deep/', out)
        self.assertNotIn('leaf.py', out)

    def test_list_dir_depth_skips_noise_dirs(self):
        (self.root / '.venv').mkdir()
        (self.root / '.venv' / 'lib.py').write_text('y')
        (self.root / 'a.txt').write_text('x')
        out = self.run_tool('list_dir', path=str(self.root), depth=3)
        self.assertIn('.venv/', out)
        self.assertNotIn('lib.py', out)
        self.assertIn('a.txt', out)

    def test_list_dir_depth_one_matches_flat(self):
        (self.root / 'b.txt').write_text('x')
        (self.root / 'sub').mkdir()
        flat = self.run_tool('list_dir', path=str(self.root))
        explicit = self.run_tool('list_dir', path=str(self.root), depth=1)
        self.assertEqual(flat, explicit)

    def test_list_dir_entry_cap(self):
        for i in range(250):
            (self.root / f'f{i:03d}.txt').write_text('x')
        out = self.run_tool_cfg('list_dir', _Cfg(list_dir_max_entries=200),
                                path=str(self.root))
        self.assertIn('... (showing first 200 of 250 entries)', out)
        for i in range(200):
            self.assertIn(f'f{i:03d}.txt', out)
        self.assertNotIn('f200.txt', out)

    def test_list_dir_entry_cap_zero_is_unlimited(self):
        for i in range(250):
            (self.root / f'f{i:03d}.txt').write_text('x')
        out = self.run_tool_cfg('list_dir', _Cfg(list_dir_max_entries=0),
                                path=str(self.root))
        self.assertIn('f249.txt', out)
        self.assertNotIn('showing first', out)

    def test_list_dir_no_config_is_unlimited(self):
        for i in range(250):
            (self.root / f'f{i:03d}.txt').write_text('x')
        out = self.run_tool('list_dir', path=str(self.root))
        self.assertIn('f249.txt', out)
        self.assertNotIn('showing first', out)

    def test_write_file_creates(self):
        target = self.root / 'new.txt'
        out = self.run_tool('write_file', path=str(target), content='hello')
        self.assertIn(f'Created {target.resolve()} (1 lines, 5 chars)', out)
        self.assertEqual(target.read_text(), 'hello')

    def test_write_file_overwrites(self):
        target = self.root / 'new.txt'
        target.write_text('old')
        out = self.run_tool('write_file', path=str(target), content='new')
        self.assertIn(f'Overwritten {target.resolve()} (1 lines, 3 chars)', out)
        self.assertEqual(target.read_text(), 'new')

    def test_write_file_creates_parents(self):
        self.run_tool('write_file', path=str(self.root / 'deep' / 'dir' / 'f.txt'), content='x')
        self.assertTrue((self.root / 'deep' / 'dir' / 'f.txt').exists())

    def test_write_file_append(self):
        target = self.root / 'f.txt'
        target.write_text('a')
        out = self.run_tool('write_file', path=str(target), content='b', mode='a')
        self.assertIn(f'Appended {target.resolve()} (1 lines, 1 chars)', out)
        self.assertEqual(target.read_text(), 'ab')

    def test_write_file_relative_path_reports_resolved(self):
        with tempfile.TemporaryDirectory() as d:
            orig = Path.cwd()
            try:
                import os
                os.chdir(d)
                out = self.run_tool('write_file', path='rel.txt', content='x')
                resolved = (Path(d) / 'rel.txt').resolve()
                self.assertIn(f'Created {resolved} (1 lines, 1 chars)', out)
                self.assertEqual(resolved.read_text(), 'x')
            finally:
                os.chdir(orig)

    def test_glob_recursive(self):
        (self.root / 'src').mkdir()
        (self.root / 'src' / 'app.py').write_text('x')
        (self.root / 'src' / 'deep').mkdir()
        (self.root / 'src' / 'deep' / 'mod.py').write_text('y')
        out = self.run_tool('glob', pattern='**/*.py', path=str(self.root))
        self.assertIn('src/app.py', out)
        self.assertIn('src/deep/mod.py', out)

    def test_glob_skips_noise_dirs(self):
        (self.root / 'app.py').write_text('x')
        (self.root / '.venv').mkdir()
        (self.root / '.venv' / 'lib.py').write_text('y')
        (self.root / '__pycache__').mkdir()
        (self.root / '__pycache__' / 'cache.py').write_text('z')
        out = self.run_tool('glob', pattern='**/*.py', path=str(self.root))
        self.assertIn('app.py', out)
        self.assertNotIn('.venv', out)
        self.assertNotIn('cache.py', out)

    def test_glob_dir_marker(self):
        (self.root / 'src').mkdir()
        (self.root / 'src' / 'a.txt').write_text('x')
        out = self.run_tool('glob', pattern='**/*', path=str(self.root))
        self.assertIn('src/', out)

    def test_glob_no_match(self):
        out = self.run_tool('glob', pattern='**/*.rs', path=str(self.root))
        self.assertIn('no matches', out)

    def test_glob_bad_path(self):
        out = self.run_tool('glob', pattern='**/*.py', path=str(self.root / 'nope'))
        self.assertIn('not a directory', out)

    def test_grep_finds_matches(self):
        (self.root / 'a.py').write_text('import os\nvalue = 1\n')
        (self.root / 'b.txt').write_text('no match here\n')
        out = self.run_tool('grep', pattern='value', path=str(self.root))
        self.assertIn('a.py:2:', out)
        self.assertNotIn('b.txt', out)

    def test_grep_glob_filter(self):
        (self.root / 'a.py').write_text('needle\n')
        (self.root / 'b.md').write_text('needle\n')
        out = self.run_tool('grep', pattern='needle', path=str(self.root), glob='*.py')
        self.assertIn('a.py:1:', out)
        self.assertNotIn('b.md', out)

    def test_grep_file_target(self):
        (self.root / 'a.py').write_text('needle here\n')
        out = self.run_tool('grep', pattern='needle', path=str(self.root / 'a.py'))
        self.assertIn('a.py:1:', out)

    def test_grep_no_match(self):
        (self.root / 'a.py').write_text('nothing\n')
        out = self.run_tool('grep', pattern='zzz', path=str(self.root))
        self.assertIn('no matches', out)

    def test_find_alias_resolves_to_grep(self):
        self.assertTrue(self.registry.is_registered('find'))
        (self.root / 'a.py').write_text('needle here\n')
        out = self.run_tool('find', path=str(self.root), query='needle')
        self.assertIn('a.py:1:', out)

    def test_grep_invalid_regex(self):
        out = self.run_tool('grep', pattern='[unclosed', path=str(self.root))
        self.assertIn('invalid regex', out)

    def test_metadata_registered(self):
        expected = {
            'file_read': ('read', 'read', 'path', 'path'),
            'list_dir': ('read', 'list', 'path', 'path'),
            'file_write': ('write', 'edit', 'path', 'path'),
            'glob': ('read', 'list', 'path', 'pattern'),
            'grep': ('read', 'list', 'path', 'pattern'),
        }
        for name, (category, permission, path_arg, key_arg) in expected.items():
            self.assertEqual(self.registry.permission_for(name), permission, name)
            self.assertEqual(self.registry.path_arg_for(name), path_arg, name)
            self.assertEqual(self.registry.key_arg_for(name), key_arg, name)

    def test_write_file_new_file_preview(self):
        path = str(self.root / 'new.md')
        value, body = self.registry.status_parts(
            'write_file', {'path': path, 'content': 'First line\nSecond line\n'})
        self.assertEqual(value, path)
        self.assertEqual(body[:2], ['+ First line', '+ Second line'])
        self.assertEqual(body[-1],
                         f'({Path(path).resolve()} - 2 lines, 23 chars, created)')

    def test_write_file_existing_file_diff(self):
        p = self.root / 'edit.md'
        p.write_text('old line\n')
        value, body = self.registry.status_parts(
            'write_file', {'path': str(p), 'content': 'new line\n'})
        self.assertEqual(value, str(p))
        self.assertIn('-old line', body)
        self.assertIn('+new line', body)
        self.assertEqual(body[-1], f'({p.resolve()} - 1 lines, 9 chars, overwritten)')

    def test_write_file_append_summary(self):
        p = self.root / 'append.md'
        p.write_text('a\n')
        value, body = self.registry.status_parts(
            'write_file', {'path': str(p), 'content': 'b\n', 'mode': 'a'})
        self.assertEqual(body[-1], f'({p.resolve()} - 1 lines, 2 chars, appended)')


if __name__ == '__main__':
    unittest.main()