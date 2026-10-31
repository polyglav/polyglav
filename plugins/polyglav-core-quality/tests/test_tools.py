import importlib.util
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


quality_plugin = _load_plugin('polyglav_quality_plugin', SRC / 'plugin.py')


class _Cfg:
    def __init__(self, **kw):
        self.data = kw

    def get(self, key, default=None):
        return self.data.get(key, default)


class TestQualityTools(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.registry = ToolRegistry()
        quality_plugin.register_tools(self.registry)

    def tearDown(self):
        self._tmp.cleanup()

    def _cmd(self, name):
        p = self.root / name
        p.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 0\n')
        p.chmod(0o755)
        return str(p)

    def run_tool_cfg(self, name, config, **args):
        return self.registry.execute(name, args, config=config)

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

    def test_cwd_missing(self):
        out = self.run_tool_cfg('code_lint', _Cfg(), cwd=str(self.root / 'nope'))
        self.assertIn('cwd not found', out)

    def test_metadata_registered(self):
        for name in ('code_lint', 'code_format'):
            self.assertEqual(self.registry.permission_for(name), 'bash', name)
            self.assertEqual(self.registry.path_arg_for(name), 'cwd', name)
            self.assertEqual(self.registry.key_arg_for(name), 'target', name)

    def test_aliases_registered(self):
        for alias in ('run_lint', 'lint_check', 'run_format', 'format_code'):
            self.assertTrue(self.registry.is_registered(alias), alias)


if __name__ == '__main__':
    unittest.main()
