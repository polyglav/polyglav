import json
import os
import tempfile
import unittest
from pathlib import Path

from polyglav.sessions.manager import SessionManager


class TestSessionIoLog(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sm = SessionManager(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _log_lines(self):
        path = self.sm.sessions_dir / 'errors.log'
        if not path.exists():
            return []
        return [line for line in path.read_text().splitlines() if line]

    def test_read_logs_corrupt_file(self):
        (self.sm.sessions_dir / 'broken.json').write_text('{not json')
        self.assertIsNone(self.sm.read('broken'))
        lines = self._log_lines()
        self.assertEqual(len(lines), 1)
        self.assertIn('read', lines[0])
        self.assertIn('broken', lines[0])

    def test_save_is_atomic_and_compact(self):
        session = self.sm.create('atomic')
        session.add_user('hello')
        self.sm.save(session)
        path = self.sm.sessions_dir / 'atomic.json'
        self.assertTrue(path.exists())
        self.assertFalse((self.sm.sessions_dir / 'atomic.json.tmp').exists())
        raw = path.read_text()
        self.assertNotIn('\n  ', raw)
        self.assertEqual(self.sm.read('atomic').turns[0]['parts'][0]['text'],
                         'hello')

    def test_unchanged_session_is_not_rewritten(self):
        from unittest.mock import patch
        session = self.sm.create('clean')
        session.add_user('hello')
        self.sm.save(session)
        with patch('polyglav.sessions.private.write_text') as write:
            self.sm.save(session)
        write.assert_not_called()
        session.add_user('again')
        with patch('polyglav.sessions.private.write_text') as write:
            self.sm.save(session)
        write.assert_called_once()

    def test_read_missing_file_not_logged(self):
        self.assertIsNone(self.sm.read('nope'))
        self.assertEqual(self._log_lines(), [])

    def test_read_legacy_format_not_logged(self):
        (self.sm.sessions_dir / 'legacy.json').write_text(
            json.dumps({'name': 'legacy', 'messages': []}))
        self.assertIsNone(self.sm.read('legacy'))
        self.assertEqual(self._log_lines(), [])

    def test_save_logs_write_failure(self):
        s = self.sm.create('cap')
        s.add_user('hi')
        (self.sm.sessions_dir / 'cap.json').mkdir()
        self.sm.save(s)
        lines = self._log_lines()
        self.assertTrue(any('save' in line and 'cap' in line
                            for line in lines))

    def test_errors_log_not_listed_as_session(self):
        (self.sm.sessions_dir / 'broken.json').write_text('{')
        self.sm.read('broken')
        self.assertNotIn('errors', self.sm.list())

    @unittest.skipIf(os.name == 'nt', 'POSIX file modes')
    def test_sessions_directory_is_private(self):
        mode = (self.sm.sessions_dir.stat().st_mode & 0o777)
        self.assertEqual(mode, 0o700)

    @unittest.skipIf(os.name == 'nt', 'POSIX file modes')
    def test_session_file_is_private(self):
        session = self.sm.create('private')
        session.add_user('hello')
        self.sm.save(session)
        path = self.sm.sessions_dir / 'private.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    @unittest.skipIf(os.name == 'nt', 'POSIX file modes')
    def test_errors_log_is_private(self):
        (self.sm.sessions_dir / 'broken.json').write_text('{not json')
        self.sm.read('broken')
        path = self.sm.sessions_dir / 'errors.log'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    @unittest.skipIf(os.name == 'nt', 'POSIX file modes')
    def test_summary_file_is_private(self):
        path = self.sm.write_summary('private', 'summary text')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)


if __name__ == '__main__':
    unittest.main()


class TestJsonlSessionStore(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.sm = SessionManager(self.dir, storage='jsonl')

    def tearDown(self):
        self._tmp.cleanup()

    def test_round_trip_and_no_json(self):
        session = self.sm.create('log')
        session.add_user('hello')
        session.add_text('world')
        session.end_turn('ok')
        self.sm.save(session)
        self.assertTrue((self.dir / 'log.jsonl').exists())
        self.assertFalse((self.dir / 'log.json').exists())
        loaded = SessionManager(self.dir, storage='jsonl').read('log')
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.turns[0]['parts'][0]['text'], 'hello')
        self.assertEqual(loaded.turns[0]['parts'][1]['text'], 'world')

    def test_team_round_trip(self):
        session = self.sm.create('log', role='researcher', team='docs')
        self.sm.save(session)
        loaded = SessionManager(self.dir).read('log')
        self.assertEqual(loaded.role, 'researcher')
        self.assertEqual(loaded.team, 'docs')

    def test_materialize_writes_json(self):
        session = self.sm.create('log')
        session.add_user('hello')
        session.end_turn('ok')
        self.sm.save(session)
        path = self.sm.materialize(session)
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        loaded = SessionManager(self.dir).read('log')
        self.assertEqual(loaded.turns[0]['parts'][0]['text'], 'hello')

    def test_paused_turn_restores_from_json(self):
        session = self.sm.create('log')
        session.add_user('one')
        session.open_turn()['status'] = 'paused'
        self.sm.save(session)
        loaded = SessionManager(self.dir).read('log')
        self.assertIsNotNone(loaded.open_turn())
        self.assertEqual(loaded.open_turn()['status'], 'paused')

    def test_append_after_new_turn(self):
        session = self.sm.create('log')
        session.add_user('one')
        session.end_turn('ok')
        self.sm.save(session)
        before = (self.dir / 'log.jsonl').read_text().count('\n')
        session.add_user('two')
        session.end_turn('ok')
        self.sm.save(session)
        after = (self.dir / 'log.jsonl').read_text().count('\n')
        self.assertGreater(after, before)
        loaded = self.sm.read('log')
        self.assertEqual(len(loaded.turns), 2)

    def test_paused_turn_restores_open(self):
        session = self.sm.create('log')
        session.add_user('one')
        session.open_turn()['status'] = 'paused'
        self.sm.save(session)
        loaded = self.sm.read('log')
        self.assertIsNotNone(loaded.open_turn())
        self.assertEqual(loaded.open_turn()['status'], 'paused')
