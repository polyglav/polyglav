import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polyglav.tools.policy import ToolPolicy
from polyglav.tools.registry import ToolRegistry


def _load_plugin(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


git_plugin = _load_plugin('polyglav_git_plugin', SRC / 'plugin.py')


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(repo) if False else None
    return subprocess.run(['git'] + list(args), cwd=str(repo),
                          capture_output=True, text=True, env=env)


class _Cfg:
    def __init__(self, **kw):
        self.data = kw

    def get(self, key, default=None):
        return self.data.get(key, default)


def _init_repo(repo: Path) -> None:
    _git(repo, 'init', '-q', '-b', 'main')
    _git(repo, 'config', 'user.email', 'test@example.com')
    _git(repo, 'config', 'user.name', 'Test')
    (repo / 'a.txt').write_text('one\n')
    _git(repo, 'add', 'a.txt')
    _git(repo, 'commit', '-q', '-m', 'first commit')


class TestGitTools(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _init_repo(self.repo)
        self.registry = ToolRegistry()
        git_plugin.register_tools(self.registry)

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, name, **args):
        return self.registry.execute(name, args)

    def test_status_short_branch(self):
        out = self.run_tool('git', cwd=str(self.repo))
        self.assertIn('$ git status --short --branch', out)
        self.assertIn('main', out)
        self.assertIn('exit 0', out)

    def test_diff_clean(self):
        out = self.run_tool('git', operation='diff', cwd=str(self.repo))
        self.assertIn('exit 0', out)

    def test_diff_shows_change(self):
        (self.repo / 'a.txt').write_text('one\ntwo\n')
        out = self.run_tool('git', operation='diff', cwd=str(self.repo))
        self.assertIn('+two', out)

    def test_diff_staged(self):
        (self.repo / 'b.txt').write_text('x\n')
        _git(self.repo, 'add', 'b.txt')
        out = self.run_tool('git', operation='diff', staged=True,
                            cwd=str(self.repo))
        self.assertIn('b.txt', out)
        self.assertIn('$ git diff --cached', out)

    def test_log(self):
        out = self.run_tool('git', operation='log', cwd=str(self.repo))
        self.assertIn('first commit', out)
        self.assertIn('$ git log --oneline -20', out)

    def test_log_limit(self):
        (self.repo / 'a.txt').write_text('two\n')
        _git(self.repo, 'add', 'a.txt')
        _git(self.repo, 'commit', '-q', '-m', 'second commit')
        out = self.run_tool('git', operation='log', limit=1,
                            cwd=str(self.repo))
        self.assertIn('second commit', out)
        self.assertNotIn('first commit', out)

    def test_log_path(self):
        (self.repo / 'b.txt').write_text('x\n')
        _git(self.repo, 'add', 'b.txt')
        _git(self.repo, 'commit', '-q', '-m', 'add b')
        out = self.run_tool('git', operation='log', path='a.txt',
                            cwd=str(self.repo))
        self.assertIn('first commit', out)
        self.assertNotIn('add b', out)

    def test_branch(self):
        out = self.run_tool('git', operation='branch', cwd=str(self.repo))
        self.assertIn('main', out)

    def test_rev_parse(self):
        out = self.run_tool('git', operation='rev_parse', cwd=str(self.repo))
        self.assertIn('exit 0', out)

    def test_show(self):
        out = self.run_tool('git', operation='show', cwd=str(self.repo))
        self.assertIn('$ git show --stat', out)
        self.assertIn('a.txt', out)

    def test_add(self):
        (self.repo / 'new.txt').write_text('hi\n')
        out = self.run_tool('git_commit', operation='add',
                            path='new.txt', cwd=str(self.repo))
        self.assertIn('$ git add new.txt', out)
        staged = _git(self.repo, 'diff', '--cached', '--name-only')
        self.assertIn('new.txt', staged.stdout)

    def test_add_all(self):
        (self.repo / 'x.txt').write_text('x\n')
        (self.repo / 'y.txt').write_text('y\n')
        self.run_tool('git_commit', operation='add', all=True,
                      cwd=str(self.repo))
        staged = _git(self.repo, 'diff', '--cached', '--name-only')
        self.assertIn('x.txt', staged.stdout)
        self.assertIn('y.txt', staged.stdout)

    def test_add_requires_path_or_all(self):
        out = self.run_tool('git_commit', operation='add', cwd=str(self.repo))
        self.assertIn('requires a path', out)

    def test_commit(self):
        (self.repo / 'a.txt').write_text('one\ntwo\n')
        _git(self.repo, 'add', 'a.txt')
        out = self.run_tool('git_commit', operation='commit',
                            message='second commit', cwd=str(self.repo))
        self.assertIn('second commit', out)
        log = _git(self.repo, 'log', '--oneline')
        self.assertIn('second commit', log.stdout)

    def test_commit_all_stages_first(self):
        (self.repo / 'new.txt').write_text('hi\n')
        self.run_tool('git_commit', operation='commit', all=True,
                      message='add new', cwd=str(self.repo))
        log = _git(self.repo, 'log', '--oneline')
        self.assertIn('add new', log.stdout)
        status = _git(self.repo, 'status', '--porcelain')
        self.assertEqual(status.stdout.strip(), '')

    def test_commit_requires_message(self):
        out = self.run_tool('git_commit', operation='commit',
                            cwd=str(self.repo))
        self.assertIn('requires a message', out)

    def test_cwd_missing(self):
        out = self.run_tool('git', cwd=str(self.repo / 'nope'))
        self.assertIn('cwd not found', out)

    def test_metadata_registered(self):
        self.assertEqual(self.registry.permission_for('git'), 'read')
        self.assertEqual(self.registry.permission_for('git_commit'), 'vcs')
        self.assertEqual(self.registry.path_arg_for('git'), 'cwd')
        self.assertEqual(self.registry.key_arg_for('git'), 'operation')

    def test_git_has_own_identity(self):
        self.assertEqual(self.registry.activity('git', {'operation': 'log'})[:2],
                         ('⎇', 'Git'))
        self.assertEqual(self.registry.activity('git_commit',
                                                {'operation': 'commit'})[:2],
                         ('⎇', 'Git'))

    def test_write_action_defers_unless_all(self):
        self.assertIsNone(git_plugin._write_action({}))
        self.assertIsNone(git_plugin._write_action({'operation': 'commit'}))
        self.assertEqual(git_plugin._write_action({'all': True}), 'ask')

    def test_vcs_permission_resolution(self):
        resolvers = {'git_commit': git_plugin._write_action}
        carved = ToolPolicy(
            permissions={'edit': 'allow', 'vcs': 'allow'},
            resolvers=resolvers)
        self.assertEqual(carved.action('git_commit', 'vcs'), 'allow')
        self.assertEqual(carved.action('git_commit', 'vcs', args={}), 'allow')
        self.assertEqual(
            carved.action('git_commit', 'vcs', args={'all': True}), 'ask')
        gated = ToolPolicy(
            permissions={'edit': 'allow'}, resolvers=resolvers)
        self.assertEqual(gated.action('git_commit', 'vcs'), 'ask')
        self.assertEqual(gated.action('git_commit', 'vcs', args={}), 'ask')

    def test_aliases_registered(self):
        for alias in ('git_status', 'git_diff', 'git_log', 'git_branch',
                      'git_show', 'commit'):
            self.assertTrue(self.registry.is_registered(alias), alias)

    def test_alias_param_alias_msg(self):
        (self.repo / 'a.txt').write_text('one\ntwo\n')
        _git(self.repo, 'add', 'a.txt')
        out = self.run_tool('commit', operation='commit', msg='aliased',
                            cwd=str(self.repo))
        self.assertIn('aliased', out)
        log = _git(self.repo, 'log', '--oneline')
        self.assertIn('aliased', log.stdout)


if __name__ == '__main__':
    unittest.main()