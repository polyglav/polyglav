import json
import unittest

from polyglav.sessions import turns


class TestTurnBuilders(unittest.TestCase):

    def test_new_turn_shape(self):
        turn = turns.new_turn(3, model='m', provider='p', mode='build')
        self.assertEqual(turn['index'], 3)
        self.assertEqual(turn['status'], 'running')
        self.assertEqual(turn['ended_at'], '')
        self.assertEqual(turn['parts'], [])
        self.assertEqual(turn['model'], 'm')
        self.assertEqual(turn['provider'], 'p')
        self.assertEqual(turn['mode'], 'build')
        self.assertTrue(turn['started_at'])

    def test_finish_turn(self):
        turn = turns.new_turn(1)
        turns.finish_turn(turn, 'error')
        self.assertEqual(turn['status'], 'error')
        self.assertTrue(turn['ended_at'])

    def test_part_builders(self):
        for part, kind in (
            (turns.user_part('hi'), 'user'),
            (turns.text_part('out'), 'text'),
            (turns.thinking_part('hmm'), 'thinking'),
            (turns.system_part('ctx'), 'system'),
        ):
            self.assertEqual(part['type'], kind)
            self.assertTrue(part['timestamp'])
        self.assertEqual(turns.user_part('hi')['text'], 'hi')

    def test_command_and_tool_parts(self):
        cmd = turns.command_part('/compact', summary='sum', compact_from=2)
        self.assertEqual(cmd['type'], 'command')
        self.assertEqual(cmd['summary'], 'sum')
        self.assertEqual(cmd['compact_from'], 2)
        part = turns.tool_part('web_search', input={'q': 'x'})
        self.assertEqual(part['type'], 'tool')
        self.assertEqual(part['name'], 'web_search')
        self.assertEqual(part['input'], {'q': 'x'})
        self.assertEqual(part['output'], '')
        self.assertFalse(part['is_error'])

    def test_add_and_finish_tool(self):
        turn = turns.new_turn(1)
        part = turns.add_part(turn, turns.tool_part('read'))
        self.assertEqual(turn['parts'], [part])
        turns.finish_tool(part, 'content', analysis='insight')
        self.assertEqual(part['output'], 'content')
        self.assertEqual(part['analysis'], 'insight')
        self.assertFalse(part['is_error'])


