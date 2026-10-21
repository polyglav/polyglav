import io
import unittest
from unittest.mock import patch

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

    def test_thinking_and_footer(self):
        self.chat.config.set('verbosity.thinking', 'summary')

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
        value = self._capture(
            lambda: self.ui.sub_result('[call writer] Draft done.'))
        self.assertIn('↲ Draft done.', value)

    def test_ask_block(self):
        with patch('polyglav.ui.input', return_value='2') as inp:
            value = self._capture(
                lambda: self.ui.ask('Which?', options=['a', 'b']))
        self.assertIn('? Which?', value)
        self.assertIn('  1) a', value)
        self.assertIn('  2) b', value)
        prompt = inp.call_args[0][0]
        self.assertIn(CYAN, prompt)
        self.assertIn('>', prompt)

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
