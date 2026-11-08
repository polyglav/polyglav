import io
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from polyglav.cli import cmd_models
from polyglav.main import main


class TestCliModels(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, **kw):
        base = dict(path=self.path, action=None, provider='')
        base.update(kw)
        return SimpleNamespace(**base)

    def _engine(self, models=None, grouped=None, keys=None, list_result=None):
        engine = MagicMock()
        engine.models.all.return_value = models or []
        engine.models.grouped.return_value = grouped or []
        engine.providers.find.return_value = None
        engine.providers.api_key_for.side_effect = keys or (lambda p: '')
        if list_result is not None:
            engine.list_models.return_value = list_result
        if models:
            engine.model_target.return_value = (
                models[0].provider, '', models[0].model)
        else:
            engine.model_target.return_value = ('ollama', 'https://api.ollama.com', 'llama3.2')
        return engine

    def _capture(self, args, engine):
        with patch('polyglav.cli.Engine', return_value=engine):
            out = io.StringIO()
            err = io.StringIO()
            with patch('sys.stdout', new=out), patch('sys.stderr', new=err):
                rc = cmd_models(args)
        return rc, out.getvalue(), err.getvalue()

    def test_models_bare_lists_configured(self):
        e1 = SimpleNamespace(provider='openai', model='gpt-4o')
        e2 = SimpleNamespace(provider='ollama', model='llama3.2')
        engine = self._engine(models=[e1, e2],
                              grouped=[('openai', [e1]), ('ollama', [e2])],
                              keys=lambda p: 'k' if p == 'openai' else '')
        rc, out, _ = self._capture(self._args(), engine)
        self.assertEqual(rc, 0)
        self.assertIn('openai:', out)
        self.assertIn('gpt-4o', out)
        self.assertIn('(key)', out)
        self.assertIn('ollama:', out)

    def test_models_bare_marks_active(self):
        e = SimpleNamespace(provider='ollama', model='llama3.2')
        engine = self._engine(models=[e], grouped=[('ollama', [e])])
        rc, out, _ = self._capture(self._args(), engine)
        self.assertEqual(rc, 0)
        self.assertIn('> llama3.2', out)

    def test_models_bare_empty(self):
        rc, out, _ = self._capture(self._args(), self._engine())
        self.assertEqual(rc, 0)
        self.assertIn('No models configured yet', out)

    def test_models_list_probes_current(self):
        engine = self._engine(list_result=(['m1', 'm2'], None))
        rc, out, _ = self._capture(self._args(action='list'), engine)
        self.assertEqual(rc, 0)
        self.assertIn('2 models available from ollama', out)
        self.assertIn('- m1', out)
        engine.list_models.assert_called_once_with(
            provider='ollama', base_url='https://api.ollama.com',
            api_key='', model='llama3.2')

    def test_models_list_probes_provider(self):
        engine = self._engine(list_result=(['gpt-4o', 'gpt-5'], None))
        rc, out, _ = self._capture(self._args(action='list', provider='openai'),
                                   engine)
        self.assertEqual(rc, 0)
        self.assertIn('2 models available from openai', out)
        engine.list_models.assert_called_once_with(
            provider='openai', base_url='https://api.ollama.com',
            api_key='', model='llama3.2')

    def test_models_list_error_exit_code(self):
        engine = self._engine(list_result=([], 'HTTP 500: boom'))
        rc, _, err = self._capture(self._args(action='list'), engine)
        self.assertEqual(rc, 1)
        self.assertIn('HTTP 500: boom', err)

    def test_models_list_empty(self):
        engine = self._engine(list_result=([], None))
        rc, out, _ = self._capture(self._args(action='list'), engine)
        self.assertEqual(rc, 0)
        self.assertIn('No models listed from ollama', out)

    def test_models_context_sets_budget(self):
        entry = SimpleNamespace(provider='opencode-go',
                                model='deepseek-v4.1-flash',
                                context_window=0)
        engine = self._engine()
        engine.model_target.return_value = (
            'opencode-go', '', 'deepseek-v4.1-flash')
        engine.models.find.return_value = entry
        engine.models.set_context_window.return_value = entry
        rc, out, _ = self._capture(
            self._args(action='context',
                       ref='opencode-go/deepseek-v4.1-flash',
                       tokens=1000000), engine)
        self.assertEqual(rc, 0)
        engine.models.set_context_window.assert_called_once_with(
            'opencode-go', 'deepseek-v4.1-flash', 1000000)
        self.assertIn('context budget 1,000,000 tokens', out)

    def test_models_bare_shows_context(self):
        e = SimpleNamespace(provider='ollama', model='deepseek',
                            context_window=1000000)
        engine = self._engine(models=[e], grouped=[('ollama', [e])])
        rc, out, _ = self._capture(self._args(), engine)
        self.assertEqual(rc, 0)
        self.assertIn('(ctx=1M)', out)

    def test_models_main_dispatch(self):
        e = SimpleNamespace(provider='ollama', model='llama3.2')
        engine = self._engine(models=[e], grouped=[('ollama', [e])])
        with patch('polyglav.cli.Engine', return_value=engine):
            out = io.StringIO()
            with patch('sys.stdout', new=out):
                rc = main(['models', '--path', self.path])
        self.assertEqual(rc, 0)
        self.assertIn('> llama3.2', out.getvalue())

    def test_models_list_main_dispatch(self):
        engine = self._engine(list_result=(['m1'], None))
        with patch('polyglav.cli.Engine', return_value=engine):
            out = io.StringIO()
            with patch('sys.stdout', new=out):
                rc = main(['models', '--path', self.path, 'list'])
        self.assertEqual(rc, 0)
        self.assertIn('1 models available from ollama', out.getvalue())
