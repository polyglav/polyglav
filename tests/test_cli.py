import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from polyglav.cli import cmd_run, cmd_models, cmd_plugins
from polyglav.main import main
from polyglav import get_version
from polyglav.config import Config, DEFAULT_CONFIG
from polyglav.sessions.manager import Session

import importlib.util
_plugin_path = (Path(__file__).resolve().parents[1] / 'plugins'
                / 'polyglav-core-sessions' / 'src' / 'plugin.py')
_spec = importlib.util.spec_from_file_location(
    'polyglav_core_sessions_plugin_test', _plugin_path)
_sessions_plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sessions_plugin)
cmd_export = _sessions_plugin.cmd_export
cmd_import = _sessions_plugin.cmd_import


def _factory(rounds):
    def _f(**kwargs):
        p = MagicMock()
        p.chat.side_effect = rounds
        return p
    _f.DEFAULT_BASE_URL = 'https://fake.api.com'
    _f.DEFAULT_MODEL = 'fake-model'
    _f.HOST_PATTERNS = ('ollama.com', 'fake.api.com')
    return _f


class TestCliHelp(unittest.TestCase):

    def test_help_groups_core_and_plugin_commands(self):
        out = io.StringIO()
        with patch('sys.stdout', new=out), self.assertRaises(SystemExit):
            main(['--help'])
        text = out.getvalue()
        self.assertIn('Core commands:', text)
        self.assertIn('Plugin commands:', text)
        self.assertIn('serv', text)


