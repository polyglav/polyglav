import io
import sys
import time
import unittest
from unittest.mock import patch

from tests.helpers import make_chat
from polyglav.engine import Engine
from polyglav.ui import HeadlessUI, DIM, RED, BLUE, ORANGE, _hidden_input


class TestGlyphActivityLines(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat._init_tooling()
        self.chat._show_tool_status = Engine._show_tool_status.__get__(self.chat)

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _capture_status(self, name, args):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._show_tool_status(name, args)
        return out.getvalue()

    def test_glyph_lines_default_true(self):
        from polyglav.config import DEFAULT_CONFIG
        self.assertTrue(DEFAULT_CONFIG['glyph_lines'])

    def test_repl_activity_renders_glyph_line(self):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._ui.activity('→', 'Write', 'a.md', ['+ hi'])
        value = out.getvalue()
        self.assertIn('→ Write a.md', value)
        self.assertIn('+ hi', value)

    def test_headless_activity_renders_when_verbose(self):
        ui = HeadlessUI(auto='deny', verbose=True)
        err = io.StringIO()
        with patch('sys.stderr', new=err):
            ui.activity('$', 'Run', 'echo hi', [])
        self.assertIn('$ Run echo hi', err.getvalue())

    def test_repl_tool_error_renders_first_line(self):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._ui.tool_error('Error: boom\nsecond line')
        value = out.getvalue()
        self.assertIn('! Error: boom', value)
        self.assertNotIn('second line', value)

    def test_headless_tool_error_renders_when_verbose(self):
        ui = HeadlessUI(auto='deny', verbose=True)
        err = io.StringIO()
        with patch('sys.stderr', new=err):
            ui.tool_error('Error: boom')
        self.assertIn('! Error: boom', err.getvalue())

    def test_headless_tool_error_silent_when_not_verbose(self):
        ui = HeadlessUI(auto='deny', verbose=False)
        err = io.StringIO()
        with patch('sys.stderr', new=err):
            ui.tool_error('Error: boom')
        self.assertEqual(err.getvalue(), '')

    def test_status_renders_glyph_when_mapped(self):
        value = self._capture_status('write_file', {'path': 'a.md', 'content': 'x'})
        self.assertIn('→ Write a.md', value)
        self.assertNotIn('[write_file:', value)

    def test_status_falls_back_to_oneliner_when_disabled(self):
        self.chat.config.set('glyph_lines', False)
        value = self._capture_status('write_file', {'path': 'a.md', 'content': 'x'})
        self.assertIn('[write_file: a.md]', value)
        self.assertNotIn('→', value)

    def test_status_falls_back_to_oneliner_for_unmapped_category(self):
        params = {'type': 'object', 'properties': {}, 'required': []}
        self.chat._tool_registry.register(
            'xyz_case', 'Do something', params, category='custom')(lambda: 'ok')
        value = self._capture_status('xyz_case', {})
        self.assertIn('[xyz_case: xyz_case]', value)


class TestThinkingSpinner(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._ui._stop_spinner()
        self.chat._tmp.cleanup()

    def test_spinner_starts_when_thinking_hidden(self):
        self.chat.config.set('show_thinking', False)
        self.chat._ui.thinking_begin()
        self.assertIsNotNone(self.chat._ui._spinner_thread)
        self.assertTrue(self.chat._ui._spinner_thread.is_alive())

    def test_no_spinner_when_thinking_visible(self):
        self.chat.config.set('show_thinking', True)
        self.chat._ui.thinking_begin()
        self.assertIsNone(self.chat._ui._spinner_thread)

    def test_thinking_end_stops_spinner_and_prints_thought(self):
        self.chat.config.set('show_thinking', False)
        self.chat._ui.thinking_begin()
        thread = self.chat._ui._spinner_thread
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._ui.thinking_end(2.5)
        self.assertFalse(thread.is_alive())
        self.assertIsNone(self.chat._ui._spinner_thread)
        value = out.getvalue()
        self.assertIn('\r\033[K', value)
        self.assertIn('+ Thought 2.5s', value)

    def test_thinking_end_without_spinner_is_clean(self):
        self.chat.config.set('show_thinking', False)
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._ui.thinking_end(1.0)
        self.assertIsNone(self.chat._ui._spinner_thread)
        self.assertIn('+ Thought 1.0s', out.getvalue())

    def test_status_begin_and_end_use_label(self):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._ui.status_begin('Delegating to writer...')
            thread = self.chat._ui._spinner_thread
            self.assertIsNotNone(thread)
            self.assertTrue(thread.is_alive())
            self.assertEqual(self.chat._ui._spinner_label,
                             'Delegating to writer...')
            self.chat._ui.status_end()
        self.assertFalse(thread.is_alive())
        self.assertIsNone(self.chat._ui._spinner_thread)
        self.assertIn('\r\033[K', out.getvalue())

    def test_status_spinner_disabled(self):
        self.chat.config.set('status_spinner', False)
        self.chat._ui.status_begin('Delegating...')
        self.assertIsNone(self.chat._ui._spinner_thread)

    def test_null_ui_status_is_noop(self):
        from polyglav.ui import NullUI
        NullUI().status_begin('x')
        NullUI().status_end()

    def test_run_subagent_wraps_status(self):
        from polyglav.roles import Role
        self.chat.roles.put(
            Role(name='writer', system_prompt='You are the writer.'),
            scope='local')
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'done'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        calls = []
        self.chat._ui.status_begin = lambda label: calls.append(('begin', label))
        self.chat._ui.status_end = lambda note='': calls.append(('end', note))
        with patch('sys.stdout', new=io.StringIO()):
            self.chat.run_subagent('writer', 'draft it')
        self.assertEqual(calls[0][0], 'begin')
        self.assertIn('writer', calls[0][1])
        self.assertEqual(calls[-1][0], 'end')

    def test_status_end_prints_frozen_line_with_note(self):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._ui.status_begin('dev: planner...')
            self.chat._ui.status_end('(1.2s, 300 tokens)')
        value = out.getvalue()
        self.assertIn('✓ dev: planner', value)
        self.assertIn('(1.2s, 300 tokens)', value)

    def test_status_begin_prints_switch_marker(self):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._ui.status_begin('dev: programmer...')
            self.chat._ui.status_end()
        self.assertIn('↔ Switch dev: programmer', out.getvalue())

    def test_confirm_sets_prompting_during_input(self):
        seen = []

        def fake_input(prompt, timeout, hidden=False):
            seen.append(self.chat._ui._prompting.is_set())
            return 'y'

        with patch('polyglav.ui._timed_input', side_effect=fake_input):
            with patch('sys.stdout', new=io.StringIO()):
                self.assertTrue(self.chat._ui.confirm('x', 'probe'))
        self.assertEqual(seen, [True])
        self.assertFalse(self.chat._ui._prompting.is_set())

    def test_ask_sets_prompting_during_input(self):
        seen = []

        def fake_input(prompt, timeout):
            seen.append(self.chat._ui._prompting.is_set())
            return 'answer'

        with patch('polyglav.ui._timed_input', side_effect=fake_input):
            with patch('sys.stdout', new=io.StringIO()):
                answer = self.chat._ui.ask('q')
        self.assertEqual(answer, 'answer')
        self.assertEqual(seen, [True])
        self.assertFalse(self.chat._ui._prompting.is_set())

    def test_spinner_skips_repaint_while_prompting(self):
        out = io.StringIO()
        self.chat._ui._prompting.set()
        try:
            with patch('sys.stdout', new=out):
                self.chat._ui._start_spinner('x...')
                time.sleep(0.25)
                self.chat._ui._stop_spinner()
        finally:
            self.chat._ui._prompting.clear()
        self.assertNotIn('⠋', out.getvalue())

    def test_run_stats_reports_duration_and_tokens(self):
        from polyglav.engine import TurnResult
        result = TurnResult(duration=2.5, usage={'prompt_tokens': 100,
                                                'completion_tokens': 20})
        self.assertEqual(self.chat._run_stats(result), '(2.5s, 120 tokens)')

    def test_run_stats_omits_tokens_without_usage(self):
        from polyglav.engine import TurnResult
        self.assertEqual(self.chat._run_stats(TurnResult(duration=1.0)),
                         '(1.0s)')

    def test_subrun_summary_forwards_only_writes(self):
        from polyglav.ui import SubRunUI
        run = self.chat.current_run
        forwarded = []
        parent = type('P', (), {'activity': lambda self, *a: forwarded.append(a)})()
        ui = SubRunUI(run, parent)
        ui.activity('→', 'Write', 'a.md', [])
        ui.activity('←', 'Read', 'a.md', [])
        self.assertEqual(len(forwarded), 1)
        self.assertEqual(forwarded[0][0], '→')

    def test_subrun_verbosity_full_forwards_all(self):
        from polyglav.ui import SubRunUI
        run = self.chat.current_run
        forwarded = []
        parent = type('P', (), {'activity': lambda self, *a: forwarded.append(a)})()
        ui = SubRunUI(run, parent, forward_all=True)
        ui.activity('←', 'Read', 'a.md', [])
        ui.activity('→', 'Write', 'a.md', [])
        self.assertEqual(len(forwarded), 2)

    def test_subrun_verbosity_selects_ui(self):
        from polyglav.roles import Role
        from polyglav.ui import BufferUI, SubRunUI
        self.chat.roles.put(
            Role(name='writer', system_prompt='w'), scope='local')
        self.chat.config.set('subrun_verbosity', 'summary')
        self.assertIsInstance(self.chat._new_sub_engine('writer')._ui,
                              SubRunUI)
        self.chat.config.set('subrun_verbosity', 'quiet')
        self.assertIsInstance(self.chat._new_sub_engine('writer')._ui,
                              BufferUI)

    def test_thinking_end_streamed_prints_thought_duration(self):
        self.chat.config.set('show_thinking', True)
        self.chat.config.set('show_thought_duration', True)
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._ui.thinking_end(2.5)
        value = out.getvalue()
        self.assertIn('(Thought 2.5s)', value)
        self.assertNotIn('+ Thought', value)

    def test_thinking_end_streamed_hides_thought_duration_when_off(self):
        self.chat.config.set('show_thinking', True)
        self.chat.config.set('show_thought_duration', False)
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._ui.thinking_end(1.0)
        self.assertNotIn('Thought', out.getvalue())


class TestEphemeralUI(unittest.TestCase):

    def test_activity_lines_not_persisted_to_session(self):
        chat = make_chat()
        chat._init_tooling()
        chat._show_tool_status = Engine._show_tool_status.__get__(chat)
        chat._show_tool_status('write_file', {'path': 'a.md', 'content': 'x'})
        dump = chat.current_session.to_dict()
        blob = str(dump)
        self.assertNotIn('→ Write a.md', blob)
        self.assertNotIn('[write_file: a.md]', blob)
        chat._tmp.cleanup()


class TestWordStreaming(unittest.TestCase):

    PREFIX = '\001\033[33m\002<<< \001\033[0m\002'

    def setUp(self):
        self.chat = make_chat()
        self.ui = self.chat._ui

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _capture(self, fn):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            fn()
        return out.getvalue()

    def test_word_streaming_default_true(self):
        from polyglav.config import DEFAULT_CONFIG
        self.assertTrue(DEFAULT_CONFIG['word_streaming'])

    def test_partial_word_held_until_boundary(self):
        def run():
            self.ui.token('app')
            self.ui.token('rox ')
            self.ui.token('hard')
        value = self._capture(run)
        self.assertEqual(value, self.PREFIX + 'approx ')
        self.assertEqual(self.ui._word_buffer, 'hard')

    def test_flush_writes_remainder(self):
        def run():
            self.ui.token('app')
            self.ui.token('rox ')
            self.ui.token('hard')
            self.ui.flush()
        value = self._capture(run)
        self.assertEqual(value, self.PREFIX + 'approx hard')
        self.assertEqual(self.ui._word_buffer, '')

    def test_multi_word_token_flushes_through_last_space(self):
        def run():
            self.ui.token('word1 word2 par')
        value = self._capture(run)
        self.assertEqual(value, self.PREFIX + 'word1 word2 ')
        self.assertEqual(self.ui._word_buffer, 'par')

    def test_newline_flushes(self):
        def run():
            self.ui.token('line1\n')
            self.ui.token('par')
        value = self._capture(run)
        self.assertEqual(value, self.PREFIX + 'line1\n')
        self.assertEqual(self.ui._word_buffer, 'par')

    def test_footer_flushes_tail(self):
        def run():
            self.ui.token('hard')
            self.ui.footer(3.0, {'context': 10})
        value = self._capture(run)
        self.assertIn('hard', value)
        self.assertIn('(3.0s, 10 tokens)', value)
        self.assertIn('hard\n', value)
        self.assertLess(value.index('hard'), value.index('(3.0s'))

    def test_footer_token_parts_selected(self):
        self.chat.config.set('footer_tokens', ['in', 'thinking', 'out'])
        def run():
            self.ui.footer(3.0, {'in': 12, 'thinking': 5, 'out': 8})
        value = self._capture(run)
        self.assertIn('(3.0s, 12t/5t/8t)', value)

    def test_footer_token_parts_skip_unavailable(self):
        self.chat.config.set('footer_tokens', ['in', 'thinking', 'out'])
        def run():
            self.ui.footer(3.0, {'in': 12})
        value = self._capture(run)
        self.assertIn('(3.0s, 12t)', value)
        self.assertNotIn('thinking', value)

    def test_footer_token_parts_empty_hides_tokens(self):
        self.chat.config.set('footer_tokens', [])
        def run():
            self.ui.footer(3.0, {'context': 10})
        value = self._capture(run)
        self.assertIn('(3.0s)', value)
        self.assertNotIn('tokens', value)

    def test_footer_show_context_size_off_hides_tokens(self):
        self.chat.config.set('show_context_size', False)
        self.chat.config.set('footer_tokens', ['in', 'out'])
        def run():
            self.ui.footer(3.0, {'in': 12, 'out': 8})
        value = self._capture(run)
        self.assertIn('(3.0s)', value)
        self.assertNotIn('t', value)

    def test_word_streaming_off_writes_immediately(self):
        self.chat.config.set('word_streaming', False)

        def run():
            self.ui.token('app')
            self.ui.token('rox ')
        self.assertEqual(self._capture(run), self.PREFIX + 'approx ')
        self.assertEqual(self.ui._word_buffer, '')

    def test_markdown_bold_across_flush_boundary(self):
        self.chat.config.set('markdown_streaming', True)

        def run():
            self.ui.token('**bo')
            self.ui.token('ld**: ok')
            self.ui.flush()
        value = self._capture(run)
        self.assertIn('bold', value)
        self.assertNotIn('*', value)

    def test_activity_flushes_pending_word(self):
        def run():
            self.ui.token('par')
            self.ui.activity('→', 'Write', 'a.md', ['+ hi'])
        value = self._capture(run)
        self.assertIn('par', value)
        self.assertIn('→ Write a.md', value)
        self.assertLess(value.index('par'), value.index('→ Write a.md'))

    def test_confirm_flushes_pending_word(self):
        def fake_input(prompt):
            sys.stdout.write(prompt)
            return 'n'

        def run():
            self.ui.token('par')
            with patch('polyglav.ui.input', side_effect=fake_input):
                self.ui.confirm('write_file', 'write_file a.md')
        value = self._capture(run)
        self.assertIn('par', value)
        self.assertIn('write_file a.md', value)
        self.assertLess(value.index('par'), value.index('write_file a.md'))

    def test_confirm_question_marks_start_of_line(self):
        def fake_input(prompt):
            sys.stdout.write(prompt)
            return 'n'

        def run():
            with patch('polyglav.ui.input', side_effect=fake_input):
                self.ui.confirm('write_file', 'write_file a.md')
        value = self._capture(run)
        self.assertIn('? write_file a.md - approve? [Y/n]', value)
        self.assertNotIn('  ? ', value)

    def test_confirm_default_yes_on_empty(self):
        def fake_input(prompt):
            return ''
        with patch('polyglav.ui.input', side_effect=fake_input):
            self.assertTrue(self.ui.confirm('write_file', 'write_file a.md'))

    def test_confirm_no_on_n(self):
        def fake_input(prompt):
            return 'n'
        with patch('polyglav.ui.input', side_effect=fake_input):
            self.assertFalse(self.ui.confirm('write_file', 'write_file a.md'))

    def test_confirm_hidden_input(self):
        self.chat.config.set('hide_confirm_input', True)
        with patch('polyglav.ui._hidden_input', return_value='y') as hidden:
            with patch('polyglav.ui.input', side_effect=AssertionError(
                    'visible input used')):
                self.assertTrue(self.ui.confirm('write_file', 'write_file a.md'))
        hidden.assert_called_once()

    def test_ask_uses_visible_input(self):
        self.chat.config.set('hide_confirm_input', True)
        with patch('polyglav.ui._hidden_input', side_effect=AssertionError(
                'hidden input used')):
            with patch('polyglav.ui.input', return_value='answer'):
                self.assertEqual(self.ui.ask('q'), 'answer')

    def test_confirm_raises_on_keyboard_interrupt(self):
        def fake_input(prompt):
            raise KeyboardInterrupt()

        with patch('polyglav.ui.input', side_effect=fake_input):
            with self.assertRaises(KeyboardInterrupt):
                self.ui.confirm('write_file', 'write_file a.md')

    def test_confirm_returns_false_on_eof(self):
        def fake_input(prompt):
            raise EOFError()

        with patch('polyglav.ui.input', side_effect=fake_input):
            self.assertFalse(self.ui.confirm('write_file', 'write_file a.md'))


class TestLinePrompts(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.ui = self.chat._ui

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _capture(self, fn):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            fn()
        return out.getvalue()

    def _confirm(self, answers, label='write_file a.md'):
        with patch('polyglav.ui.input', side_effect=list(answers)):
            return self.ui.confirm('write_file', label)

    def test_confirm_y_approves(self):
        self.assertTrue(self._confirm(['y']))

    def test_confirm_yes_approves(self):
        self.assertTrue(self._confirm(['yes']))

    def test_confirm_enter_approves(self):
        self.assertTrue(self._confirm(['']))

    def test_confirm_n_declines(self):
        self.assertFalse(self._confirm(['n']))

    def test_confirm_no_declines(self):
        self.assertFalse(self._confirm(['no']))

    def test_confirm_unknown_reprompts(self):
        self.assertFalse(self._confirm(['maybe', 'n']))

    def test_confirm_question_marks_start_of_line(self):
        def fake_input(prompt):
            sys.stdout.write(prompt)
            return 'n'

        def run():
            with patch('polyglav.ui.input', side_effect=fake_input):
                self.ui.confirm('write_file', 'write_file a.md')
        value = self._capture(run)
        self.assertIn('? write_file a.md - approve? [Y/n]', value)
        self.assertNotIn('  ? ', value)

    def test_confirm_hidden_input(self):
        self.chat.config.set('hide_confirm_input', True)
        with patch('polyglav.ui._hidden_input', return_value='y') as hidden:
            with patch('polyglav.ui.input', side_effect=AssertionError(
                    'visible input used')):
                self.assertTrue(self.ui.confirm('write_file', 'write_file a.md'))
        hidden.assert_called_once()

    def test_confirm_timeout_denies(self):
        self.chat.config.set('confirm_timeout', 2)
        with patch('polyglav.ui.select.select', return_value=([], [], [])):
            with patch('polyglav.ui.input', side_effect=AssertionError(
                    'input must not be called on timeout')):
                value = self._capture(
                    lambda: self.ui.confirm('write_file', 'write_file a.md'))
        self.assertIn('no answer in 2s, denied', value)

    def test_confirm_eof_denies(self):
        with patch('polyglav.ui.input', side_effect=EOFError):
            self.assertFalse(self.ui.confirm('write_file', 'write_file a.md'))

    def test_confirm_keyboard_interrupt_reraises(self):
        with patch('polyglav.ui.input', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.ui.confirm('write_file', 'write_file a.md')

    def test_ask_digit_returns_option_text(self):
        with patch('polyglav.ui.input', return_value='2'):
            answer = self.ui.ask('which?', options=['a', 'b'])
        self.assertEqual(answer, 'b')

    def test_ask_out_of_range_digit_is_free_text(self):
        with patch('polyglav.ui.input', return_value='9'):
            answer = self.ui.ask('which?', options=['a', 'b'])
        self.assertEqual(answer, '9')

    def test_ask_non_digit_enters_free_text(self):
        with patch('polyglav.ui.input', return_value='my own answer'):
            answer = self.ui.ask('which?', options=['a', 'b'])
        self.assertEqual(answer, 'my own answer')

    def test_ask_enter_returns_none(self):
        with patch('polyglav.ui.input', return_value=''):
            self.assertIsNone(self.ui.ask('which?', options=['a', 'b']))

    def test_ask_timeout_returns_none(self):
        self.chat.config.set('confirm_timeout', 2)
        with patch('polyglav.ui.select.select', return_value=([], [], [])):
            with patch('polyglav.ui.input', side_effect=AssertionError(
                    'input must not be called on timeout')):
                self.assertIsNone(self.ui.ask('which?', options=['a', 'b']))

    def test_ask_options_rendered_inline(self):
        with patch('polyglav.ui.input', return_value='1'):
            value = self._capture(
                lambda: self.ui.ask('which?', options=['a', 'b']))
        self.assertIn('which?  (a) a  (b) b', value)

    def test_ask_letter_returns_option_text(self):
        with patch('polyglav.ui.input', return_value='b'):
            answer = self.ui.ask('which?', options=['a', 'b'])
        self.assertEqual(answer, 'b')

    def test_ask_long_question_renders_numbered_list(self):
        question = 'x' * 70
        with patch('polyglav.ui.input', return_value='2'):
            value = self._capture(
                lambda: self.ui.ask(question, options=['a', 'b']))
        self.assertIn('1) a', value)
        self.assertIn('2) b', value)
        self.assertNotIn('(a) a', value)

    def test_ask_inline_threshold_config_disables_inline(self):
        self.chat.config.set('ask_options_inline_chars', 0)
        with patch('polyglav.ui.input', return_value='1'):
            value = self._capture(
                lambda: self.ui.ask('which?', options=['a', 'b']))
        self.assertIn('1) a', value)

    def test_ask_origin_prefix_present(self):
        with patch('polyglav.ui.input', return_value='1'):
            value = self._capture(
                lambda: self.ui.ask('which?', options=['a', 'b'],
                                    origin='other-session'))
        self.assertIn('[other-session] which?', value)

    def test_ask_uses_visible_input_even_when_confirm_hidden(self):
        self.chat.config.set('hide_confirm_input', True)
        with patch('polyglav.ui._hidden_input', side_effect=AssertionError(
                'hidden input used')):
            with patch('polyglav.ui.input', return_value='answer'):
                self.assertEqual(self.ui.ask('q'), 'answer')

    def test_hidden_path_does_not_read_stdin(self):
        class _FakeTTY:
            def fileno(self):
                return 0

            def close(self):
                pass

        with patch('polyglav.ui._open_tty', return_value=_FakeTTY()):
            with patch('termios.tcgetattr',
                       return_value=[0, 0, 0, 0, 0, 0, []]):
                with patch('termios.tcsetattr'):
                    with patch('tty.setcbreak'):
                        with patch('polyglav.ui._read_key',
                                   side_effect=['y', '\r']):
                            with patch('polyglav.ui.sys.stdin') as stdin:
                                stdin.readline.side_effect = AssertionError(
                                    'stdin read')
                                stdin.fileno.side_effect = AssertionError(
                                    'stdin read')
                                self.assertEqual(
                                    _hidden_input('? ', 0.0), 'y')


class TestReplColors(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.ui = self.chat._ui

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _capture(self, fn):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            fn()
        return out.getvalue()

    def test_activity_orange(self):
        value = self._capture(
            lambda: self.ui.activity('→', 'Write', 'a.md', []))
        self.assertIn(ORANGE, value)

    def test_tool_error_red(self):
        value = self._capture(lambda: self.ui.tool_error('Error: boom'))
        self.assertIn(RED, value)

    def test_tool_error_result_prints_all_lines_red(self):
        value = self._capture(
            lambda: self.ui.tool_error_result('$ cmd\nexit 1\nboom'))
        self.assertIn('exit 1', value)
        self.assertIn('boom', value)
        self.assertIn(RED, value)

    def test_thinking_header_blue(self):
        self.chat.config.set('show_thinking', True)
        value = self._capture(lambda: self.ui.thinking_begin())
        self.assertIn(BLUE, value)

    def test_reasoning_body_dim(self):
        self.chat.config.set('show_thinking', True)
        value = self._capture(lambda: self.ui.thinking('reason'))
        self.assertIn(DIM, value)

    def test_thought_summary_dim(self):
        self.chat.config.set('show_thinking', True)
        self.chat.config.set('show_thought_duration', True)
        value = self._capture(lambda: self.ui.thinking_end(2.5))
        self.assertIn(DIM, value)
        self.assertIn('(Thought 2.5s)', value)
        self.assertNotIn(BLUE, value)

    def test_hidden_thought_blue(self):
        self.chat.config.set('show_thinking', False)
        value = self._capture(lambda: self.ui.thinking_end(2.5))
        self.assertIn(BLUE, value)
        self.assertIn('+ Thought 2.5s', value)

    def test_status_line_starts_on_new_line_after_text(self):
        def run():
            self.ui.token('streamed text')
            self.ui.activity('→', 'Write', 'a.md', [])
        value = self._capture(run)
        self.assertIn('streamed text\n', value)


if __name__ == '__main__':
    unittest.main()
