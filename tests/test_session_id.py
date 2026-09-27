import tempfile
import unittest
from pathlib import Path

from polyglav.runs import RunRegistry
from polyglav.sessions.manager import (SESSION_ID_LEN, Session, SessionManager,
                                     coded_session_name, session_id_from_name,
                                     session_id_hash)
from tests.helpers import make_chat


class TestSessionId(unittest.TestCase):

    def test_deterministic_and_short(self):
        session_id = session_id_hash('ses_20260915_120000', 'assistant')
        self.assertEqual(session_id,
                         session_id_hash('ses_20260915_120000', 'assistant'))
        self.assertEqual(len(session_id), SESSION_ID_LEN)
        self.assertTrue(all(c in '0123456789abcdefghijklmnopqrstuvwxyz'
                            for c in session_id))

    def test_different_parts_differ(self):
        self.assertNotEqual(session_id_hash('a'), session_id_hash('b'))

    def test_custom_length(self):
        self.assertEqual(len(session_id_hash('a', length=10)), 10)

    def test_session_stores_id_and_round_trips(self):
        s = Session('ses_20260915_120000_ab12cd', session_id='ab12cd')
        self.assertEqual(s.session_id, 'ab12cd')
        restored = Session.from_dict(s.to_dict())
        self.assertEqual(restored.session_id, 'ab12cd')

    def test_missing_id_loads_empty(self):
        data = Session('legacy').to_dict()
        data.pop('session_id')
        self.assertEqual(Session.from_dict(data).session_id, '')

    def test_create_mints_embedded_id(self):
        manager = SessionManager(Path(tempfile.mkdtemp()))
        s = manager.create(role='assistant')
        self.assertTrue(s.session_name.startswith('ses_'))
        self.assertTrue(s.session_name.endswith(f'_{s.session_id}'))
        self.assertEqual(len(s.session_id), SESSION_ID_LEN)

    def test_create_mints_unique_ids(self):
        manager = SessionManager(Path(tempfile.mkdtemp()))
        ids = {manager.create(role='assistant').session_id for _ in range(20)}
        self.assertEqual(len(ids), 20)

    def test_explicit_name_has_no_id(self):
        manager = SessionManager(Path(tempfile.mkdtemp()))
        s = manager.create('myname')
        self.assertEqual(s.session_name, 'myname')
        self.assertEqual(s.session_id, '')

    def test_find_by_session_id(self):
        manager = SessionManager(Path(tempfile.mkdtemp()))
        s = manager.create(role='assistant')
        manager.save(s)
        found = manager.find_by_session_id(s.session_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.session_name, s.session_name)

    def test_session_id_from_name_parses_coded_session_names(self):
        self.assertEqual(
            session_id_from_name('ses_20260915_120000_ab12cd'), 'ab12cd')
        self.assertEqual(
            session_id_from_name('job_20260915_120000_ab12cd'), 'ab12cd')
        self.assertEqual(
            session_id_from_name('sub_20260915_120000_ab12cd'), 'ab12cd')

    def test_session_id_from_name_ignores_uncoded_session_names(self):
        self.assertEqual(session_id_from_name(''), '')
        self.assertEqual(session_id_from_name('myname'), '')
        self.assertEqual(session_id_from_name('agent_writer'), '')
        self.assertEqual(session_id_from_name('sub_thesis__writer'), '')
        self.assertEqual(session_id_from_name('ses_20260915_120000_slug'), '')

    def test_coded_session_name_round_trips_id(self):
        name = coded_session_name('ses', 'assistant')
        session_id = session_id_from_name(name)
        self.assertEqual(len(session_id), SESSION_ID_LEN)
        self.assertTrue(name.endswith(f'_{session_id}'))

    def test_find_by_session_id_normalizes_and_misses(self):
        manager = SessionManager(Path(tempfile.mkdtemp()))
        s = manager.create(role='assistant')
        manager.save(s)
        self.assertIsNotNone(manager.find_by_session_id(s.session_id.upper()))
        self.assertIsNone(manager.find_by_session_id('zzzzzz'))
        self.assertIsNone(manager.find_by_session_id(''))


class TestRunRegistrySessionId(unittest.TestCase):

    def test_start_stores_session_id(self):
        reg = RunRegistry()
        run = reg.start(role='assistant', session='ses_x', session_id='ab12cd')
        self.assertEqual(run.session_id, 'ab12cd')

    def test_find_by_session_id(self):
        reg = RunRegistry()
        reg.start(role='assistant', session='ses_x', session_id='ab12cd')
        reg.start(role='writer', session='ses_y', session_id='cd34ef')
        self.assertEqual(reg.find_by_session_id('CD34EF').role, 'writer')
        self.assertIsNone(reg.find_by_session_id('nope'))
        self.assertIsNone(reg.find_by_session_id(''))


class TestEngineSessionId(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def test_run_mirrors_session_id(self):
        self.assertEqual(self.chat.current_run.session_id,
                         self.chat.current_session.session_id)

    def test_load_or_create_syncs_run_session_id(self):
        self.chat.load_or_create_session('foo')
        self.assertEqual(self.chat.current_session.session_id, '')
        self.assertEqual(self.chat.current_run.session_id, '')
        self.assertEqual(self.chat.current_run.session, 'foo')

    def test_load_or_create_auto_syncs_run_session_id(self):
        self.chat.load_or_create_session(None)
        self.assertEqual(self.chat.current_run.session_id,
                         self.chat.current_session.session_id)
        self.assertTrue(self.chat.current_session.session_id)

    def test_turns_do_not_change_session_id(self):
        s = self.chat.sessions.create(role='assistant')
        session_id = s.session_id
        self.chat.sessions.save(s)
        s.add_user('hi')
        s.add_text('yo')
        s.end_turn('ok')
        self.chat.sessions.save(s)
        self.assertEqual(s.session_id, session_id)
        found = self.chat.sessions.find_by_session_id(session_id)
        self.assertIsNotNone(found)
        self.assertEqual(len(found.turns), 1)


if __name__ == '__main__':
    unittest.main()
