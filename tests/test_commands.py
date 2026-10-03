import unittest
import io
import json
from unittest.mock import patch

from tests.helpers import make_chat


class TestToolCommand(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def _global_raw(self):
        p = self.chat.config.global_path
        return json.loads(p.read_text()) if p.exists() else {}

    def _local_raw(self):
        p = self.chat.config.local_path
        return json.loads(p.read_text()) if p.exists() else {}

    def _search_service(self):
        return self.chat._plugin_manager.service('search')

    def test_tool_lists_names_without_args(self):
        output = self._dispatch('/tool')
        self.assertIn('web_search', output)
        self.assertIn('fetch_page', output)

    def test_help_lists_aliases_inline(self):
        output = self._dispatch('/help')
        self.assertIn('/help, /h', output)
        self.assertIn('/exit, /quit, /q', output)
        self.assertNotIn('aliases:', output)

    def test_help_shows_subcommands(self):
        output = self._dispatch('/help')
        self.assertIn('new', output)
        self.assertIn('Start a new session', output)
        self.assertIn('load', output)
        self.assertIn('List saved sessions', output)

    def test_help_subcommand_indent(self):
        output = self._dispatch('/help')
        self.assertIn('\n    new', output)

    def test_help_lists_tools_under_tool(self):
        self.chat.config.set('mode', 'write')
        output = self._dispatch('/help')
        self.assertNotIn('Available tools:', output)
        self.assertIn('\n    run_command', output)
        self.assertIn('Run a shell command', output)
        self.assertIn('Find files matching a glob pattern', output)
        self.assertNotIn('[exec · bash: ask]', output)

    def test_help_tool_shows_tool_rows(self):
        output = self._dispatch('/help tool')
        self.assertIn('\n    read_file', output)
        self.assertIn('Read the contents of a text file', output)

    def test_help_tool_detail(self):
        output = self._dispatch('/help read_file')
        self.assertIn('category: read', output)
        self.assertIn('path (required)', output)
        self.assertIn('offset (optional)', output)

    def test_help_tool_detail_has_permission(self):
        self.chat.config.set('mode', 'write')
        output = self._dispatch('/help run_command')
        self.assertIn('category: exec', output)
        self.assertIn('permission: bash: ask', output)
        self.assertIn('command (required)', output)

    def test_help_command_by_name(self):
        output = self._dispatch('/help session')
        self.assertIn('Start a new session', output)

    def test_help_alias_resolution(self):
        output = self._dispatch('/help h')
        self.assertIn('Show available commands and tools', output)

    def test_help_unknown(self):
        output = self._dispatch('/help nosuch')
        self.assertIn('No help available for "nosuch"', output)

    def test_tool_listing_points_to_help(self):
        output = self._dispatch('/tool')
        self.assertIn('Use /help <tool> for details', output)
        self.assertNotIn(', web_search', output)

    def test_session_no_args_shows_current(self):
        output = self._dispatch('/session')
        self.assertIn('Current session:', output)
        self.assertIn('context', output)

    def test_sessions_no_args_lists(self):
        s = self.chat.sessions.create('saved1')
        s.add_user('x')
        self.chat.sessions.save(s)
        output = self._dispatch('/sessions')
        self.assertIn('saved1', output)

    def test_session_new_switches_current_session(self):
        old = self.chat.current_session
        self._dispatch('/session new')
        self.assertIsNot(self.chat.current_session, old)
        self.assertEqual(self.chat.current_session.turns, [])

    def test_session_load_switches_current_session(self):
        old = self.chat.current_session
        s = self.chat.sessions.create('saved1')
        s.add_user('hello from saved session')
        self.chat.sessions.save(s)
        with patch('polyglav.commands.builtins.input', return_value='n'):
            self._dispatch('/session load saved1')
        self.assertIsNot(self.chat.current_session, old)
        texts = [p['text'] for t in self.chat.current_session.turns
                 for p in t.get('parts') or []]
        self.assertEqual(texts, ['hello from saved session', '/session load saved1'])

    def test_session_load_shows_context_size(self):
        s = self.chat.sessions.create('saved2')
        s.add_user('hello world')
        self.chat.sessions.save(s)
        with patch('polyglav.commands.builtins.input', return_value='n'):
            output = self._dispatch('/session load saved2')
        self.assertIn('messages', output)
        self.assertIn('context', output)

    def test_session_load_not_found(self):
        output = self._dispatch('/session load nosuch')
        self.assertIn('Session not found: nosuch', output)

    def test_session_load_offers_compact(self):
        s = self.chat.sessions.create('big1')
        s.add_user('x')
        self.chat.sessions.save(s)
        self.chat.compact_session = unittest.mock.MagicMock()
        with patch('polyglav.commands.builtins.input', return_value='y'):
            self._dispatch('/session load big1')
        self.chat.compact_session.assert_called_once()

    def test_session_load_declines_compact(self):
        s = self.chat.sessions.create('big2')
        s.add_user('x')
        self.chat.sessions.save(s)
        self.chat.compact_session = unittest.mock.MagicMock()
        with patch('polyglav.commands.builtins.input', return_value='n'):
            self._dispatch('/session load big2')
        self.chat.compact_session.assert_not_called()

    def test_session_preview_does_not_switch_current(self):
        old = self.chat.current_session
        s = self.chat.sessions.create('pv1')
        s.add_user('hello')
        s.add_tool('web_search', {})
        self.chat.sessions.save(s)
        output = self._dispatch('/sessions preview pv1')
        self.assertIs(self.chat.current_session, old)
        self.assertIn('1 turns', output)
        self.assertIn('web_search', output)

    def test_session_preview_not_found(self):
        output = self._dispatch('/sessions preview nosuch')
        self.assertIn('Session not found: nosuch', output)

    def test_compact_dispatch_calls_compaction(self):
        self.chat.compact_session = unittest.mock.MagicMock()
        self._dispatch('/compact')
        self.chat.compact_session.assert_called_once()

    def test_version_prints_version(self):
        from polyglav import get_version
        output = self._dispatch('/version')
        self.assertIn(get_version(), output)

    def test_config_parses_json_list(self):
        self._dispatch('/config tools.deny ["run_command", "web_search"]')
        self.assertEqual(self.chat.config.get('tools.deny'),
                         ['run_command', 'web_search'])

    def test_config_parses_numbers(self):
        self._dispatch('/config temperature 0.3')
        self._dispatch('/config max_tokens 4096')
        self.assertEqual(self.chat.config.get('temperature'), 0.3)
        self.assertEqual(self.chat.config.get('max_tokens'), 4096)

    def test_config_add_item(self):
        self.chat.config.set('tools.deny', ['run_command'])
        self._dispatch('/config tools.deny -a write_file')
        self.assertIn('write_file', self.chat.config.get('tools.deny'))

    def test_config_add_creates_list(self):
        self._dispatch('/config tools.deny -a run_command')
        self.assertEqual(self.chat.config.get('tools.deny'), ['run_command'])

    def test_config_remove_item(self):
        self.chat.config.set('tools.deny', ['run_command', 'write_file'])
        self._dispatch('/config tools.deny -r run_command')
        self.assertNotIn('run_command', self.chat.config.get('tools.deny'))

    def test_config_unknown_key_prompts(self):
        with patch('polyglav.commands.builtins.input', return_value='y'):
            self._dispatch('/config frobnicate 1')
        self.assertEqual(self.chat.config.get('frobnicate'), 1)

    def test_config_unknown_key_declined(self):
        with patch('polyglav.commands.builtins.input', return_value='n'):
            output = self._dispatch('/config frobnicate 1')
        self.assertIn('Skipped', output)
        self.assertIsNone(self.chat.config.get('frobnicate'))

    def test_config_instances_do_not_share_lists(self):
        self._dispatch('/config tools.deny -a run_command')
        other = make_chat()
        try:
            self.assertEqual(other.config.get('tools.deny'), [])
        finally:
            other._tmp.cleanup()

    def test_config_default_scope_is_local(self):
        self._dispatch('/config temperature 0.3')
        self.assertEqual(self._local_raw().get('temperature'), 0.3)
        self.assertEqual(self._global_raw().get('temperature'), None)

    def test_config_global_flag_writes_global(self):
        output = self._dispatch('/config --global temperature 0.3')
        self.assertIn('(global)', output)
        self.assertEqual(self._global_raw().get('temperature'), 0.3)
        self.assertEqual(self._local_raw().get('temperature'), 0.7)

    def test_config_global_api_key_writes_global(self):
        output = self._dispatch('/config --global api_key sk-456')
        self.assertEqual(self._global_raw().get('api_key'), 'sk-456')
        self.assertEqual(self._local_raw().get('api_key'), '')
        self.assertIn('sk-456', output)

    def test_config_local_flag_explicit(self):
        self._dispatch('/config --local temperature 0.4')
        self.assertEqual(self._local_raw().get('temperature'), 0.4)
        self.assertNotIn('temperature', self._global_raw())

    def test_config_global_unset(self):
        self._dispatch('/config --global temperature 0.3')
        output = self._dispatch('/config --global unset temperature')
        self.assertIn('(global config)', output)
        self.assertNotIn('temperature', self._global_raw())
        self.assertEqual(self.chat.config.get('temperature'), 0.7)

    def test_config_global_list_op(self):
        self._dispatch('/config --global tools.deny -a run_command')
        self.assertEqual(self._global_raw().get('tools.deny'), ['run_command'])
        self.assertEqual(self._local_raw().get('tools.deny', []), [])

    def test_tool_executes_via_registry(self):
        with patch.object(self._search_service(), 'search', return_value=[
            {'title': 'T', 'url': 'http://x.com', 'snippet': 'S'}
        ]) as search_mock:
            output = self._dispatch('/tool web_search {"query": "python news"}')
        search_mock.assert_called_once_with('python news')
        self.assertIn('python news', output)

    def test_tool_disabled_when_tool_calling_off(self):
        self.chat.config.set('tool_calling', False)
        output = self._dispatch('/tool web_search {"query": "x"}')
        self.assertIn('disabled', output)

    def test_tool_invalid_json(self):
        output = self._dispatch('/tool web_search not-json')
        self.assertIn('Usage: /tool', output)

    def test_tool_denied_by_policy(self):
        self.chat.config.set('tools.deny', ['web_search'])
        output = self._dispatch('/tool web_search {"query": "x"}')
        self.assertIn('disabled by tool policy', output)

    def test_tool_listing_respects_deny(self):
        self.chat.config.set('tools.deny', ['web_search'])
        output = self._dispatch('/tool')
        self.assertNotIn('\n  web_search', output)
        self.assertIn('\n  read_file', output)

    def test_tool_ask_prompt_declined(self):
        self.chat.config.set('tool_permission', {'web': 'ask'})
        with patch('polyglav.ui.input', return_value='n'):
            output = self._dispatch('/tool web_search {"query": "x"}')
        self.assertIn('[cancelled]', output)

    def test_tool_ask_prompt_accepted(self):
        self.chat.config.set('tool_permission', {'web': 'ask'})
        with patch.object(self._search_service(), 'search', return_value=[
            {'title': 'T', 'url': 'http://x.com', 'snippet': 'S'}
        ]), patch('polyglav.ui.input', return_value='y'):
            output = self._dispatch('/tool web_search {"query": "python"}')
        self.assertNotIn('[cancelled]', output)
        self.assertIn('python', output)

    def test_schema_filters_denied_tools(self):
        self.chat.config.set('tools.deny', ['web_search', 'run_command'])
        schema = self.chat._init_tooling()
        names = [s['function']['name'] for s in schema]
        self.assertNotIn('web_search', names)
        self.assertNotIn('run_command', names)
        self.assertIn('file_read', names)


class TestConnectCommand(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line, inputs=None):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            if inputs is None:
                self.chat.registry.dispatch(line)
            else:
                with patch('polyglav.commands.builtins.input', side_effect=inputs):
                    self.chat.registry.dispatch(line)
        return out.getvalue()

    def test_connect_pick_lists_providers(self):
        self.chat.providers.put('openai', 'https://api.openai.com/v1', 'oak')
        with patch('polyglav.commands.builtins.input', side_effect=EOFError):
            output = self._dispatch('/connect')
        self.assertIn('1. ollama', output)
        self.assertIn('openai (key)', output)

    def test_connect_named_presets_defaults(self):
        with patch.object(self.chat, 'check_connection',
                          return_value=(True, '3 models available', [])) as probe:
            output = self._dispatch('/connect ollama', ['sk-123'])
        probe.assert_called_once_with(
            base_url='https://api.ollama.com', api_key='sk-123', provider='ollama')
        self.assertIn('Connected to ollama (https://api.ollama.com)', output)
        self.assertIn('Added provider "ollama"', output)
        entry = self.chat.providers.find('ollama')
        self.assertEqual(entry.api_key, 'sk-123')
        self.assertEqual(entry.base_url, 'https://api.ollama.com')
        self.assertEqual(self.chat.config.get('provider'), 'ollama')
        self.assertEqual(self.chat.config.get('base_url'), 'https://api.ollama.com')
        self.assertEqual(self.chat.config.get('model'), 'test-model')

    def test_connect_named_reenters_stored_key(self):
        self.chat.providers.put('ollama', 'https://api.ollama.com', 'old-key')
        with patch.object(self.chat, 'check_connection',
                          return_value=(True, 'ok', [])):
            with patch('polyglav.commands.builtins.input',
                       side_effect=['new-key']) as inp:
                output = self._dispatch('/connect ollama')
        inp.assert_called_once_with('  API key [<stored>]: ')
        self.assertEqual(self.chat.providers.api_key_for('ollama'), 'new-key')
        self.assertIn('Updated provider "ollama"', output)

    def test_connect_named_keeps_stored_key(self):
        self.chat.providers.put('ollama', 'https://api.ollama.com', 'old-key')
        with patch.object(self.chat, 'check_connection',
                          return_value=(True, 'ok', [])):
            self._dispatch('/connect ollama', [''])
        self.assertEqual(self.chat.providers.api_key_for('ollama'), 'old-key')

    def test_connect_named_unknown_provider(self):
        with patch.object(self.chat, 'check_connection') as probe:
            output = self._dispatch('/connect nope')
        probe.assert_not_called()
        self.assertIn('Unknown provider "nope"', output)
        self.assertIn('1. ollama', output)

    def test_connect_url_known_host(self):
        with patch.object(self.chat, 'check_connection',
                          return_value=(True, 'ok', [])) as probe:
            output = self._dispatch('/connect https://api.openai.com/v1', ['sk-openai'])
        probe.assert_called_once_with(
            base_url='https://api.openai.com/v1', api_key='sk-openai', provider='openai')
        self.assertIn('Detected provider "openai"', output)
        self.assertEqual(self.chat.config.get('provider'), 'openai')
        self.assertEqual(self.chat.config.get('base_url'), 'https://api.openai.com/v1')

    def test_connect_url_known_host_keeps_url(self):
        with patch.object(self.chat, 'check_connection',
                          return_value=(True, 'ok', [])) as probe:
            self._dispatch('/connect https://api.openai.com', [''])
        probe.assert_called_once_with(
            base_url='https://api.openai.com', api_key='', provider='openai')
        self.assertEqual(self.chat.config.get('base_url'), 'https://api.openai.com')

    def test_connect_url_plugin_default_match(self):
        from polyglav.providers.base import OpenAICompatibleProvider

        class _PluginProvider(OpenAICompatibleProvider):
            DEFAULT_BASE_URL = 'https://llm.acme.example/v1'
            DEFAULT_MODEL = 'acme-model'

        self.chat._plugin_manager._provider_classes = {'acme': _PluginProvider}
        with patch.object(self.chat, 'check_connection',
                          return_value=(True, 'ok', [])) as probe:
            self._dispatch('/connect https://llm.acme.example/v1', ['sk'])
        probe.assert_called_once_with(
            base_url='https://llm.acme.example/v1', api_key='sk', provider='acme')
        self.assertEqual(self.chat.config.get('provider'), 'acme')

    def test_connect_url_custom_derives_name(self):
        with patch.object(self.chat, 'check_connection',
                          return_value=(True, 'ok', [])) as probe:
            output = self._dispatch('/connect https://llm.acme.example/v1', ['sk'])
        self.assertIn('New provider name: acme-example', output)
        probe.assert_called_once_with(
            base_url='https://llm.acme.example/v1', api_key='sk', provider='acme-example')
        self.assertEqual(self.chat.config.get('provider'), 'acme-example')
        self.assertEqual(self.chat.config.get('base_url'), 'https://llm.acme.example/v1')
        self.assertEqual(self.chat.providers.api_key_for('acme-example'), 'sk')

    def test_connect_url_custom_name_override(self):
        with patch.object(self.chat, 'check_connection',
                          return_value=(True, 'ok', [])) as probe:
            self._dispatch('/connect https://llm.acme.example/v1 mymodels', ['sk'])
        probe.assert_called_once_with(
            base_url='https://llm.acme.example/v1', api_key='sk', provider='mymodels')
        self.assertEqual(self.chat.config.get('provider'), 'mymodels')

    def test_connect_url_bare_hostname(self):
        with patch.object(self.chat, 'check_connection',
                          return_value=(True, 'ok', [])) as probe:
            self._dispatch('/connect models.example.com', ['sk'])
        probe.assert_called_once_with(
            base_url='https://models.example.com', api_key='sk', provider='example-com')

    def test_connect_failure_declined_leaves_config(self):
        with patch.object(self.chat, 'check_connection',
                          return_value=(False, 'HTTP 401: bad key', [])):
            output = self._dispatch('/connect ollama', ['sk-bad', 'n'])
        self.assertIn('[Error] Connection test failed: HTTP 401: bad key', output)
        self.assertIn('Connection not saved', output)
        self.assertIsNone(self.chat.providers.find('ollama'))
        self.assertEqual(self.chat.config.get('base_url'), 'https://test.api.com')

    def test_connect_failure_accepted_saves(self):
        with patch.object(self.chat, 'check_connection',
                          return_value=(False, 'HTTP 500: boom', [])):
            output = self._dispatch('/connect ollama', ['sk-risk', 'y'])
        self.assertIn('Connected to ollama (https://api.ollama.com)', output)
        self.assertEqual(self.chat.providers.api_key_for('ollama'), 'sk-risk')

    def test_connect_check_disabled_skips_probe(self):
        self.chat.config.set('connect_check', False)
        with patch.object(self.chat, 'check_connection') as probe:
            output = self._dispatch('/connect ollama', ['sk-123'])
        probe.assert_not_called()
        self.assertIn('Connected to ollama (https://api.ollama.com)', output)
        self.assertEqual(self.chat.providers.api_key_for('ollama'), 'sk-123')

    def test_connect_pick_number(self):
        with patch.object(self.chat, 'check_connection',
                          return_value=(True, 'ok', [])) as probe:
            self._dispatch('/connect', ['1', 'sk'])
        probe.assert_called_once_with(
            base_url='https://api.ollama.com', api_key='sk', provider='ollama')

    def test_connect_pick_url(self):
        with patch.object(self.chat, 'check_connection',
                          return_value=(True, 'ok', [])) as probe:
            self._dispatch('/connect', ['https://llm.acme.example/v1', 'sk'])
        probe.assert_called_once_with(
            base_url='https://llm.acme.example/v1', api_key='sk', provider='acme-example')

    def test_connect_pick_bad_number(self):
        with patch.object(self.chat, 'check_connection') as probe:
            output = self._dispatch('/connect', ['9'])
        probe.assert_not_called()
        self.assertIn('Unknown provider number "9"', output)

    def test_connect_pick_stored_custom_provider(self):
        self.chat.providers.put('acme-example', 'https://llm.acme.example/v1', 'sk')
        self.chat.config.set('provider', 'acme-example')
        with patch.object(self.chat, 'check_connection',
                          return_value=(True, 'ok', [])) as probe:
            self._dispatch('/connect', ['', 'new-sk'])
        probe.assert_called_once_with(
            base_url='https://llm.acme.example/v1', api_key='new-sk',
            provider='acme-example')
        self.assertEqual(self.chat.providers.api_key_for('acme-example'), 'new-sk')


class TestModelCommand(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def test_model_switch_touches_registry(self):
        self.chat.models.put('ollama', 'test-model')
        output = self._dispatch('/model test-model')
        self.assertIn('Model set to: test-model', output)
        entry = self.chat.models.find('ollama', 'test-model')
        self.assertIsNotNone(entry)

    def test_model_ref_unfolds(self):
        self.chat.models.put('opencode-go', 'deepseek-v4-flash')
        self.chat.providers.put('opencode-go',
                                'https://opencode.ai/zen/go/v1', 'k')
        output = self._dispatch('/model opencode-go/deepseek-v4-flash')
        self.assertIn('Model set to: opencode-go/deepseek-v4-flash', output)
        self.assertEqual(self.chat.config.get('provider'), 'opencode-go')
        self.assertEqual(self.chat.config.get('model'), 'deepseek-v4-flash')
        self.assertEqual(self.chat.config.get('base_url'),
                         'https://opencode.ai/zen/go/v1')

    def test_model_ref_unapproved_prompts_and_approves(self):
        self.chat.providers.put('opencode-go',
                                'https://opencode.ai/zen/go/v1', 'k')
        with patch('builtins.input', return_value='y'):
            output = self._dispatch('/model opencode-go/deepseek-v4-flash')
        self.assertIn('Model set to: opencode-go/deepseek-v4-flash', output)
        self.assertIsNotNone(
            self.chat.models.find('opencode-go', 'deepseek-v4-flash'))

    def test_model_ref_declined_prompt(self):
        with patch('builtins.input', return_value='n'):
            output = self._dispatch('/model opencode-go/deepseek-v4-flash')
        self.assertIn('Model not approved', output)

    def test_model_bare_shows_current(self):
        output = self._dispatch('/model')
        self.assertIn('Current model: test-model', output)
        self.assertIn('(ollama @ https://test.api.com)', output)


class TestModelsCommand(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def test_models_shows_configured(self):
        self.chat.models.put('openai', 'gpt-4o')
        self.chat.providers.put('openai', 'https://api.openai.com/v1', 'k')
        output = self._dispatch('/models')
        self.assertIn('openai:', output)
        self.assertIn('gpt-4o', output)
        self.assertIn('(key)', output)

    def test_models_marks_active(self):
        self.chat.models.put('ollama', 'test-model')
        self.chat.models.put('ollama', 'other')
        output = self._dispatch('/models')
        self.assertIn('> test-model', output)

    def test_models_empty(self):
        output = self._dispatch('/models')
        self.assertIn('No models configured yet', output)

    def test_models_usage(self):
        output = self._dispatch('/models bogus')
        self.assertIn('Usage: /models', output)

    def test_models_list_probes_provider(self):
        self.chat.models.put('openai', 'gpt-4o')
        self.chat.providers.put('openai', 'https://api.openai.com/v1', 'oak')
        with patch.object(self.chat, 'list_models',
                          return_value=(['gpt-4o', 'gpt-5'], None)) as lm:
            output = self._dispatch('/models list openai')
        lm.assert_called_once_with(
            provider='openai', base_url='https://api.openai.com/v1',
            api_key='oak', model='gpt-4o')
        self.assertIn('gpt-4o', output)
        self.assertIn('gpt-5', output)

    def test_models_list_defaults_to_current_provider(self):
        with patch.object(self.chat, 'list_models',
                          return_value=(['m1', 'm2'], None)) as lm:
            output = self._dispatch('/models list')
        lm.assert_called_once_with(
            provider='ollama', base_url='https://test.api.com',
            api_key='', model='test-model')
        self.assertIn('2 models available from ollama (https://test.api.com)', output)

    def test_models_list_error(self):
        with patch.object(self.chat, 'list_models',
                          return_value=([], 'HTTP 401: bad key')):
            output = self._dispatch('/models list')
        self.assertIn('[Error] Failed to list models: HTTP 401: bad key', output)
        self.assertIn('run /connect to fix', output)

    def test_models_list_empty(self):
        with patch.object(self.chat, 'list_models', return_value=([], None)):
            output = self._dispatch('/models list')
        self.assertIn('No models listed from ollama (https://test.api.com)', output)

    def test_models_list_notes_missing_configured_model(self):
        with patch.object(self.chat, 'list_models',
                          return_value=(['a', 'b'], None)):
            output = self._dispatch('/models list')
        self.assertIn('(configured model "test-model" not in the model list)', output)


class TestProviderWarn(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def test_provider_failed_probe_warns(self):
        with patch.object(self.chat, 'check_connection',
                          return_value=(False, 'HTTP 500: boom', [])):
            output = self._dispatch('/provider openai')
        self.assertIn('Provider set to: openai', output)
        self.assertIn('Warning: connection test failed - HTTP 500: boom', output)
        self.assertIn('Run /connect', output)

    def test_provider_success_no_warning(self):
        with patch.object(self.chat, 'check_connection',
                          return_value=(True, 'ok', [])):
            output = self._dispatch('/provider openai')
        self.assertIn('Provider set to: openai', output)
        self.assertNotIn('Warning', output)

    def test_provider_no_probe_when_disabled(self):
        self.chat.config.set('connect_check', False)
        with patch.object(self.chat, 'check_connection') as probe:
            output = self._dispatch('/provider openai')
        probe.assert_not_called()
        self.assertNotIn('Warning', output)


class TestReadlineCompleter(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _buffer(self, line):
        return patch('polyglav.chat.readline.get_line_buffer', return_value=line)

    def _make_sessions(self, *names):
        for n in names:
            s = self.chat.sessions.create(n)
            s.add_user('x')
            self.chat.sessions.save(s)

    def test_session_load_completes_names(self):
        self._make_sessions('alpha_01', 'alpha_02', 'beta_01')
        with self._buffer('/session load alpha_'):
            self.assertEqual(self.chat._completer('alpha_', 0), 'alpha_01 ')
            self.assertEqual(self.chat._completer('alpha_', 1), 'alpha_02 ')
            self.assertIsNone(self.chat._completer('alpha_', 2))

    def test_session_delete_completes_names(self):
        self._make_sessions('alpha_01')
        with self._buffer('/sessions delete alpha_'):
            self.assertEqual(self.chat._completer('alpha_', 0), 'alpha_01 ')
            self.assertIsNone(self.chat._completer('alpha_', 1))

    def test_session_load_empty_prefix_lists_all(self):
        self._make_sessions('alpha_01', 'beta_01')
        with self._buffer('/session load '):
            matches = []
            i = 0
            while True:
                m = self.chat._completer('', i)
                if m is None:
                    break
                matches.append(m)
                i += 1
        self.assertEqual(matches, ['alpha_01 ', 'beta_01 '])

    def test_command_completion_still_works(self):
        with self._buffer('/se'):
            self.assertEqual(self.chat._completer('/se', 0), '/session ')

    def test_command_completion_without_slash_prefix(self):
        with self._buffer('se'):
            self.assertIsNone(self.chat._completer('se', 0))

    def test_command_completion_outside_session_context(self):
        with self._buffer('/session'):
            self.assertEqual(self.chat._completer('/session', 0), '/session ')


class TestThinkingCommand(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def test_thinking_reports_current_state(self):
        output = self._dispatch('/thinking')
        self.assertIn('Thinking streaming: off', output)

    def test_thinking_off(self):
        output = self._dispatch('/thinking off')
        self.assertIn('Thinking streaming: off', output)
        self.assertIs(self.chat.config.get('show_thinking'), False)

    def test_thinking_on(self):
        output = self._dispatch('/thinking on')
        self.assertIn('Thinking streaming: on', output)
        self.assertIs(self.chat.config.get('show_thinking'), True)

    def test_thinking_status_no_change(self):
        self._dispatch('/thinking on')
        output = self._dispatch('/thinking status')
        self.assertIn('Thinking streaming: on', output)
        self.assertIs(self.chat.config.get('show_thinking'), True)

    def test_thinking_invalid_arg(self):
        self._dispatch('/thinking on')
        output = self._dispatch('/thinking bogus')
        self.assertIn('Usage: /thinking', output)
        self.assertIs(self.chat.config.get('show_thinking'), True)


class TestModeCommand(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def test_mode_shows_current_and_list(self):
        output = self._dispatch('/mode')
        self.assertIn('Current mode: read', output)
        self.assertIn('write', output)
        self.assertIn('read  <-- current', output)

    def test_mode_switch(self):
        output = self._dispatch('/mode write')
        self.assertIn('Mode set to: write', output)
        self.assertEqual(self.chat.config.get('mode'), 'write')

    def test_mode_unknown(self):
        output = self._dispatch('/mode nosuch')
        self.assertIn('Unknown mode "nosuch"', output)
        self.assertIn('read', output)
        self.assertEqual(self.chat.config.get('mode'), 'read')

    def test_read_mode_denies_write_tool(self):
        self._dispatch('/mode read')
        output = self._dispatch('/tool write_file {"path": "x.txt", "content": "x"}')
        self.assertIn('disabled by tool policy', output)

    def test_read_mode_filters_schema(self):
        self._dispatch('/mode read')
        schema = self.chat._init_tooling()
        names = [s['function']['name'] for s in schema]
        self.assertNotIn('file_write', names)
        self.assertNotIn('run_command', names)
        self.assertIn('file_read', names)

    def test_read_mode_tool_listing_hides_write_tools(self):
        self._dispatch('/mode read')
        output = self._dispatch('/tool')
        self.assertNotIn('\n  write_file', output)
        self.assertNotIn('\n  run_command', output)
        self.assertIn('\n  read_file', output)

    def test_read_mode_help_hides_write_tools(self):
        self._dispatch('/mode read')
        output = self._dispatch('/help')
        self.assertNotIn('\n    write_file', output)
        self.assertNotIn('\n    run_command', output)
        self.assertIn('\n    read_file', output)
        self.assertIn('\n    list_dir', output)

    def test_switch_back_to_write_restores_tools(self):
        self._dispatch('/mode read')
        self._dispatch('/mode write')
        schema = self.chat._init_tooling()
        names = [s['function']['name'] for s in schema]
        self.assertIn('file_write', names)
        self.assertIn('run_command', names)


class TestModeCompleter(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def test_mode_completes_names(self):
        with patch('polyglav.chat.readline.get_line_buffer', return_value='/mode w'):
            self.assertEqual(self.chat._completer('w', 0), 'write ')
            self.assertIsNone(self.chat._completer('w', 1))
        with patch('polyglav.chat.readline.get_line_buffer', return_value='/mode '):
            matches = []
            i = 0
            while True:
                m = self.chat._completer('', i)
                if m is None:
                    break
                matches.append(m)
                i += 1
        self.assertEqual(matches, ['read ', 'write '])


if __name__ == '__main__':
    unittest.main()
