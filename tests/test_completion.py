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

    def test_provider_completion(self):
        self.chat.providers.put('acme-example', 'https://llm.acme.example/v1', 'k')
        self.assertEqual(self._complete('/connect acme', 'acme'), 'acme-example ')
        self.assertEqual(self._complete('/provider olla', 'olla'), 'ollama ')
        self.assertEqual(self._complete('/providers olla', 'olla'), 'ollama ')

    def test_model_ref_provider_completion(self):
        self.assertEqual(self._complete('/model olla', 'olla'), 'ollama/')

    def test_model_ref_model_completion(self):
        self.chat.models.put('opencode-go', 'deepseek-v4-flash')
        self.assertEqual(
            self._complete('/model opencode-go/deep', 'opencode-go/deep'),
            'opencode-go/deepseek-v4-flash ')

    def test_model_ref_completion_from_cache(self):
        self.chat._model_cache = {'opencode-go': ['deepseek-v4.1-flash']}
        self.assertEqual(
            self._complete('/model opencode-go/deep', 'opencode-go/deep'),
            'opencode-go/deepseek-v4.1-flash ')

    def test_models_list_provider_completion(self):
        self.assertEqual(self._complete('/models list olla', 'olla'), 'ollama ')

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
