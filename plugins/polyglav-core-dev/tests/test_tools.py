import importlib.util
import subprocess
import sys
import tempfile
import unittest
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


dev_plugin = _load_plugin('polyglav_dev_plugin', SRC / 'plugin.py')


class _Cfg:
    def __init__(self, **kw):
        self.data = kw

    def get(self, key, default=None):
        return self.data.get(key, default)


class TestDevTools(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.registry = ToolRegistry()
        dev_plugin.register_tools(self.registry)

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, name, **args):
        return self.registry.execute(name, args)

    def run_tool_cfg(self, name, config, **args):
        return self.registry.execute(name, args, config=config)

    def _write(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def _cmd(self, name):
        p = self.root / name
        p.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 0\n')
        p.chmod(0o755)
        return str(p)

    def test_code_test_runs_python_unittest(self):
        self._write('tests/__init__.py', '')
        self._write('tests/test_ok.py', 'import unittest\n'
                    'class T(unittest.TestCase):\n'
                    '    def test_p(self):\n'
                    '        self.assertTrue(True)\n')
        out = self.run_tool('code_test', cwd=str(self.root))
        self.assertIn(f'$ {sys.executable} -m unittest discover', out)
        self.assertIn('exit 0', out)
        self.assertIn('OK', out)

    def test_code_test_explicit_python_resolves_interpreter(self):
        self._write('tests/__init__.py', '')
        self._write('tests/test_ok.py', 'import unittest\n'
                    'class T(unittest.TestCase):\n'
                    '    def test_p(self):\n'
                    '        self.assertTrue(True)\n')
        out = self.run_tool_cfg('code_test',
                                _Cfg(**{'dev.test_cmd': 'python -m unittest discover'}),
                                cwd=str(self.root))
        self.assertIn(f'$ {sys.executable} -m unittest discover', out)
        self.assertIn('OK', out)

    def test_code_test_default_cmd_from_config(self):
        script = self._cmd('fake_test.sh')
        out = self.run_tool_cfg('code_test',
                                _Cfg(**{'dev.test_cmd': script}),
                                cwd=str(self.root))
        self.assertIn(f'$ {script}', out)

    def test_code_test_target_appended(self):
        script = self._cmd('fake_test.sh')
        out = self.run_tool_cfg('code_test',
                                _Cfg(**{'dev.test_cmd': script}),
                                target='tests.test_something',
                                cwd=str(self.root))
        self.assertIn(f'$ {script} tests.test_something', out)
        self.assertIn('tests.test_something', out)

    def test_code_test_target_runs_module(self):
        self._write('tests/__init__.py', '')
        self._write('tests/test_ok.py', 'import unittest\n'
                    'class T(unittest.TestCase):\n'
                    '    def test_p(self):\n'
                    '        self.assertTrue(True)\n')
        out = self.run_tool('code_test', target='tests.test_ok',
                            cwd=str(self.root))
        self.assertIn(f'$ {sys.executable} -m unittest tests.test_ok', out)
        self.assertNotIn('discover tests tests.test_ok', out)
        self.assertIn('exit 0', out)
        self.assertIn('OK', out)

    def test_code_test_target_no_match_reported(self):
        self._write('tests/__init__.py', '')
        self._write('tests/test_empty.py', 'import unittest\n')
        out = self.run_tool('code_test', target='tests.test_empty',
                            cwd=str(self.root))
        self.assertIn('no tests matched "tests.test_empty"', out)
        self.assertIn('Ran 0 tests', out)

    def test_default_timeout_fits_full_suite(self):
        self.assertGreaterEqual(dev_plugin.DEFAULT_TIMEOUT, 300)

    def test_code_lint_default_is_ruff(self):
        script = self._cmd('fake_lint.sh')
        out = self.run_tool_cfg('code_lint',
                                _Cfg(**{'dev.lint_cmd': script}),
                                cwd=str(self.root))
        self.assertIn(f'$ {script}', out)

    def test_code_format_default_is_ruff(self):
        script = self._cmd('fake_format.sh')
        out = self.run_tool_cfg('code_format',
                                _Cfg(**{'dev.format_cmd': script}),
                                cwd=str(self.root))
        self.assertIn(f'$ {script}', out)

    def test_code_lint_reports_failure(self):
        script = self.root / 'fail_lint.sh'
        script.write_text('#!/bin/sh\necho "E501 line too long"\nexit 1\n')
        script.chmod(0o755)
        out = self.run_tool_cfg('code_lint',
                                _Cfg(**{'dev.lint_cmd': str(script)}),
                                cwd=str(self.root))
        self.assertIn('exit 1', out)
        self.assertIn('E501 line too long', out)

    def test_code_test_unknown_command(self):
        out = self.run_tool_cfg('code_test',
                                _Cfg(**{'dev.test_cmd': 'definitely-not-a-real-cmd-xyz'}),
                                cwd=str(self.root))
        self.assertIn('not found', out)

    def test_cwd_missing(self):
        out = self.run_tool('code_test', cwd=str(self.root / 'nope'))
        self.assertIn('cwd not found', out)

    def test_timeout_reports(self):
        script = self.root / 'hang.sh'
        script.write_text('#!/bin/sh\nsleep 30\n')
        script.chmod(0o755)
        out = self.run_tool_cfg('code_test',
                                _Cfg(**{'dev.test_cmd': str(script)}),
                                timeout=1, cwd=str(self.root))
        self.assertIn('timed out', out)

    def test_metadata_registered(self):
        for name in ('code_test', 'code_lint', 'code_format'):
            self.assertEqual(self.registry.permission_for(name), 'bash', name)
            self.assertEqual(self.registry.path_arg_for(name), 'cwd', name)
            self.assertEqual(self.registry.key_arg_for(name), 'target', name)

    def test_aliases_registered(self):
        for alias in ('run_tests', 'test_suite', 'run_lint', 'lint_check',
                      'run_format', 'format_code'):
            self.assertTrue(self.registry.is_registered(alias), alias)

    def test_alias_param_alias(self):
        script = self._cmd('fake_test.sh')
        out = self.run_tool_cfg('run_tests',
                                _Cfg(**{'dev.test_cmd': script}),
                                test='tests.test_x',
                                cwd=str(self.root))
        self.assertIn('tests.test_x', out)

    def test_cap_truncates(self):
        script = self.root / 'big.sh'
        script.write_text('#!/bin/sh\nprintf "x%.0s" $(seq 1 20000)\n')
        script.chmod(0o755)
        out = self.run_tool_cfg('code_test',
                                _Cfg(**{'dev.test_cmd': str(script),
                                        'tool_max_result_chars': 1000}),
                                cwd=str(self.root))
        self.assertIn('... (truncated)', out)


if __name__ == '__main__':
    unittest.main()