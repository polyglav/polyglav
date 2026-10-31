import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polyglav.sessions.manager import SessionManager


def _load_plugin(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


store_plugin = _load_plugin('polyglav_storage_sqlite', SRC / 'plugin.py')


class TestSQLiteStore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = store_plugin.SQLiteSessionStore(self.dir)
        self.manager = SessionManager(self.dir, storage='sqlite',
                                      store=self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip(self):
        session = self.manager.create('db')
        session.add_user('hello')
        session.end_turn('ok')
        self.manager.save(session)
        loaded = self.manager.read('db')
        self.assertEqual(loaded.turns[0]['parts'][0]['text'], 'hello')
        self.assertIn('db', self.manager.list())

    def test_delete(self):
        session = self.manager.create('db')
        session.add_user('hello')
        session.end_turn('ok')
        self.manager.save(session)
        self.assertTrue(self.manager.delete('db'))
        self.assertIsNone(self.manager.read('db'))
        self.assertEqual(self.manager.list(), [])

    def test_materialize(self):
        session = self.manager.create('db')
        session.add_user('hello')
        session.end_turn('ok')
        self.manager.save(session)
        path = self.manager.materialize(session)
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
