import unittest

from tests.helpers import make_chat


class TestDelegateTool(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat._init_tooling()
        self.sessions_dir = self.chat.config.local_path.parent / 'sessions'

    def tearDown(self):
        self.chat._tmp.cleanup()

    def test_registered_as_read_tool(self):
        schema = self.chat._init_tooling()
        names = [s['function']['name'] for s in schema]
        self.assertIn('delegate', names)
        self.assertNotIn('offload', names)
        entry = self.chat._tool_registry.info('delegate')
        self.assertEqual(entry['permission'], 'delegate')
        self.assertTrue(self.chat._tool_policy.allowed('delegate', 'delegate'))

    def test_delegate_runs_roleless_sibling(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'summary text'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        out = self.chat._run_tool('delegate',
                                  {'task': 'summarize the report'})
        self.assertIn('[delegate] summary text', out)
        self.assertEqual(len(list(self.sessions_dir.glob('sub_*.json'))), 1)

    def test_delegate_depth_guard(self):
        self.chat._delegate_depth = 1
        out = self.chat._run_tool('delegate', {'task': 'again'})
        self.assertIn('depth limit', out)

    def test_call_rejects_sibling_target(self):
        out = self.chat._run_tool('call', {'target': 'sibling', 'task': 'x'})
        self.assertIn('disabled by tool policy', out)


if __name__ == '__main__':
    unittest.main()
