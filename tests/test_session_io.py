import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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

    def _aged_session(self, name, days):
        session = self.sm.create(name)
        session.add_user('hello')
        stamp = (datetime.now(timezone.utc) - timedelta(days=days))
        session.updated_at = stamp.isoformat(timespec='seconds')
        self.sm.save(session)
        self.sm.current = None
        return session

    def test_prune_dry_run_deletes_nothing(self):
        self._aged_session('old', 40)
        result = self.sm.prune(30, dry_run=True)
        self.assertEqual(result['removed'], 1)
        self.assertEqual(result['sessions'], ['old'])
        self.assertTrue(result['dry_run'])
        self.assertTrue((self.sm.sessions_dir / 'old.json').exists())

    def test_prune_removes_old_sessions(self):
        self._aged_session('old', 40)
        self._aged_session('fresh', 1)
        result = self.sm.prune(30)
        self.assertEqual(result['removed'], 1)
        self.assertEqual(result['sessions'], ['old'])
        self.assertFalse((self.sm.sessions_dir / 'old.json').exists())
        self.assertTrue((self.sm.sessions_dir / 'fresh.json').exists())

    def test_prune_removes_tool_log_and_summary(self):
        self._aged_session('old', 40)
        (self.sm.sessions_dir / 'old.tools.log').write_text('x')
        self.sm.write_summary('old', 'summary')
        self.sm.prune(30)
        self.assertFalse((self.sm.sessions_dir / 'old.tools.log').exists())
        self.assertFalse(self.sm.summary_path('old').exists())

    def test_prune_keeps_current_session(self):
        self.sm.current = self._aged_session('current', 40)
        result = self.sm.prune(30)
        self.assertEqual(result['removed'], 0)
        self.assertTrue((self.sm.sessions_dir / 'current.json').exists())

    def test_prune_counts_bytes(self):
        self._aged_session('old', 40)
        result = self.sm.prune(30)
        self.assertGreater(result['bytes'], 0)

    def test_prune_rejects_non_integer_age(self):
        with self.assertRaises(ValueError):
            self.sm.prune('soon')


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
