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

    def test_runs_show_duration_and_usage(self):
        run = self.chat.runs.start(role='writer', session='sub_test',
                                   parent=self.chat.current_run.id)
        self.chat.runs.finish(run.id, usage={'total_tokens': 45},
                              duration=1.2)
        out = self._dispatch('/runs')
        self.assertIn('writer', out)
        self.assertIn('1.2s', out)
        self.assertIn('45 tokens', out)


if __name__ == '__main__':
    unittest.main()
