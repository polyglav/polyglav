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


exec_plugin = _load_plugin('polyglav_exec_plugin', SRC / 'plugin.py')


class _Cfg:
    def __init__(self, **kw):
        self.data = kw

    def get(self, key, default=None):
        return self.data.get(key, default)


class TestExecTools(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.registry = ToolRegistry()
        exec_plugin.register_tools(self.registry)

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, name, **args):
        return self.registry.execute(name, args)

    def run_tool_cfg(self, name, config, **args):
        return self.registry.execute(name, args, config=config)

    def test_run_command_success(self):
        out = self.run_tool('run_command', command='echo hello', cwd=str(self.root))
        self.assertIn('exit 0', out)
        self.assertIn('hello', out)

    def test_run_command_nonzero_exit(self):
        out = self.run_tool('run_command', command='exit 3', cwd=str(self.root))
        self.assertIn('exit 3', out)

    def test_run_command_error_predicate(self):
        bad = self.run_tool('run_command', command='exit 3', cwd=str(self.root))
        self.assertTrue(self.registry.is_error_result('run_command', bad))
        good = self.run_tool('run_command', command='echo hi', cwd=str(self.root))
        self.assertFalse(self.registry.is_error_result('run_command', good))

    def test_run_command_timeout(self):
        out = self.run_tool('run_command', command='sleep 5', cwd=str(self.root), timeout=1)
        self.assertIn('timed out', out)

    def test_run_command_missing_cwd(self):
        out = self.run_tool('run_command', command='echo hi',
                            cwd='/definitely/not/a/real/dir')
        self.assertIn("Error: cwd not found: /definitely/not/a/real/dir", out)

    def test_clamp_timeout(self):
        self.assertEqual(exec_plugin._clamp_timeout(10000), exec_plugin.MAX_TIMEOUT)
        self.assertEqual(exec_plugin._clamp_timeout(5), 5)
        self.assertEqual(exec_plugin._clamp_timeout(0), 1)
        self.assertEqual(exec_plugin._clamp_timeout('nonsense'), exec_plugin.DEFAULT_TIMEOUT)
        self.assertEqual(exec_plugin._clamp_timeout(None), exec_plugin.DEFAULT_TIMEOUT)

    def test_run_command_cap_truncates(self):
        out = self.run_tool_cfg('run_command', _Cfg(tool_max_result_chars=20),
                                command='seq 1 1000', cwd=str(self.root))
        self.assertIn('... (truncated)', out)
        self.assertNotIn('\n1000', out)

    def test_metadata_registered(self):
        self.assertEqual(self.registry.permission_for('run_command'), 'bash')
        self.assertEqual(self.registry.path_arg_for('run_command'), 'cwd')
        self.assertEqual(self.registry.key_arg_for('run_command'), 'command')
        self.assertTrue(self.registry.echo_for('run_command'))
        self.assertEqual(self.registry.resolver_for('run_command'),
                         exec_plugin._run_command_permission)

    def test_exec_allow_allows_prefix(self):
        out = exec_plugin._run_command_permission(
            {'command': 'pytest -q'}, {'exec_allow': ['pytest', 'python -m unittest']})
        self.assertIsNone(out)

    def test_exec_allow_denies_other(self):
        out = exec_plugin._run_command_permission(
            {'command': 'rm -rf /'}, {'exec_allow': ['pytest', 'python -m unittest']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_chain_all_segments(self):
        out = exec_plugin._run_command_permission(
            {'command': 'pytest -q && ruff check .'},
            {'exec_allow': ['pytest', 'ruff']})
        self.assertIsNone(out)

    def test_exec_allow_chain_denies_unlisted_segment(self):
        out = exec_plugin._run_command_permission(
            {'command': 'pytest -q && rm -rf /'},
            {'exec_allow': ['pytest', 'ruff']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_pipe_segments(self):
        out = exec_plugin._run_command_permission(
            {'command': 'git diff | grep foo'},
            {'exec_allow': ['git', 'grep']})
        self.assertIsNone(out)

    def test_exec_allow_rejects_heredoc(self):
        out = exec_plugin._run_command_permission(
            {'command': 'cat <<EOF\nx\nEOF'},
            {'exec_allow': ['cat']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_rejects_multiline(self):
        out = exec_plugin._run_command_permission(
            {'command': 'pytest\nruff check .'},
            {'exec_allow': ['pytest', 'ruff']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_empty_list_is_unrestricted(self):
        out = exec_plugin._run_command_permission(
            {'command': 'rm -rf /'}, {'exec_allow': []})
        self.assertIsNone(out)

    def test_exec_allow_no_permissions_is_unrestricted(self):
        out = exec_plugin._run_command_permission({'command': 'rm -rf /'})
        self.assertIsNone(out)

    def test_exec_allow_whitespace_prefix(self):
        out = exec_plugin._run_command_permission(
            {'command': '  pytest -q'}, {'exec_allow': ['pytest']})
        self.assertIsNone(out)

    def test_exec_allow_semicolon_chain(self):
        out = exec_plugin._run_command_permission(
            {'command': 'pytest; ruff check .'},
            {'exec_allow': ['pytest', 'ruff']})
        self.assertIsNone(out)

    def test_exec_allow_rejects_backtick_substitution(self):
        out = exec_plugin._run_command_permission(
            {'command': 'git log `id`'}, {'exec_allow': ['git']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_rejects_dollar_substitution(self):
        out = exec_plugin._run_command_permission(
            {'command': 'git diff -- $(id)'}, {'exec_allow': ['git']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_rejects_dollar_brace(self):
        out = exec_plugin._run_command_permission(
            {'command': 'git log ${HOME}'}, {'exec_allow': ['git']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_rejects_output_redirect(self):
        out = exec_plugin._run_command_permission(
            {'command': 'git status > /tmp/pwn'}, {'exec_allow': ['git']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_rejects_input_redirect(self):
        out = exec_plugin._run_command_permission(
            {'command': 'git log < /etc/shadow'}, {'exec_allow': ['git']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_rejects_fd_duplication(self):
        out = exec_plugin._run_command_permission(
            {'command': 'pytest -q 2>&1'}, {'exec_allow': ['pytest']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_prefix_respects_token_boundary(self):
        out = exec_plugin._run_command_permission(
            {'command': 'pytestx --run evil'}, {'exec_allow': ['pytest']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_prefix_respects_token_boundary_for_interpreters(self):
        out = exec_plugin._run_command_permission(
            {'command': 'python3 -c "import os"'}, {'exec_allow': ['python']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_multi_token_prefix(self):
        out = exec_plugin._run_command_permission(
            {'command': 'python -m unittest discover tests'},
            {'exec_allow': ['python -m unittest']})
        self.assertIsNone(out)

    def test_exec_allow_multi_token_prefix_denies_other_module(self):
        out = exec_plugin._run_command_permission(
            {'command': 'python -m pip install evil'},
            {'exec_allow': ['python -m unittest']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_rejects_unbalanced_quotes(self):
        out = exec_plugin._run_command_permission(
            {'command': 'pytest "unbalanced'}, {'exec_allow': ['pytest']})
        self.assertEqual(out, 'deny')

    def test_exec_allow_trailing_space_prefix(self):
        out = exec_plugin._run_command_permission(
            {'command': 'git status'}, {'exec_allow': ['git ']})
        self.assertIsNone(out)

    def test_resolver_error_denies_run_command(self):
        from polyglav.tools.policy import ToolPolicy

        def boom(args):
            raise RuntimeError('allowlist lookup failed')

        policy = ToolPolicy(
            permissions={'bash': 'allow'},
            resolvers={'run_command': boom})
        self.assertEqual(
            policy.action('run_command', 'bash', args={'command': 'pytest'}),
            'deny')

    def test_cwd_outside_worktree_escalates_to_ask(self):
        from polyglav.tools.policy import ToolPolicy

        outside = self.root.parent / 'elsewhere'
        policy = ToolPolicy(
            permissions={'bash': 'allow'},
            worktree=self.root,
            resolvers={'run_command': exec_plugin._run_command_permission})
        self.assertEqual(
            policy.action('run_command', 'bash', str(self.root),
                          {'command': 'pytest', 'cwd': str(self.root)}), 'allow')
        self.assertEqual(
            policy.action('run_command', 'bash', str(outside),
                          {'command': 'pytest', 'cwd': str(outside)}), 'ask')


if __name__ == '__main__':
    unittest.main()