class TestCliRun(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, **kw):
        base = dict(prompt='hello', output='json', session_id=None, approve=None,
                    verbose=False, path=self.tmp.name, provider=None, model=None,
                    base_url=None, mode=None)
        base.update(kw)
        return SimpleNamespace(**base)

    def _run(self, rounds, **kw):
        with patch('polyglav.providers.PROVIDERS', {'ollama': _factory(rounds)}):
            out = io.StringIO()
            with patch('sys.stdout', new=out):
                rc = cmd_run(self._args(**kw))
        return rc, out.getvalue()

    def test_run_json_output(self):
        rc, out = self._run([[{'type': 'token', 'content': 'cli answer'},
                              {'type': 'done', 'reason': 'stop'}]])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data['content'], 'cli answer')
        self.assertEqual(data['status'], 'ok')

    def _global_dir(self):
        from polyglav.config import Config, DEFAULT_CONFIG
        prev = Config.GLOBAL_DIR
        Config.GLOBAL_DIR = Path(self.tmp.name) / 'global-home'
        return prev

    def test_run_explicit_model_auto_approves(self):
        from polyglav.cli import _engine_from_args
        from polyglav.config import Config, DEFAULT_CONFIG
        prev = self._global_dir()
        try:
            args = self._args(model='opencode-go/deepseek-v4-flash')
            engine = _engine_from_args(args)
            self.assertTrue(engine.approve_models)
            self.assertEqual(engine.config.get('model'),
                             'opencode-go/deepseek-v4-flash')
            self.assertEqual(engine.model_target()[0], 'opencode-go')
            from polyglav.models import ModelRegistry
            reg = ModelRegistry()
            self.assertIsNotNone(reg.find('opencode-go', 'deepseek-v4-flash'))
        finally:
            Config.GLOBAL_DIR = prev

    def test_run_approve_model_flag_grants(self):
        from polyglav.cli import _engine_from_args
        from polyglav.config import Config, DEFAULT_CONFIG
        prev = self._global_dir()
        try:
            engine = _engine_from_args(self._args(approve_model=True))
            self.assertTrue(engine.approve_models)
        finally:
            Config.GLOBAL_DIR = prev

    def test_run_default_does_not_auto_approve(self):
        from polyglav.cli import _engine_from_args
        from polyglav.config import Config, DEFAULT_CONFIG
        prev = self._global_dir()
        try:
            engine = _engine_from_args(self._args())
            self.assertFalse(engine.approve_models)
        finally:
            Config.GLOBAL_DIR = prev

    def test_run_stdout_is_pure_json(self):
        _, out = self._run([[{'type': 'token', 'content': 'answer'},
                             {'type': 'done', 'reason': 'stop'}]])
        json.loads(out)
        self.assertNotIn('\x1b', out)

    def test_run_text_mode_streams_content(self):
        rc, out = self._run([[{'type': 'token', 'content': 'plain answer'},
                              {'type': 'done', 'reason': 'stop'}]], output='text')
        self.assertEqual(rc, 0)
        self.assertIn('plain answer', out)

    def test_run_error_exit_code(self):
        rc, _ = self._run([[{'type': 'error', 'code': 500, 'message': 'boom'}]])
        self.assertEqual(rc, 1)

    def test_run_overrides_do_not_persist(self):
        self._run([[{'type': 'token', 'content': 'x'},
                    {'type': 'done', 'reason': 'stop'}]],
                  provider='ollama', model='override-model',
                  base_url='https://override.example')
        cfg = Path(self.tmp.name) / '.polyglav' / 'config.json'
        self.assertFalse(cfg.exists())

    def test_run_overrides_apply(self):
        captured = {}

        def _factory_rec(**kwargs):
            captured.update(kwargs)
            p = MagicMock()
            p.chat.side_effect = [[{'type': 'token', 'content': 'x'},
                                   {'type': 'done', 'reason': 'stop'}]]
            return p
        _factory_rec.DEFAULT_BASE_URL = 'https://fake.api.com'
        _factory_rec.DEFAULT_MODEL = 'fake-model'
        with patch('polyglav.providers.PROVIDERS', {'ollama': _factory_rec}):
            out = io.StringIO()
            with patch('sys.stdout', new=out):
                cmd_run(self._args(provider='ollama', model='my-model',
                                   base_url='https://x.example'))
        self.assertEqual(captured['model'], 'my-model')
        self.assertEqual(captured['base_url'], 'https://x.example')

    def test_run_yes_approves_asks(self):
        tool_round = [{'type': 'tool_calls', 'tool_calls': [{
            'id': 'c1', 'type': 'function',
            'function': {'name': 'run_command', 'arguments': '{"command": "echo hi"}'},
        }]}]
        content_round = [{'type': 'token', 'content': 'ran it'},
                         {'type': 'done', 'reason': 'stop'}]
        rc, out = self._run([tool_round, content_round], approve=True)
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data['content'], 'ran it')
        self.assertEqual(len(data['tool_calls']), 1)

    def test_run_default_denies_asks(self):
        tool_round = [{'type': 'tool_calls', 'tool_calls': [{
            'id': 'c1', 'type': 'function',
            'function': {'name': 'run_command', 'arguments': '{"command": "echo hi"}'},
        }]}]
        content_round = [{'type': 'token', 'content': 'skipped'},
                         {'type': 'done', 'reason': 'stop'}]
        rc, out = self._run([tool_round, content_round])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(len(data['tool_calls']), 1)

    def test_run_mode_read_filters_schema(self):
        captured = {}

        def _factory_rec(rounds):
            def _f(**kwargs):
                p = MagicMock()
                p.chat.side_effect = rounds
                captured['provider'] = p
                return p
            _f.DEFAULT_BASE_URL = 'https://fake.api.com'
            _f.DEFAULT_MODEL = 'fake-model'
            _f.HOST_PATTERNS = ('ollama.com', 'fake.api.com')
            return _f
        rounds = [[{'type': 'token', 'content': 'plan answer'},
                   {'type': 'done', 'reason': 'stop'}]]
        with patch('polyglav.providers.PROVIDERS', {'ollama': _factory_rec(rounds)}):
            out = io.StringIO()
            with patch('sys.stdout', new=out):
                rc = cmd_run(self._args(mode='read'))
        self.assertEqual(rc, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data['content'], 'plan answer')
        tools = captured['provider'].chat.call_args.kwargs['tools']
        names = [s['function']['name'] for s in tools]
        self.assertNotIn('file_write', names)
        self.assertNotIn('run_command', names)
        self.assertIn('file_read', names)
        msgs = captured['provider'].chat.call_args.args[0]
        self.assertIn('read mode', msgs[0]['content'])

    def test_run_mode_write_keeps_write_tools(self):
        captured = {}

        def _factory_rec(rounds):
            def _f(**kwargs):
                p = MagicMock()
                p.chat.side_effect = rounds
                captured['provider'] = p
                return p
            _f.DEFAULT_BASE_URL = 'https://fake.api.com'
            _f.DEFAULT_MODEL = 'fake-model'
            _f.HOST_PATTERNS = ('ollama.com', 'fake.api.com')
            return _f
        rounds = [[{'type': 'token', 'content': 'x'},
                   {'type': 'done', 'reason': 'stop'}]]
        with patch('polyglav.providers.PROVIDERS', {'ollama': _factory_rec(rounds)}):
            out = io.StringIO()
            with patch('sys.stdout', new=out):
                cmd_run(self._args(mode='write'))
        tools = captured['provider'].chat.call_args.kwargs['tools']
        names = [s['function']['name'] for s in tools]
        self.assertIn('file_write', names)
        self.assertIn('run_command', names)


