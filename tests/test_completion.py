import os
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import make_chat


class TestCompletion(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.addCleanup(self.chat._tmp.cleanup)

    def _complete(self, line, text):
        with patch('polyglav.chat.readline.get_line_buffer', return_value=line):
            return self.chat._completer(text, 0)

    def test_command_completion(self):
        self.assertEqual(self._complete('/he', '/he'), '/help ')

    def test_command_completion_exhausts(self):
        with patch('polyglav.chat.readline.get_line_buffer', return_value='/he'):
            self.assertIsNone(self.chat._completer('/he', 1))

    def test_session_name_completion(self):
        self.chat.sessions.create('mysession123')
        self.chat.sessions.save()
        self.assertEqual(self._complete('/session load mysess', 'mysess'), 'mysession123 ')

    def test_plugin_name_completion(self):
        options = self._complete('/plugins enable polyglav-core', 'polyglav-core')
        self.assertTrue(options.startswith('polyglav-core-'))
        self.assertTrue(options.endswith(' '))

    def test_tool_name_completion(self):
        self.chat._init_tooling()
        self.assertEqual(self._complete('/tool read_', 'read_'), 'read_file ')

    def test_subcommand_completion(self):
        self.assertEqual(self._complete('/session lo', 'lo'), 'load ')
        self.assertEqual(self._complete('/sessions de', 'de'), 'delete ')
        self.assertEqual(self._complete('/plugins dis', 'dis'), 'disable ')

    def test_subcommand_completion_exhausts(self):
        with patch('polyglav.chat.readline.get_line_buffer', return_value='/session zz'):
            self.assertIsNone(self.chat._completer('zz', 0))

    def test_plain_input_no_completion(self):
        self.assertIsNone(self._complete('hello', 'hello'))

    def test_path_completion_file(self):
        root = Path(self.chat._tmp.name)
        (root / 'notes.md').write_text('x')
        (root / 'notes.txt').write_text('x')
        prefix = str(root / 'notes')
        options = self._complete('/tool read_file ' + prefix, prefix)
        self.assertEqual(options, str(root / 'notes.md') + ' ')

    def test_path_completion_dir_trailing_slash(self):
        root = Path(self.chat._tmp.name)
        (root / 'src').mkdir()
        prefix = str(root / 's')
        options = self._complete('/tool read_file ' + prefix, prefix)
        self.assertEqual(options, str(root / 'src') + '/')

    def test_setup_readline_libedit_binding(self):
        with patch('polyglav.chat.readline') as rl:
            rl.__doc__ = 'libedit readline'
            self.chat._setup_readline()
            rl.set_completer_delims.assert_called_once_with(' \t\n')
            rl.parse_and_bind.assert_called_once_with('bind ^I rl_complete')

    def test_setup_readline_gnu_binding(self):
        with patch('polyglav.chat.readline') as rl:
            rl.__doc__ = 'GNU readline'
            self.chat._setup_readline()
            rl.parse_and_bind.assert_called_once_with('tab: complete')
