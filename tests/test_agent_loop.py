import unittest
import io
import json
from unittest.mock import patch

from tests.helpers import make_chat


class TestAgentLoop(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _run(self):
        with patch('sys.stdout', new=io.StringIO()):
            self.chat._agent_loop()

    def _parts(self, kind):
        return [p for t in self.chat.current_session.turns
                for p in t.get('parts') or [] if p['type'] == kind]

    def _texts(self):
        return [p['text'] for p in self._parts('text')]

    def test_no_tools_single_round_trip(self):
        self.chat.provider.chat.return_value = [
            {'type': 'token', 'content': 'Hello world'},
            {'type': 'done', 'reason': 'stop'},
        ]
        self._run()
        self.chat.provider.chat.assert_called_once()
        self.assertEqual(self._texts(), ['Hello world'])
        self.chat.session_auto_save.assert_called()

    def test_thinking_persisted_as_metadata_not_content(self):
        self.chat.provider.chat.return_value = [
            {'type': 'thinking', 'content': 'reasoning...'},
            {'type': 'token', 'content': 'Answer'},
            {'type': 'done', 'reason': 'stop'},
        ]
        self._run()
        self.assertEqual(self._texts(), ['Answer'])
        self.assertEqual([p['text'] for p in self._parts('thinking')],
                         ['reasoning...'])

    def test_error_bails_gracefully_and_is_persisted(self):
        self.chat.provider.chat.return_value = [
            {'type': 'error', 'code': 401, 'message': 'Unauthorized'},
        ]
        self._run()
        self.assertEqual(self._texts(), [])
        self.chat.session_auto_save.assert_called()
        errors = self.chat.current_session.errors
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['code'], 401)
        self.assertEqual(errors[0]['message'], 'Unauthorized')

    def test_empty_stream_persists_nothing(self):
        self.chat.provider.chat.return_value = []
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._agent_loop()
        self.assertEqual(self._texts(), [])
        self.chat.session_auto_save.assert_called()
        errors = self.chat.current_session.errors
        self.assertEqual(len(errors), 1)
        self.assertIn('Stream ended before a completion event', errors[0]['message'])
        self.assertEqual(self.chat.provider.chat.call_count, 3)
        self.assertEqual(out.getvalue().count('retrying'), 2)

    def test_empty_stream_retried_once_then_succeeds(self):
        self.chat.provider.chat.side_effect = [
            [],
            [
                {'type': 'token', 'content': 'Recovered answer'},
                {'type': 'done', 'reason': 'stop'},
            ],
        ]
        self._run()
        self.assertEqual(self.chat.provider.chat.call_count, 2)
        self.assertEqual(self.chat.current_session.errors, [])
        self.assertEqual(self._texts()[0], 'Recovered answer')

    def test_empty_stream_retried_twice_then_succeeds(self):
        self.chat.provider.chat.side_effect = [
            [],
            [],
            [
                {'type': 'token', 'content': 'Recovered answer'},
                {'type': 'done', 'reason': 'stop'},
            ],
        ]
        self._run()
        self.assertEqual(self.chat.provider.chat.call_count, 3)
        self.assertEqual(self.chat.current_session.errors, [])
        self.assertEqual(self._texts()[0], 'Recovered answer')

    def test_failed_follow_up_stream_hints_recovery(self):
        target = self.chat.config.local_path.parent.parent / 'a.txt'
        target.write_text('hello\n')
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': [
                {'id': 'call_1', 'type': 'function',
                 'function': {'name': 'read_file',
                              'arguments': json.dumps({'path': str(target)})}},
            ]}],
            [],
            [],
            [],
        ]
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._agent_loop()
        errors = self.chat.current_session.errors
        self.assertEqual(len(errors), 1)
        self.assertIn('Stream ended before a completion event', errors[0]['message'])
        self.assertIn('tool results are saved', out.getvalue())
        self.assertIn('retrying', out.getvalue())
        tool_msgs = self._parts('tool')
        self.assertEqual(len(tool_msgs), 1)

    def test_token_stream_then_eof_persists_content_and_logs_error(self):
        self.chat.provider.chat.return_value = [
            {'type': 'token', 'content': 'Partial answer'},
        ]
        self._run()
        self.assertEqual(self._texts()[0], 'Partial answer')
        errors = self.chat.current_session.errors
        self.assertEqual(len(errors), 1)
        self.assertIn('Stream ended before a completion event', errors[0]['message'])

    def test_empty_done_logs_error(self):
        self.chat.provider.chat.return_value = [
            {'type': 'done', 'reason': 'stop'},
        ]
        self._run()
        self.assertEqual(self._texts(), [])
        self.assertEqual(self.chat.provider.chat.call_count, 3)
        errors = self.chat.current_session.errors
        self.assertEqual(len(errors), 1)
        self.assertIn('empty response', errors[0]['message'])

    def test_empty_done_retried_then_succeeds(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'done', 'reason': 'stop'}],
            [{'type': 'token', 'content': 'Back on track'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self._run()
        self.assertEqual(self.chat.provider.chat.call_count, 2)
        self.assertEqual(self.chat.current_session.errors, [])
        self.assertEqual(self._texts()[0], 'Back on track')

    def test_mid_stream_exception_is_caught_and_logged(self):
        def _raising():
            yield {'type': 'token', 'content': 'Partial'}
            raise RuntimeError('boom')

        self.chat.provider.chat.return_value = _raising()
        self._run()
        self.assertEqual(self._texts()[0], 'Partial')
        errors = self.chat.current_session.errors
        self.assertEqual(len(errors), 1)
        self.assertIn('Agent loop failed: boom', errors[0]['message'])

    def _interrupt_stream(self):
        def gen():
            yield {'type': 'token', 'content': 'Partial'}
            raise KeyboardInterrupt()
        return gen()

    def test_keyboard_interrupt_mid_stream_cancels_turn(self):
        self.chat.provider.chat.return_value = self._interrupt_stream()
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            result = self.chat._agent_loop()
        self.assertEqual(result.status, 'cancelled')
        self.assertEqual(result.errors, [])
        self.assertEqual(result.content, 'Partial')
        self.assertIn('(cancelled)', out.getvalue())

    def test_keyboard_interrupt_after_tool_call_cancels_turn(self):
        target = self.chat.config.local_path.parent
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': [
                {'id': 'call_1', 'type': 'function',
                 'function': {'name': 'list_dir',
                              'arguments': json.dumps({'path': str(target)})}},
            ]}],
            self._interrupt_stream(),
        ]
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            result = self.chat._agent_loop()
        self.assertEqual(result.status, 'cancelled')
        self.assertEqual(result.errors, [])
        tool_msgs = self._parts('tool')
        self.assertEqual(len(tool_msgs), 1)

    def test_unknown_tool_result_lists_available_tools(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': [
                {'id': 'call_1', 'type': 'function',
                 'function': {'name': 'browse', 'arguments': json.dumps({'url': 'x'})}},
            ]}],
            [{'type': 'token', 'content': 'Done'}, {'type': 'done', 'reason': 'stop'}],
        ]
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            result = self.chat._agent_loop()
        self.assertEqual(result.status, 'ok')
        tool_msgs = self._parts('tool')
        self.assertEqual(len(tool_msgs), 1)
        self.assertIn('Error: unknown tool "browse"', tool_msgs[0]['output'])
        self.assertIn('web_search', tool_msgs[0]['output'])

    def test_length_finish_logs_truncation_error(self):
        self.chat.config.set('max_tokens', 500)
        self.chat.config.set('auto_continue', False)
        self.chat.provider.chat.return_value = [
            {'type': 'token', 'content': 'Part of an answer'},
            {'type': 'done', 'reason': 'length'},
        ]
        self._run()
        errors = self.chat.current_session.errors
        self.assertEqual(len(errors), 1)
        self.assertIn('max_tokens limit reached (500)', errors[0]['message'])
        self.assertEqual(self._texts()[0], 'Part of an answer')

    def test_length_finish_unset_limit_mentions_provider_default(self):
        self.chat.config.set('max_tokens', 0)
        self.chat.config.set('auto_continue', False)
        self.chat.provider.chat.return_value = [
            {'type': 'token', 'content': 'Part of an answer'},
            {'type': 'done', 'reason': 'length'},
        ]
        self._run()
        errors = self.chat.current_session.errors
        self.assertEqual(len(errors), 1)
        self.assertIn('provider\'s default max_tokens limit', errors[0]['message'])
        self.assertNotIn('(0)', errors[0]['message'])

    def test_length_finish_auto_continues_until_completion(self):
        self.chat.config.set('auto_continue', True)
        self.chat.config.set('auto_continue_max', 3)
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'Part 1'},
             {'type': 'done', 'reason': 'length'}],
            [{'type': 'token', 'content': ' Part 2'},
             {'type': 'done', 'reason': 'length'}],
            [{'type': 'token', 'content': ' End'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self._run()
        self.assertEqual(self.chat.provider.chat.call_count, 3)
        self.assertEqual(self.chat.current_session.errors, [])
        self.assertEqual(self._texts(), ['Part 1 Part 2 End'])
        continuation = self.chat.provider.chat.call_args_list[1].args[0][-1]
        self.assertEqual(continuation['role'], 'user')
        self.assertIn('Continue exactly where you stopped.',
                      continuation['content'])

    def test_length_finish_auto_continue_obeyed_cap_then_truncates(self):
        self.chat.config.set('auto_continue', True)
        self.chat.config.set('auto_continue_max', 1)
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'A'},
             {'type': 'done', 'reason': 'length'}],
            [{'type': 'token', 'content': 'B'},
             {'type': 'done', 'reason': 'length'}],
            [{'type': 'token', 'content': 'C'},
             {'type': 'done', 'reason': 'length'}],
        ]
        self._run()
        self.assertEqual(self.chat.provider.chat.call_count, 2)
        errors = self.chat.current_session.errors
        self.assertEqual(len(errors), 1)
        self.assertIn('truncated', errors[0]['message'])
        self.assertEqual(self._texts()[0], 'AB')

    def test_reasoning_only_turn_is_not_flagged_empty(self):
        self.chat.provider.chat.return_value = [
            {'type': 'thinking', 'content': 'reasoned but did not answer'},
            {'type': 'done', 'reason': 'stop'},
        ]
        self._run()
        self.assertEqual(self.chat.current_session.errors, [])
        self.assertEqual(self._texts(), [])
        self.assertEqual([p['text'] for p in self._parts('thinking')],
                         ['reasoned but did not answer'])

    def test_context_size_printed_after_response(self):
        self.chat.provider.chat.return_value = [
            {'type': 'token', 'content': 'Hello'},
            {'type': 'done', 'reason': 'stop'},
        ]
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._agent_loop()
        value = out.getvalue()
        self.assertIn('s, ', value)
        self.assertIn('tokens', value)

    def test_footer_uses_provider_usage(self):
        self.chat.provider.chat.return_value = [
            {'type': 'token', 'content': 'Hello'},
            {'type': 'done', 'reason': 'stop',
             'usage': {'prompt_tokens': 29238, 'completion_tokens': 5,
                       'total_tokens': 29243}},
        ]
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._agent_loop()
        self.assertIn('29,238 tokens', out.getvalue())

    def test_clear_screen_on_repl_start_default(self):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            with patch('polyglav.chat.input', side_effect=EOFError):
                self.chat.run()
        self.assertIn('\033[3J\033[2J\033[H', out.getvalue())

    def test_clear_screen_disabled_suppresses_escape(self):
        self.chat.config.data['clear_screen'] = False
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            with patch('polyglav.chat.input', side_effect=EOFError):
                self.chat.run()
        self.assertNotIn('\033[3J\033[2J\033[H', out.getvalue())
        self.assertIn('Polyglav', out.getvalue())

    def test_banner_shows_version_by_default(self):
        from polyglav import get_version
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            with patch('polyglav.chat.input', side_effect=EOFError):
                self.chat.run()
        self.assertIn(f'v{get_version()}', out.getvalue())

    def test_banner_version_omitted_when_disabled(self):
        from polyglav import get_version
        self.chat.config.data['show_version'] = False
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            with patch('polyglav.chat.input', side_effect=EOFError):
                self.chat.run()
        self.assertNotIn(f'v{get_version()}', out.getvalue())


if __name__ == '__main__':
    unittest.main()
