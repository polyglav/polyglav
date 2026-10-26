import io
import unittest
from unittest.mock import patch

from polyglav.chat import _display_width
from polyglav.ui import (
    CYAN, DIM, ITALIC_GRAY, MAGENTA, RED, YELLOW,
)

from tests.helpers import make_chat


class TestReplOutput(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.ui = self.chat._ui

    def tearDown(self):
        self.ui._stop_spinner()
        self.chat._tmp.cleanup()

    def _capture(self, fn):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            fn()
        return out.getvalue()

    def test_header(self):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            with patch('polyglav.chat.input', side_effect=EOFError):
                self.chat.run()
        value = out.getvalue()
        self.assertIn('Polyglav v', value)
        self.assertIn('/help to list commands', value)
        self.assertIn('@ Read mode (ollama/test-model)', value)
        self.assertIn(DIM, value)

    def test_prompt_is_plain_underline(self):
        self.assertEqual(self.chat._prompt(), '_ ')
        self.assertEqual(self.chat._cont_prompt(), '... ')
        self.chat.config.set('mode', 'write')
        self.assertEqual(self.chat._prompt(), '_ ')

    def test_command_reprint(self):
        value = self._capture(lambda: self.chat._reprint_line('/mode write'))
        self.assertIn(MAGENTA, value)
        self.assertIn('mode write', value)

    def test_short_reprint_clears_one_row(self):
        value = self._capture(lambda: self.chat._reprint_line('hello'))
        self.assertEqual(value.count('\033[A'), 1)
        self.assertIn('\033[J', value)

    def test_long_reprint_clears_all_wrapped_rows(self):
        with patch('polyglav.chat._terminal_columns', return_value=10):
            value = self._capture(lambda: self.chat._reprint_line('x' * 25))
        self.assertEqual(value.count('\033[A'), 3)
        self.assertIn('\033[J', value)
        self.assertIn('> ' + 'x' * 25, value)

    def test_display_width_counts_wide_and_combining(self):
        self.assertEqual(_display_width('abc'), 3)
        self.assertEqual(_display_width('漢字'), 4)
        self.assertEqual(_display_width('e\u0301'), 1)

    def test_thinking_and_footer(self):
        self.chat.config.set('verbosity.thinking', 'assistant')

        def run():
            self.ui.thinking_begin()
            self.ui.thinking('reason')
            self.ui.thinking_end(1.0)

        value = self._capture(run)
        self.assertIn('✓ Thought 1.0s', value)
        self.assertIn(DIM, value)
        value = self._capture(
            lambda: self.ui.footer(1.0, {'context': 42}))
        self.assertIn('✓ Done 1.0s (42 tokens)', value)

    def test_tool_output_hidden(self):
        value = self._capture(
            lambda: self.ui.activity('→', 'Write', 'hello.py', ['+ secret']))
        self.assertIn('→ Write hello.py', value)
        self.assertNotIn('+ secret', value)
        self.assertIn('/print', value)
        self.assertIn(ITALIC_GRAY, value)

    def test_flat_stage_lines(self):
        def run():
            self.ui.status_begin('Call writer (1/2)', name='writer')
            self.ui.status_end('0.9s (120 tokens)')

        value = self._capture(run)
        self.assertIn('↳ Call writer (1/2)', value)
        self.assertIn('✓ Worked: writer 0.9s (120 tokens)', value)
        self.chat.config.set('verbosity.output', 'all')
        value = self._capture(
            lambda: self.ui.sub_result('[call writer] Draft done.', role='writer'))
        self.assertIn('↲ Draft done.', value)

    def test_ask_block(self):
        with patch('polyglav.ui.input', return_value='2') as inp:
            value = self._capture(
                lambda: self.ui.ask('Which?', options=['a', 'b']))
        self.assertIn('? Which?', value)
        self.assertIn(CYAN, value)
        self.assertIn('  1) a', value)
        self.assertIn('  2) b', value)
        prompt = inp.call_args[0][0]
        self.assertIn(CYAN, prompt)
        self.assertIn('>', prompt)

    def test_ask_context_is_indented_per_line(self):
        with patch('polyglav.ui.input', return_value='1'):
            value = self._capture(
                lambda: self.ui.ask('Which?', context='line one\nline two',
                                    options=['a']))
        self.assertIn('  line one', value)
        self.assertIn('  line two', value)

    def test_warning_and_error(self):
        def run():
            self.ui.warning('careful')
            self.ui.error('provider', 'boom')

        value = self._capture(run)
        self.assertIn('! careful', value)
        self.assertIn(YELLOW, value)
        self.assertIn('✗ [provider] boom', value)
        self.assertIn(RED, value)


if __name__ == '__main__':
    unittest.main()
