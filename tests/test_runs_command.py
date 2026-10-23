import io
import unittest
from unittest.mock import patch

from tests.helpers import make_chat


class TestRunsCommand(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def test_runs_tree_is_read_only(self):
        out = self._dispatch('/runs')
        self.assertIn('@ Runs', out)
        self.assertIn('#1 root', out)
        self.assertNotIn('↔ Switch', out)


if __name__ == '__main__':
    unittest.main()
