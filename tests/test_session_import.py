import tempfile
import unittest
from pathlib import Path

from polyglav.sessions.manager import (Session, SessionManager,
                                       session_from_document)
from polyglav.sessions.render import export_document


class TestSessionFromDocument(unittest.TestCase):

    def _session(self):
        s = Session('orig', role='writer', mode='write', version='0.44.0',
                    session_id='ab12cd')
        s.add_user('hello')
        s.add_text('hi')
        s.end_turn('ok')
        s.add_error(0, 'boom')
        s.add_permission('run_command', 'ask', 'granted')
        return s

    def test_builds_session_from_export_document(self):
        loaded = session_from_document(export_document(self._session()))
        self.assertEqual(loaded.session_name, 'orig')
        self.assertEqual(loaded.session_id, 'ab12cd')
        self.assertEqual(loaded.role, 'writer')
        self.assertEqual(loaded.mode, 'write')
        self.assertEqual(loaded.version, '0.44.0')
        self.assertEqual(len(loaded.turns), 1)
        self.assertEqual(loaded.turns[0]['parts'][0]['text'], 'hello')
        self.assertEqual(loaded.errors[0]['message'], 'boom')
        self.assertEqual(loaded.permissions[0]['tool'], 'run_command')

    def test_accepts_raw_session_dict(self):
        loaded = session_from_document(self._session().to_dict())
        self.assertEqual(loaded.session_name, 'orig')

    def test_rejects_non_document(self):
        for value in ({'foo': 1}, [], 'nope'):
            with self.assertRaises(ValueError):
                session_from_document(value)

    def test_tolerates_missing_optionals(self):
        doc = {'info': {'session_name': 'x'}, 'turns': []}
        loaded = session_from_document(doc)
        self.assertEqual(loaded.session_name, 'x')
        self.assertEqual(loaded.errors, [])
        self.assertEqual(loaded.permissions, [])


class TestSessionManagerImport(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sm = SessionManager(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _doc(self):
        s = Session('orig')
        s.add_user('hello')
        s.end_turn('ok')
        return export_document(s)

    def test_import_keeps_original_name(self):
        s = self.sm.import_document(self._doc())
        self.assertEqual(s.session_name, 'orig')
        self.assertTrue((self.sm.sessions_dir / 'orig.json').exists())
        self.assertEqual(self.sm.read('orig').turns[0]['parts'][0]['text'],
                         'hello')

    def test_import_explicit_name(self):
        s = self.sm.import_document(self._doc(), name='custom')
        self.assertEqual(s.session_name, 'custom')
        self.assertTrue((self.sm.sessions_dir / 'custom.json').exists())

    def test_import_collision_generates_fresh_name(self):
        self.sm.import_document(self._doc())
        s = self.sm.import_document(self._doc())
        self.assertNotEqual(s.session_name, 'orig')
        self.assertTrue(s.session_name.startswith('ses_'))

    def test_import_explicit_collision_raises(self):
        self.sm.import_document(self._doc(), name='custom')
        with self.assertRaises(ValueError):
            self.sm.import_document(self._doc(), name='custom')

    def test_import_force_overwrites(self):
        self.sm.import_document(self._doc(), name='custom')
        doc = self._doc()
        doc['turns'][0]['parts'][0]['text'] = 'second'
        s = self.sm.import_document(doc, name='custom', force=True)
        self.assertEqual(s.session_name, 'custom')
        self.assertEqual(self.sm.read('custom').turns[0]['parts'][0]['text'],
                         'second')

    def test_import_does_not_switch_current(self):
        self.sm.create('active')
        current = self.sm.current
        self.sm.import_document(self._doc())
        self.assertIs(self.sm.current, current)


if __name__ == '__main__':
    unittest.main()
