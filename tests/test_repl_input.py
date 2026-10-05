import io
import unittest
from unittest.mock import MagicMock, patch

from polyglav.chat import _open_delim, _strip_framing
from tests.helpers import make_chat


class TestOpenDelim(unittest.TestCase):

    def test_plain_text_balanced(self):
        self.assertIsNone(_open_delim('hello world'))

    def test_empty_balanced(self):
        self.assertIsNone(_open_delim(''))
        self.assertIsNone(_open_delim('   '))

    def test_single_triple_double_opens(self):
        self.assertEqual(_open_delim('hello """'), '"""')
        self.assertEqual(_open_delim('"""'), '"""')

    def test_paired_triple_double_balanced(self):
        self.assertIsNone(_open_delim('""" a """'))
        self.assertIsNone(_open_delim('""""'))

    def test_single_triple_single_opens(self):
        self.assertEqual(_open_delim("it's [[['''"), "'''")

    def test_single_quotes_ignored(self):
        self.assertIsNone(_open_delim("don't"))
        self.assertIsNone(_open_delim('say "hi"'))

    def test_both_odd_prefers_double(self):
        self.assertEqual(_open_delim('""" and \'\'\''), '"""')


class TestStripFraming(unittest.TestCase):

    def test_pure_framing(self):
        self.assertEqual(_strip_framing('"""\nhello\n"""', '"""'), 'hello')

    def test_lead_in_framing(self):
        self.assertEqual(
            _strip_framing('task: """\nbody\n"""', '"""'), 'task: \nbody')

    def test_single_quote_framing(self):
        self.assertEqual(_strip_framing("'''\na\n'''", "'''"), 'a')

    def test_no_delimiter_unchanged(self):
        text = 'plain text'
        self.assertEqual(_strip_framing(text, '"""'), text)

    def test_inner_pairs_preserved(self):
        self.assertEqual(
            _strip_framing('"""\na """ b """ c\n"""', '"""'),
            'a """ b """ c')

    def test_no_delimiter_unchanged_end(self):
        self.assertEqual(_strip_framing('abc', '"""'), 'abc')


class TestReplInput(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat.chat = MagicMock()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _run(self, lines):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            with patch('polyglav.chat.input', side_effect=lines):
                with patch('polyglav.chat.readline'):
                    self.chat.run()
        return out.getvalue()

    def test_single_line_sent_directly(self):
        self._run(['hello', EOFError])
        self.chat.chat.assert_called_once_with('hello')

    def test_empty_line_skipped(self):
        self._run(['', 'hello', EOFError])
        self.chat.chat.assert_called_once_with('hello')

    def test_triple_quote_block_composes(self):
        self._run(['"""', 'hello', 'world', '"""', EOFError])
        self.chat.chat.assert_called_once_with('hello\nworld')

    def test_lead_in_block_composes(self):
        self._run(['task: """', 'body', '"""', EOFError])
        self.chat.chat.assert_called_once_with('task: \nbody')

    def test_indented_lines_preserved(self):
        self._run(['"""', '  "key": 1', '  "other": 2', '"""', EOFError])
        self.chat.chat.assert_called_once_with('  "key": 1\n  "other": 2')

    def test_first_line_stripped_like_single_line(self):
        self._run(['  "key": 1"""', '  "other": 2', '"""', EOFError])
        self.chat.chat.assert_called_once_with('"key": 1\n  "other": 2')

    def test_block_EOF_exits_without_sending(self):
        self._run(['"""', 'partial', EOFError])
        self.chat.chat.assert_not_called()

    def test_slash_command_stays_single_line(self):
        output = self._run(['/sessions list', EOFError])
        self.chat.chat.assert_not_called()
        self.assertIn('No sessions found', output)

    def test_open_delim_in_normal_question_is_single_line(self):
        self._run(['what is """ x """?', EOFError])
        self.chat.chat.assert_called_once_with('what is """ x """?')

    def test_blank_line_closes_block(self):
        self._run(['"""', 'hello', '', EOFError])
        self.chat.chat.assert_called_once_with('hello')

    def test_delimiter_only_closes_at_line_start(self):
        self._run(['"""', 'a """ b', '"""', EOFError])
        self.chat.chat.assert_called_once_with('a """ b')

    def test_backslash_continuation(self):
        self._run(['first \\', 'second \\', 'third', EOFError])
        self.chat.chat.assert_called_once_with('first\nsecond\nthird')

    def test_backslash_in_middle_is_plain(self):
        self._run(['a\\b', EOFError])
        self.chat.chat.assert_called_once_with('a\\b')


class TestOutputLog(unittest.TestCase):

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _run(self, config, lines=('hello', EOFError)):
        self.chat = make_chat(config)
        self.chat.chat = MagicMock()
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            with patch('polyglav.chat.input', side_effect=list(lines)):
                with patch('polyglav.chat.readline'):
                    self.chat.run()
        return self.chat.config.local_path.parent.parent

    def test_output_log_written_when_enabled(self):
        worktree = self._run({'output_log': True})
        logs = list((worktree / '.polyglav' / 'output').glob('*.txt'))
        self.assertEqual(len(logs), 1)
        self.assertIn('Polyglav', logs[0].read_text())

    def test_output_log_strips_ansi_by_default(self):
        worktree = self._run({'output_log': True})
        log = next((worktree / '.polyglav' / 'output').glob('*.txt'))
        text = log.read_text()
        self.assertNotIn('\x1b', text)
        self.assertIn('Polyglav', text)

    def test_output_log_keeps_ansi_when_configured(self):
        worktree = self._run({'output_log': True, 'output_log_ansi': True})
        log = next((worktree / '.polyglav' / 'output').glob('*.txt'))
        self.assertIn('\x1b', log.read_text())

    def test_no_output_log_when_disabled(self):
        worktree = self._run({})
        self.assertFalse((worktree / '.polyglav' / 'output').exists())


if __name__ == '__main__':
    unittest.main()