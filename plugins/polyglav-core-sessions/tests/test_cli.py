import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from polyglav.main import main
from polyglav.sessions.manager import Session

_plugin_path = (Path(__file__).resolve().parents[1]
                / 'src' / 'plugin.py')
_spec = importlib.util.spec_from_file_location(
    'polyglav_core_sessions_plugin_cli_test', _plugin_path)
_sessions_plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sessions_plugin)
cmd_export = _sessions_plugin.cmd_export
cmd_import = _sessions_plugin.cmd_import


class TestCliExport(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name
        sessions = Path(self.path) / '.polyglav' / 'sessions'
        sessions.mkdir(parents=True, exist_ok=True)
        s = Session('alpha')
        s.add_user('hello')
        s.add_text('hi there')
        s.end_turn('ok')
        with open(sessions / 'alpha.json', 'w') as f:
            json.dump(s.to_dict(), f)

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, **kw):
        base = dict(name='alpha', out=None, path=self.path)
        base.update(kw)
        return SimpleNamespace(**base)

    def _capture(self, args):
        out = io.StringIO()
        err = io.StringIO()
        with patch('sys.stdout', new=out), patch('sys.stderr', new=err):
            rc = cmd_export(args)
        return rc, out.getvalue(), err.getvalue()

    def test_export_writes_default_file(self):
        rc, out, _ = self._capture(self._args())
        self.assertEqual(rc, 0)
        path = (Path(self.path) / '.polyglav' / 'exports' / 'alpha.md').resolve()
        self.assertTrue(path.exists())
        self.assertIn('# Session: alpha', path.read_text())
        self.assertIn(f'Exported session: alpha -> {path}', out)

    def test_export_stdout(self):
        rc, out, _ = self._capture(self._args(out='-'))
        self.assertEqual(rc, 0)
        self.assertIn('# Session: alpha', out)
        self.assertIn('hello', out)
        self.assertIn('hi there', out)

    def test_export_custom_out(self):
        target = Path(self.path) / 'out' / 'custom.md'
        rc, _, _ = self._capture(self._args(out=str(target)))
        self.assertEqual(rc, 0)
        self.assertTrue(target.exists())
        self.assertIn('# Session: alpha', target.read_text())

    def test_export_not_found(self):
        rc, _, err = self._capture(self._args(name='nosuch'))
        self.assertEqual(rc, 1)
        self.assertIn('Session not found: nosuch', err)

    def test_export_main_dispatch(self):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            rc = main(['export', 'alpha', '--path', self.path])
        self.assertEqual(rc, 0)
        self.assertIn('Exported session: alpha', out.getvalue())

    def test_export_json_writes_default_file(self):
        rc, out, _ = self._capture(self._args(json=True))
        self.assertEqual(rc, 0)
        path = (Path(self.path) / '.polyglav' / 'exports'
                / 'alpha.json').resolve()
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(data['info']['session_name'], 'alpha')
        self.assertIn(f'Exported session: alpha -> {path}', out)

    def test_export_json_stdout(self):
        rc, out, _ = self._capture(self._args(json=True, out='-'))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)['info']['session_name'], 'alpha')


class TestCliImport(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name
        sessions = Path(self.path) / '.polyglav' / 'sessions'
        sessions.mkdir(parents=True, exist_ok=True)
        s = Session('alpha')
        s.add_user('hello')
        s.add_text('hi')
        s.end_turn('ok')
        with open(sessions / 'alpha.json', 'w') as f:
            json.dump(s.to_dict(), f)
        export_document = _sessions_plugin.export_document
        self.out_file = Path(self.path) / 'export.json'
        self.out_file.write_text(json.dumps(export_document(s)))

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, **kw):
        base = dict(file=str(self.out_file), name='', force=False,
                    path=self.path)
        base.update(kw)
        return SimpleNamespace(**base)

    def _capture(self, args):
        out = io.StringIO()
        err = io.StringIO()
        with patch('sys.stdout', new=out), patch('sys.stderr', new=err):
            rc = cmd_import(args)
        return rc, out.getvalue(), err.getvalue()

    def test_import_round_trip(self):
        rc, out, _ = self._capture(self._args(name='beta'))
        self.assertEqual(rc, 0)
        self.assertIn('Imported session: ', out)
        path = Path(self.path) / '.polyglav' / 'sessions' / 'beta.json'
        self.assertTrue(path.exists())
        self.assertEqual(json.loads(path.read_text())['turns'][0]['parts'][0]['text'],
                         'hello')

    def test_import_missing_file(self):
        rc, _, err = self._capture(self._args(file='/no/such.json'))
        self.assertEqual(rc, 1)
        self.assertIn('Cannot read session file', err)

    def test_import_collision_errors(self):
        rc, _, err = self._capture(self._args(name='alpha'))
        self.assertEqual(rc, 1)
        self.assertIn('Session exists', err)

    def test_import_main_dispatch(self):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            rc = main(['import', str(self.out_file), '--name', 'beta',
                       '--path', self.path])
        self.assertEqual(rc, 0)
        self.assertIn('Imported session', out.getvalue())
