import unittest
import io
from unittest.mock import patch

from tests.helpers import make_chat


class TestToolCalling(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _make_tool_call(self, name='web_search', args='{"query": "test"}'):
        return [{
            'id': 'call_test123',
            'type': 'function',
            'function': {'name': name, 'arguments': args},
        }]

    def _run(self):
        with patch('sys.stdout', new=io.StringIO()):
            self.chat._agent_loop()

    def _texts(self):
        return [p['text'] for t in self.chat.current_session.turns
                for p in t.get('parts') or [] if p['type'] == 'text']

    def _tool_msgs(self):
        return [p for t in self.chat.current_session.turns
                for p in t.get('parts') or [] if p['type'] == 'tool']

    def _search_service(self):
        return self.chat._plugin_manager.service('search')

    def test_single_tool_then_final(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._make_tool_call()}],
            [
                {'type': 'token', 'content': 'Final answer.'},
                {'type': 'done', 'reason': 'stop'},
            ],
        ]
        with patch.object(self._search_service(), 'search', return_value=[
            {'title': 'T', 'url': 'http://x.com', 'snippet': 'S'}
        ]):
            self._run()

        self.assertEqual(self.chat.provider.chat.call_count, 2)
        self.chat._show_tool_status.assert_called_once()
        self.chat.session_auto_save.assert_called()
        self.assertEqual(len(self._tool_msgs()), 1)
        self.assertEqual(self._texts()[-1], 'Final answer.')

    def test_multiple_tool_calls(self):
        tool_calls = [
            {'id': 'call_001', 'type': 'function', 'function': {'name': 'web_search', 'arguments': '{"query": "python"}'}},
            {'id': 'call_002', 'type': 'function', 'function': {'name': 'web_search', 'arguments': '{"query": "rust"}'}},
        ]
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': tool_calls}],
            [
                {'type': 'token', 'content': 'Combined answer.'},
                {'type': 'done', 'reason': 'stop'},
            ],
        ]
        with patch.object(self._search_service(), 'search', return_value=[
            {'title': 'T', 'url': 'http://x.com', 'snippet': 'S'}
        ]):
            self._run()

        self.assertEqual(self.chat._show_tool_status.call_count, 2)
        self.assertEqual(len(self._tool_msgs()), 2)
        self.assertEqual(self._texts()[-1], 'Combined answer.')

    def test_unknown_tool_returns_error(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._make_tool_call(name='nonexistent')}],
            [
                {'type': 'token', 'content': 'Recovered.'},
                {'type': 'done', 'reason': 'stop'},
            ],
        ]
        self._run()

        tool_msgs = self._tool_msgs()
        self.assertEqual(len(tool_msgs), 1)
        self.assertIn('unknown tool', tool_msgs[0]['output'].lower())
        self.assertEqual(self._texts()[-1], 'Recovered.')

    def test_query_refine_on_short_query(self):
        self.chat.config.set('query_refine', True)
        self.chat.config.set('query_refine_min_words', 3)
        self.chat._refine_query = unittest.mock.MagicMock(return_value='latest AI news')
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._make_tool_call(args='{"query": "ai"}')}],
            [
                {'type': 'token', 'content': 'Done.'},
                {'type': 'done', 'reason': 'stop'},
            ],
        ]
        with patch.object(self._search_service(), 'search', return_value=[
            {'title': 'T', 'url': 'http://x.com', 'snippet': 'S'}
        ]) as search_mock:
            self._run()

        self.chat._refine_query.assert_called_once_with('ai')
        search_mock.assert_called_once_with('latest AI news')
        self.assertEqual(self._texts()[-1], 'Done.')

    def test_shown_thinking_streams_and_summarizes(self):
        self.chat.config.data['show_thinking'] = True
        self.chat.provider.chat.side_effect = [
            [{'type': 'thinking', 'content': 'reasoning...'},
             {'type': 'token', 'content': 'Visible'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        buf = io.StringIO()
        with patch('sys.stdout', new=buf):
            self.chat._agent_loop()
        out = buf.getvalue()
        self.assertIn('✓ Thought', out)
        self.assertIn('reasoning...', out)
        self.assertIn('Visible', out)

    def test_hidden_thinking_announces_duration_only(self):
        self.chat.config.data['show_thinking'] = False
        self.chat.provider.chat.side_effect = [
            [{'type': 'thinking', 'content': 'secret reasoning'},
             {'type': 'token', 'content': 'Visible'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        buf = io.StringIO()
        with patch('sys.stdout', new=buf):
            self.chat._agent_loop()
        out = buf.getvalue()
        self.assertNotIn('secret reasoning', out)
        self.assertRegex(out, r'✓ Thought \d+\.\ds')
        self.assertIn('Visible', out)


if __name__ == '__main__':
    unittest.main()
