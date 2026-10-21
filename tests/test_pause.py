import io
import unittest
from unittest.mock import MagicMock, patch

from tests.helpers import make_chat


class TestPauseResume(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat.chat = MagicMock()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def test_pause_and_resume_state(self):
        out = self._dispatch('/pause')
        self.assertTrue(self.chat._paused)
        self.assertIn('@ Paused #1 root', out)
        out = self._dispatch('/resume')
        self.assertFalse(self.chat._paused)
        self.assertIn('@ Resumed #1 root', out)

    def test_paused_turn_is_skipped(self):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            with patch('polyglav.chat.input',
                       side_effect=['/pause', 'hello', EOFError]):
                with patch('polyglav.chat.readline'):
                    self.chat.run()
        self.chat.chat.assert_not_called()
        self.assertIn('@ Paused #1 root', out.getvalue())


if __name__ == '__main__':
    unittest.main()
