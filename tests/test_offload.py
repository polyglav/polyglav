import json
import unittest

from tests.helpers import make_chat


class TestOffloadTool(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat._init_tooling()
        self.sessions_dir = self.chat.config.local_path.parent / 'sessions'

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _tool_call(self, task='summarize the report'):
        return [{
            'id': 'call_offload001',
            'type': 'function',
            'function': {'name': 'offload',
                         'arguments': json.dumps({'task': task})},
        }]

    def test_registered_as_read_tool(self):
        schema = self.chat._init_tooling()
        names = [s['function']['name'] for s in schema]
        self.assertIn('offload', names)
        entry = self.chat._tool_registry.info('offload')
        self.assertEqual(entry['permission'], 'offload')
        self.assertTrue(self.chat._tool_policy.allowed('offload', 'offload'))

    def test_offload_runs_roleless_sibling(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'summary text'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        out = self.chat._run_tool('offload',
                                  {'task': 'summarize the report'})
        self.assertIn('[offload] summary text', out)
        self.assertEqual(len(list(self.sessions_dir.glob('sub_*.json'))), 1)

    def test_offload_depth_guard(self):
        self.chat._offload_depth = 1
        out = self.chat._run_tool('offload', {'task': 'again'})
        self.assertIn('depth limit', out)


if __name__ == '__main__':
    unittest.main()
