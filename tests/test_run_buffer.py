import io
import unittest
from contextlib import redirect_stdout

from polyglav.runs import Run, RunRegistry
from polyglav.ui import BufferUI

from tests.helpers import make_chat


class TestRunBuffer(unittest.TestCase):

    def setUp(self):
        self.reg = RunRegistry()
        self.run = self.reg.start(role='writer', session='sub_1')

    def test_append_and_read_lines(self):
        self.run.append_buffer('one')
        self.run.append_buffer('two')
        self.assertEqual(self.run.buffer, ['one', 'two'])
        self.assertEqual(self.run.buffer_text(), 'one\ntwo')

    def test_append_skips_leading_blank(self):
        self.run.append_buffer('')
        self.assertEqual(self.run.buffer, [])
        self.run.append_buffer('one')
        self.run.append_buffer('')
        self.assertEqual(self.run.buffer, ['one', ''])

    def test_cap_trims_oldest_lines(self):
        self.run.max_buffer_lines = 3
        for i in range(5):
            self.run.append_buffer(str(i))
        self.assertEqual(self.run.buffer, ['2', '3', '4'])

    def test_clear_buffer(self):
        self.run.append_buffer('one')
        self.run.clear_buffer()
        self.assertEqual(self.run.buffer, [])


class TestBufferUI(unittest.TestCase):

    def setUp(self):
        self.reg = RunRegistry()
        self.run = self.reg.start(role='writer', session='sub_1')
        self.ui = BufferUI(self.run, max_lines=10)

    def test_tokens_split_into_lines_and_flush(self):
        self.ui.token('hello ')
        self.ui.token('world')
        self.assertEqual(self.run.buffer, [])
        self.ui.footer(1.0, {})
        self.assertEqual(self.run.buffer, ['hello world', '(1.0s)'])

    def test_token_newlines_split(self):
        self.ui.token('a\nb\nc')
        self.assertEqual(self.run.buffer, ['a', 'b'])
        self.ui.footer(1.0, {})
        self.assertEqual(self.run.buffer, ['a', 'b', 'c', '(1.0s)'])

    def test_tool_and_error_formatting(self):
        self.ui.tool_status('bash', 'ls', ['+ file.py'])
        self.ui.warning('careful')
        self.ui.error(0, 'boom')
        self.ui.tool_error('Error: no\nsecond')
        self.assertEqual(self.run.buffer, [
            '[bash: ls]', '+ file.py', '[warning] careful', '[Error] boom',
            '! Error: no'])

    def test_tool_result_each_line(self):
        self.ui.tool_result('one\ntwo\n')
        self.assertEqual(self.run.buffer, ['one', 'two'])

    def test_max_lines_sets_run_cap(self):
        run = self.reg.start(role='writer', session='sub_2')
        BufferUI(run, max_lines=2)
        self.assertEqual(run.max_buffer_lines, 2)

    def test_confirm_and_ask_have_no_channel(self):
        self.assertFalse(self.ui.confirm('bash', 'run ls'))
        self.assertIsNone(self.ui.ask('which one?'))


class TestFocusLogCommand(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def test_focus_log_prints_buffer(self):
        self.chat.current_run.append_buffer('first')
        self.chat.current_run.append_buffer('second')
        out = io.StringIO()
        with redirect_stdout(out):
            self.chat.registry.dispatch('/focus log')
        text = out.getvalue()
        self.assertIn('Run #1', text)
        self.assertIn('first', text)
        self.assertIn('second', text)

    def test_focus_log_tail_limit(self):
        for i in range(5):
            self.chat.current_run.append_buffer(str(i))
        out = io.StringIO()
        with redirect_stdout(out):
            self.chat.registry.dispatch('/focus log 2')
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[-2:], ['3', '4'])

    def test_focus_log_empty(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.chat.registry.dispatch('/focus log')
        self.assertIn('no buffered output', out.getvalue())


if __name__ == '__main__':
    unittest.main()
