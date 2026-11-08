import io
import json
import unittest
from unittest.mock import patch

from tests.helpers import make_chat


class TestObserver(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.events = []
        self.chat.add_observer(self.events.append)

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _run(self, side_effect, deny_tools=None):
        self.chat.provider.chat.side_effect = side_effect
        with patch('sys.stdout', new=io.StringIO()):
            return self.chat.chat('hello', deny_tools=deny_tools)

    def test_request_events_and_context_blocks(self):
        self._run([[
            {'type': 'token', 'content': 'hi'},
            {'type': 'done', 'reason': 'stop',
             'usage': {'prompt_tokens': 10, 'completion_tokens': 2,
                       'prompt_tokens_details': {'cached_tokens': 3}}},
        ]])
        starts = [e for e in self.events if e['type'] == 'request_start']
        ends = [e for e in self.events if e['type'] == 'request_end']
        self.assertEqual(len(starts), 1)
        self.assertEqual(len(ends), 1)
        self.assertTrue(any(b['kind'] == 'user' and b['content'] == 'hello'
                            for b in starts[0]['context_blocks']))
        self.assertEqual(ends[0]['input_tokens'], 10)
        self.assertEqual(ends[0]['cache_read_tokens'], 3)
        self.assertEqual(ends[0]['ctx_tokens'], 13)
        self.assertEqual(ends[0]['status'], 'done')

    def test_tool_end_event_and_result_tokens(self):
        self._run([
            [{'type': 'tool_calls', 'usage': {'prompt_tokens': 10},
              'tool_calls': [{
                  'id': 'call_1', 'type': 'function',
                  'function': {'name': 'list_dir',
                               'arguments': json.dumps({'path': '.'})},
              }]}],
            [{'type': 'token', 'content': 'done'},
             {'type': 'done', 'reason': 'stop'}],
        ])
        events = [e for e in self.events if e['type'] == 'tool_end']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['name'], 'list_dir')
        self.assertGreater(events[0]['result_tokens'], 0)
        self.assertIn('category', events[0])
        parts = [p for t in self.chat.current_session.turns
                 for p in t.get('parts') or [] if p['type'] == 'tool']
        self.assertIn('result_tokens', parts[0])

    def test_compaction_event(self):
        self.chat.config.set('compact_at', 1000)
        self.chat.config.set('compact_keep', 1)
        self.chat.current_session.add_user('old task')
        self.chat.current_session.add_text('old answer')
        self.chat.current_session.end_turn('ok')
        self.chat.provider.chat_nonstreaming.return_value = {
            'role': 'assistant', 'content': 'SUMMARY',
            'usage': {'prompt_tokens': 50, 'completion_tokens': 5}}
        self._run([
            [{'type': 'tool_calls',
              'usage': {'prompt_tokens': 200000, 'completion_tokens': 10},
              'tool_calls': [{
                  'id': 'call_1', 'type': 'function',
                  'function': {'name': 'list_dir',
                               'arguments': json.dumps({'path': '.'})},
              }]}],
            [{'type': 'token', 'content': 'done'},
             {'type': 'done', 'reason': 'stop'}],
        ])
        events = [e for e in self.events if e['type'] == 'compaction']
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]['auto'])
        self.assertEqual(events[0]['reason'], 'threshold')
        self.assertEqual(events[0]['usage']['prompt_tokens'], 50)
        before = [e for e in self.events if e['type'] == 'compaction_before']
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0]['compaction_index'],
                         events[0]['compaction_index'])

    def test_deny_tools_star_empties_schema_and_refuses_calls(self):
        self._run([
            [{'type': 'tool_calls', 'tool_calls': [{
                'id': 'call_1', 'type': 'function',
                'function': {'name': 'list_dir',
                             'arguments': json.dumps({'path': '.'})},
            }]}],
            [{'type': 'token', 'content': 'done'},
             {'type': 'done', 'reason': 'stop'}],
        ], deny_tools=['*'])
        self.assertEqual(
            self.chat.provider.chat.call_args.kwargs.get('tools'), [])
        parts = [p for t in self.chat.current_session.turns
                 for p in t.get('parts') or [] if p['type'] == 'tool']
        self.assertTrue(parts[0]['is_error'])
        self.assertIn('disabled for this turn', parts[0]['output'])

    def test_context_snapshot(self):
        self.chat.current_session.add_user('hello')
        snapshot = self.chat.context_snapshot()
        self.assertIn('messages', snapshot)
        self.assertTrue(any(b['kind'] == 'user' and b['content'] == 'hello'
                            for b in snapshot['blocks']))
        self.assertGreater(snapshot['tokens'], 0)

    def test_subagent_inherits_observers(self):
        sub = self.chat._new_sub_engine('', task='x')
        self.assertIn(self.events.append, sub._observers)


if __name__ == '__main__':
    unittest.main()