class TestTurnToProvider(unittest.TestCase):

    def _turn(self, *parts):
        turn = turns.new_turn(1)
        for p in parts:
            turns.add_part(turn, p)
        return turn

    def test_user_and_text(self):
        turn = self._turn(turns.user_part('hi'), turns.text_part('hello'))
        out = turns.turn_to_provider(turn)
        self.assertEqual(out[0], {'role': 'user', 'content': 'hi'})
        self.assertEqual(out[1], {'role': 'assistant', 'content': 'hello'})

    def test_thinking_attaches_to_answer(self):
        turn = self._turn(turns.user_part('hi'),
                          turns.thinking_part('reason'),
                          turns.text_part('hello'))
        out = turns.turn_to_provider(turn)
        self.assertEqual(out[1]['thinking'], 'reason')
        self.assertEqual(out[1]['content'], 'hello')

    def test_reasoning_only_turn(self):
        turn = self._turn(turns.user_part('hi'), turns.thinking_part('reason'))
        out = turns.turn_to_provider(turn)
        self.assertEqual(out[1]['role'], 'assistant')
        self.assertEqual(out[1]['content'], '')
        self.assertEqual(out[1]['thinking'], 'reason')

    def test_tool_only_turn_has_empty_content(self):
        turn = self._turn(
            turns.user_part('q'),
            turns.tool_part('file_write', input={'path': 'a.py'},
                            output='Created a.py'),
        )
        out = turns.turn_to_provider(turn)
        call = out[1]
        self.assertEqual(call['role'], 'assistant')
        self.assertEqual(call['content'], '')
        self.assertIsNotNone(call['content'])
        self.assertEqual(out[2]['role'], 'tool')

    def test_no_assistant_message_has_null_content(self):
        turn = self._turn(
            turns.user_part('q'),
            turns.thinking_part('reason'),
            turns.tool_part('read', input={'path': 'a.py'}, output='body'),
        )
        for message in turns.turn_to_provider(turn):
            if message['role'] == 'assistant':
                self.assertIsNotNone(message.get('content'))

    def test_text_tool_call_result_then_answer(self):
        turn = self._turn(
            turns.user_part('search'),
            turns.thinking_part('need data'),
            turns.text_part('Looking it up'),
            turns.tool_part('web_search', input={'q': 'x'}, output='results'),
            turns.tool_part('web_fetch', input={'id': 1}, output='page'),
            turns.text_part('Here is the answer'),
        )
        out = turns.turn_to_provider(turn)
        self.assertEqual(out[0]['role'], 'user')
        call = out[1]
        self.assertEqual(call['role'], 'assistant')
        self.assertEqual(call['content'], 'Looking it up')
        self.assertEqual(call['thinking'], 'need data')
        self.assertEqual([c['function']['name'] for c in call['tool_calls']],
                         ['web_search', 'web_fetch'])
        self.assertEqual(out[2]['role'], 'tool')
        self.assertEqual(out[2]['content'], 'results')
        self.assertEqual(out[2]['tool_call_id'],
                         call['tool_calls'][0]['id'])
        self.assertEqual(out[3]['role'], 'tool')
        self.assertEqual(out[4], {'role': 'assistant',
                                  'content': 'Here is the answer'})

    def test_tool_arguments_serialized(self):
        turn = self._turn(
            turns.user_part('q'),
            turns.tool_part('grep', input={'pattern': 'x', 'n': 2}),
        )
        out = turns.turn_to_provider(turn)
        args = out[1]['tool_calls'][0]['function']['arguments']
        self.assertEqual(json.loads(args), {'pattern': 'x', 'n': 2})

    def test_tool_arguments_string_passthrough(self):
        turn = self._turn(
            turns.user_part('q'),
            turns.tool_part('grep', input='{"pattern": "x"}'),
        )
        out = turns.turn_to_provider(turn)
        self.assertEqual(out[1]['tool_calls'][0]['function']['arguments'],
                         '{"pattern": "x"}')

    def test_tool_call_ids_are_stable(self):
        turn = self._turn(
            turns.user_part('q'),
            turns.tool_part('read', input={'p': 'a'}),
            turns.tool_part('read', input={'p': 'b'}),
        )
        first = turns.turn_to_provider(turn)
        second = turns.turn_to_provider(turn)
        self.assertEqual([c['id'] for c in first[1]['tool_calls']],
                         [c['id'] for c in second[1]['tool_calls']])
        self.assertNotEqual(first[1]['tool_calls'][0]['id'],
                            first[1]['tool_calls'][1]['id'])

    def test_command_part_dropped(self):
        turn = self._turn(turns.user_part('q'),
                          turns.command_part('/model x'))
        out = turns.turn_to_provider(turn)
        self.assertEqual([m['role'] for m in out], ['user'])

    def test_system_passthrough(self):
        turn = self._turn(turns.system_part('search context'),
                          turns.user_part('q'))
        out = turns.turn_to_provider(turn)
        self.assertEqual(out[0], {'role': 'system',
                                  'content': 'search context'})
        self.assertEqual(out[1]['role'], 'user')


class TestProviderMessages(unittest.TestCase):

    def _turns(self):
        one = turns.new_turn(1)
        turns.add_part(one, turns.user_part('old question'))
        turns.add_part(one, turns.text_part('old answer'))
        two = turns.new_turn(2)
        turns.add_part(two, turns.command_part(
            '/compact', summary='THE SUMMARY', compact_from=2))
        three = turns.new_turn(3)
        turns.add_part(three, turns.user_part('new question'))
        turns.add_part(three, turns.text_part('new answer'))
        return [one, two, three]

    def test_compaction_boundary(self):
        ts = self._turns()
        summary, boundary = turns.compaction(ts)
        self.assertEqual(summary, 'THE SUMMARY')
        self.assertEqual(boundary, 2)

    def test_provider_messages_starts_at_boundary(self):
        out = turns.provider_messages(self._turns())
        self.assertEqual(out[0]['role'], 'system')
        self.assertIn('THE SUMMARY', out[0]['content'])
        self.assertEqual(out[1], {'role': 'user', 'content': 'new question'})
        self.assertEqual(out[2], {'role': 'assistant', 'content': 'new answer'})
        self.assertEqual(len(out), 3)

    def test_no_compaction_passes_all_turns(self):
        one = turns.new_turn(1)
        turns.add_part(one, turns.user_part('q'))
        turns.add_part(one, turns.text_part('a'))
        out = turns.provider_messages([one])
        self.assertEqual(out, [{'role': 'user', 'content': 'q'},
                               {'role': 'assistant', 'content': 'a'}])


if __name__ == '__main__':
    unittest.main()
