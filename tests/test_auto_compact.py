import io
import json
import unittest
from unittest.mock import patch

from tests.helpers import make_chat


class TestCompactLimit(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def test_absolute_limit(self):
        self.chat.config.set('compact_at', 170000)
        self.assertEqual(self.chat._compact_limit(), 170000)

    def test_relative_limit_uses_context_window(self):
        self.chat.config.set('compact_at', 0.85)
        self.chat.config.set('context_window', 200000)
        self.assertEqual(self.chat._compact_limit(), 170000)

    def test_relative_limit_uses_model_entry(self):
        self.chat.models.put('ollama', 'test-model')
        self.chat.models.set_context_window('ollama', 'test-model', 100000)
        self.chat.config.set('compact_at', 0.8)
        self.assertEqual(self.chat._compact_limit(), 80000)

    def test_relative_limit_without_window_is_off(self):
        self.chat.config.set('compact_at', 0.85)
        self.chat.config.set('context_window', 0)
        self.assertEqual(self.chat._compact_limit(), 0)

    def test_one_is_ambiguous(self):
        self.chat.config.set('compact_at', 1)
        self.assertEqual(self.chat._compact_limit(), 0)

    def test_zero_disables(self):
        self.chat.config.set('compact_at', 0)
        self.assertEqual(self.chat._compact_limit(), 0)


class TestAutoCompaction(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat.config.set('compact_at', 1000)
        self.chat.config.set('compact_keep', 1)

    def tearDown(self):
        self.chat._tmp.cleanup()

    def test_average_round_weight(self):
        self.chat._round_weights = [10000, 20000, 30000]
        self.chat.config.set('compact_before', 3)
        self.assertEqual(self.chat._average_round_weight(), 20000)

    def test_projection_triggers_before_limit(self):
        self.chat.config.set('compact_at', 100000)
        self.chat.config.set('compact_before', 3)
        self.chat._round_weights = [20000, 20000, 20000]
        self.assertTrue(
            self.chat._auto_compact_due({'context_tokens': 90000}))
        self.assertFalse(
            self.chat._auto_compact_due({'context_tokens': 70000}))

    def test_compact_before_zero_disables_projection(self):
        self.chat.config.set('compact_at', 100000)
        self.chat.config.set('compact_before', 0)
        self.chat._round_weights = [20000, 20000, 20000]
        self.assertFalse(
            self.chat._auto_compact_due({'context_tokens': 90000}))

    def test_compact_history_reads_turn_context(self):
        session = self.chat.current_session
        for value in (10000, 30000, 60000):
            session.add_user('msg')
            session.add_text('answer')
            session.end_turn('ok', context_tokens=value)
        weights, last = self.chat._compact_history()
        self.assertEqual(weights, [20000, 30000])
        self.assertEqual(last, 60000)

    def test_intra_turn_compaction_keeps_last_round(self):
        session = self.chat.current_session
        session.add_user('task')
        session.add_thinking('think 1')
        first = session.add_tool('list_dir', {'path': 'a'}, call_id='c1')
        from polyglav.sessions import turns as turn_parts
        turn_parts.finish_tool(first, 'A')
        session.add_thinking('think 2')
        second = session.add_tool('list_dir', {'path': 'b'}, call_id='c2')
        turn_parts.finish_tool(second, 'B')
        self.chat.provider.chat_nonstreaming.return_value = {
            'role': 'assistant', 'content': 'SUMMARY', 'tool_calls': None}
        with patch('sys.stdout', new=io.StringIO()):
            self.assertTrue(self.chat.compact_session(auto=True))
        record = session.turns[-1]['parts'][0]
        self.assertEqual(record['compact_from'], 1)
        self.assertEqual(record['compact_from_part'], 4)
        msgs = self.chat._provider_messages()
        self.assertIn('SUMMARY', msgs[0]['content'])
        contents = [m.get('content') for m in msgs]
        self.assertIn('task', contents)
        self.assertIn('B', contents)
        calls = [m for m in msgs if m.get('tool_calls')]
        self.assertEqual(calls[-1]['tool_calls'][0]['function']['name'],
                         'list_dir')

    def _prior_turn(self):
        self.chat.current_session.add_user('old task')
        self.chat.current_session.add_text('old answer')
        self.chat.current_session.end_turn('ok')

    def _tool_round(self, prompt_tokens=200000):
        return [{
            'type': 'tool_calls',
            'usage': {'prompt_tokens': prompt_tokens,
                      'completion_tokens': 10},
            'tool_calls': [{
                'id': 'call_1', 'type': 'function',
                'function': {'name': 'list_dir',
                             'arguments': json.dumps({'path': '.'})},
            }],
        }]

    def test_triggers_after_tool_round(self):
        self._prior_turn()
        self.chat.provider.chat.side_effect = [
            self._tool_round(),
            [{'type': 'token', 'content': 'done'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self.chat.provider.chat_nonstreaming.return_value = {
            'role': 'assistant', 'content': 'SUMMARY', 'tool_calls': None}
        with patch('sys.stdout', new=io.StringIO()):
            result = self.chat.chat('new task')
        self.assertEqual(result.status, 'ok')
        self.chat.provider.chat_nonstreaming.assert_called_once()
        record = self.chat.current_session.turns[-1]['parts'][0]
        self.assertEqual(record['text'], '/compact')
        self.assertEqual(record['summary'], 'SUMMARY')

    def test_failed_summary_is_not_retried(self):
        self._prior_turn()
        self.chat.provider.chat.side_effect = [
            self._tool_round(),
            self._tool_round(),
            [{'type': 'token', 'content': 'done'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self.chat.provider.chat_nonstreaming.return_value = {
            'error': {'code': 500, 'message': 'no summary'}}
        with patch('sys.stdout', new=io.StringIO()):
            self.chat.chat('new task')
        self.assertEqual(self.chat.provider.chat_nonstreaming.call_count, 1)

    def test_disabled_does_not_summarize(self):
        self.chat.config.set('compact_auto', False)
        self._prior_turn()
        self.chat.provider.chat.side_effect = [
            self._tool_round(),
            [{'type': 'token', 'content': 'done'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        with patch('sys.stdout', new=io.StringIO()):
            self.chat.chat('new task')
        self.chat.provider.chat_nonstreaming.assert_not_called()


if __name__ == '__main__':
    unittest.main()