class TestCliPlugins(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, **kw):
        base = dict(path=self.path, action='list', source=None,
                    global_=False, deps=False, name=None)
        base.update(kw)
        return SimpleNamespace(**base)

    def _capture(self, args):
        out = io.StringIO()
        err = io.StringIO()
        with patch('sys.stdout', new=out), patch('sys.stderr', new=err):
            rc = cmd_plugins(args)
        return rc, out.getvalue(), err.getvalue()

    def test_plugins_list_shows_bundled(self):
        rc, out, _ = self._capture(self._args())
        self.assertEqual(rc, 0)
        self.assertIn('polyglav-core-web', out)
        self.assertIn('bundled', out)

    def test_plugins_install_list_uninstall(self):
        src = Path(self.path) / 'src_plugin'
        (src / 'manifest.json').parent.mkdir(parents=True, exist_ok=True)
        with open(src / 'manifest.json', 'w') as f:
            json.dump({'name': 'hello', 'version': '1.0.0'}, f)
        with open(src / 'plugin.py', 'w') as f:
            f.write('def register_tools(registry):\n    pass\n')

        rc, out, _ = self._capture(self._args(action='install', source=str(src)))
        self.assertEqual(rc, 0)
        self.assertIn('hello', out)

        rc, out, _ = self._capture(self._args(action='list'))
        self.assertEqual(rc, 0)
        self.assertIn('hello', out)

        rc, _, _ = self._capture(self._args(action='uninstall', name='hello'))
        self.assertEqual(rc, 0)
        self.assertFalse((Path(self.path) / '.polyglav' / 'plugins' / 'hello').exists())

    def test_plugins_install_missing_source_errors(self):
        rc, _, err = self._capture(self._args(action='install',
                                              source='/nonexistent/path'))
        self.assertEqual(rc, 1)
        self.assertIn('Error', err)

    def _install_hello(self):
        src = Path(self.path) / 'src_plugin'
        (src / 'manifest.json').parent.mkdir(parents=True, exist_ok=True)
        with open(src / 'manifest.json', 'w') as f:
            json.dump({'name': 'hello', 'version': '1.0.0'}, f)
        with open(src / 'plugin.py', 'w') as f:
            f.write('def register_tools(registry):\n    pass\n')
        rc, _, _ = self._capture(self._args(action='install', source=str(src)))
        self.assertEqual(rc, 0)

    def test_plugins_enable_adds_to_plugins_list(self):
        self._install_hello()
        cfg = Config(path=self.path)
        cfg.set('plugins', [p for p in cfg.get('plugins') if p != 'hello'])
        rc, out, _ = self._capture(self._args(action='enable', name='hello'))
        self.assertEqual(rc, 0)
        self.assertIn('enabled', out)
        self.assertIn('hello', Config(path=self.path).get('plugins'))

    def test_plugins_disable_removes_from_plugins_list(self):
        self._install_hello()
        rc, out, _ = self._capture(self._args(action='disable', name='hello'))
        self.assertEqual(rc, 0)
        self.assertIn('disabled', out)
        self.assertNotIn('hello', Config(path=self.path).get('plugins'))

    def test_plugins_toggle_unknown_plugin_errors(self):
        rc, _, err = self._capture(self._args(action='enable', name='nosuch'))
        self.assertEqual(rc, 1)
        self.assertIn('Plugin not installed', err)


class TestCliVersion(unittest.TestCase):

    def test_version_long_flag(self):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            with self.assertRaises(SystemExit) as ctx:
                main(['--version'])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn(get_version(), out.getvalue())

    def test_version_short_flag(self):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            with self.assertRaises(SystemExit) as ctx:
                main(['-v'])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn(get_version(), out.getvalue())




if __name__ == '__main__':
    unittest.main()
