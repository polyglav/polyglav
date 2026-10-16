import json
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


if __name__ == '__main__':
    unittest.main()
