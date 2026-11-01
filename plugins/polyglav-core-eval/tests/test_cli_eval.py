import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from polyglav.config import DEFAULT_CONFIG
from polyglav.main import main


def _factory(rounds):
    def _f(**kwargs):
        p = MagicMock()
        p.chat.side_effect = rounds
        return p
    _f.DEFAULT_BASE_URL = 'https://fake.api.com'
    _f.DEFAULT_MODEL = 'fake-model'
    _f.HOST_PATTERNS = ('ollama.com', 'fake.api.com')
    return _f


class TestCliEval(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name
        self._prev = None
        from polyglav.config import Config, DEFAULT_CONFIG
        self._prev = Config.GLOBAL_DIR
        Config.GLOBAL_DIR = Path(self.path) / 'home'
        config_dir = Path(self.path) / '.polyglav'
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / 'config.json').write_text(json.dumps({
            'plugins': list(DEFAULT_CONFIG['plugins']) + [
                'polyglav-core-eval']}))

    def tearDown(self):
        from polyglav.config import Config
        Config.GLOBAL_DIR = self._prev
        import shutil
        shutil.rmtree(self.path, ignore_errors=True)

    def _fixture(self, **data):
        eval_dir = Path(self.path) / '.polyglav' / 'eval'
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / 't.json').write_text(json.dumps(data))

    def test_eval_list(self):
        self._fixture(task='List the directory', expected=['list_dir'])
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            rc = main(['eval', '--path', self.path, 'list'])
        self.assertEqual(rc, 0)
        self.assertIn('t - List the directory', out.getvalue())

    def test_eval_run_table(self):
        self._fixture(task='List the directory', expected=['list_dir'],
                      verifier={'exact': ['list_dir']})
        rounds = [
            [{'type': 'tool_calls', 'tool_calls': [
                {'id': 'c1', 'type': 'function',
                 'function': {'name': 'list_dir',
                              'arguments': json.dumps({'path': '.'})}},
            ]}],
            [{'type': 'token', 'content': 'ok'},
             {'type': 'done', 'reason': 'stop',
              'usage': {'prompt_tokens': 4, 'completion_tokens': 1}}],
        ]
        with patch('polyglav.providers.PROVIDERS', {'ollama': _factory(rounds)}):
            out = io.StringIO()
            with patch('sys.stdout', new=out):
                rc = main(['eval', '--path', self.path, 'run', '--fixture', 't'])
        self.assertEqual(rc, 0)
        self.assertIn('accuracy 1.00', out.getvalue())
        self.assertIn('t', out.getvalue())

    def test_eval_run_json_output(self):
        self._fixture(task='List the directory', expected=['list_dir'])
        rounds = [
            [{'type': 'tool_calls', 'tool_calls': [
                {'id': 'c1', 'type': 'function',
                 'function': {'name': 'list_dir',
                              'arguments': json.dumps({'path': '.'})}},
            ]}],
            [{'type': 'token', 'content': 'ok'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        with patch('polyglav.providers.PROVIDERS', {'ollama': _factory(rounds)}):
            out = io.StringIO()
            with patch('sys.stdout', new=out):
                rc = main(['eval', '--path', self.path, 'run', '--fixture', 't',
                           '--output', 'json'])
        self.assertEqual(rc, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data['summary']['fixtures'], 1)
        self.assertEqual(data['results'][0]['names'], ['list_dir'])

    def test_eval_run_no_fixtures_errors(self):
        err = io.StringIO()
        with patch('sys.stderr', new=err):
            out = io.StringIO()
            with patch('sys.stdout', new=out):
                rc = main(['eval', '--path', self.path, 'run', '--fixture', 'zz'])
        self.assertEqual(rc, 1)
        self.assertIn('No eval fixtures found', err.getvalue())
