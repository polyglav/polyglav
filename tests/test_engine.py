import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from polyglav.config import Config
from polyglav.engine import Engine
from polyglav.plugins.manager import PluginManager
from polyglav.sessions.manager import SessionManager
from polyglav.runs import RunRegistry
from polyglav.ui import HeadlessUI, NullUI


def make_engine(config_data: dict | None = None) -> Engine:
    temp_dir = tempfile.TemporaryDirectory()
    Config.GLOBAL_DIR = Path(temp_dir.name) / 'global-home'
    data = {
        'tool_calling': True,
        'provider': 'ollama',
        'model': 'test-model',
        'base_url': 'https://test.api.com',
        'api_key': '',
        'temperature': 0.7,
        'max_tokens': 2048,
    }
    if config_data:
        data.update(config_data)
    config_dir = Path(temp_dir.name) / '.polyglav'
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_dir / 'config.json', 'w') as f:
        json.dump(data, f)

    config = Config(path=temp_dir.name)
    engine = Engine.__new__(Engine)
    engine.config = config
    engine.provider = MagicMock()
    sessions_dir = config.local_path.parent / 'sessions'
    engine.sessions = SessionManager(sessions_dir)
    engine.current_session = engine.sessions.create()
    engine._tool_registry = None
    engine._ask_ui = None
    engine._caller = None
    engine.role = ''
    engine.runs = RunRegistry()
    engine.current_run = engine.runs.start(role='', session=engine.current_session.session_name)
    engine._plugin_manager = PluginManager(config)
    engine._plugin_manager.load()
    engine._tmp = temp_dir
    return engine


class _CaptureUI:
    def __init__(self):
        self.labels = []

    def activity(self, glyph, verb, label, body):
        self.labels.append(f'{glyph} {verb} {label}')

    def tool_status(self, name, value, body):
        self.labels.append(f'[{name}: {value}]')

    def tool_error(self, msg):
        self.labels.append(f'! {msg.split(chr(10), 1)[0]}')

    def tool_note(self, output):
        lines = [l for l in output.splitlines() if l]
        self.labels.append(f'[{lines[-1]}]')

    def confirm(self, name, label):
        self.labels.append(f'confirm: {label}')
        return True


class TestEngine(unittest.TestCase):

    def setUp(self):
        self.engine = make_engine()

    def tearDown(self):
        self.engine._tmp.cleanup()

    def test_reinit_provider_uses_registry_api_key(self):
        self.engine.providers.put('ollama', 'https://test.api.com', 'reg-key')
        self.engine.config.apply('api_key', 'cfg-key')
        self.engine._reinit_provider()
        self.assertEqual(self.engine.provider.api_key, 'reg-key')

    def test_reinit_provider_no_registry_key_is_empty(self):
        self.engine.config.apply('api_key', 'cfg-key')
        self.assertIsNone(self.engine.providers.find('ollama'))
        self.engine._reinit_provider()
        self.assertEqual(self.engine.provider.api_key, '')

    def test_reinit_provider_uses_registry_base_url_when_config_empty(self):
        self.engine.config.apply('base_url', '')
        self.engine.providers.put('ollama', 'https://custom.example/v1', 'k')
        self.engine._reinit_provider()
        self.assertEqual(self.engine.provider.base_url, 'https://custom.example/v1')

    def test_chat_returns_turn_result(self):
        self.engine.provider.chat.return_value = [
            {'type': 'token', 'content': 'Hello world'},
            {'type': 'done', 'reason': 'stop'},
        ]
        result = self.engine.chat('hi')
        self.assertEqual(result.content, 'Hello world')
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.provider, 'ollama')
        self.assertEqual(result.session, self.engine.current_session.session_name)
        roles = [p['type'] for t in self.engine.current_session.turns
                 for p in t.get('parts') or []]
        self.assertEqual(roles, ['user', 'text'])
        self.assertEqual(result.tool_calls, [])
        self.assertEqual(result.errors, [])

    def test_thinking_separated_from_content(self):
        self.engine.provider.chat.return_value = [
            {'type': 'token', 'content': '<thinking>hmm</thinking>Answer'},
            {'type': 'done', 'reason': 'stop'},
        ]
        result = self.engine.chat('q')
        self.assertEqual(result.content, 'Answer')
        self.assertEqual(result.thinking, '<thinking>hmm')

    def test_provider_thinking_event_accumulates(self):
        self.engine.provider.chat.return_value = [
            {'type': 'thinking', 'content': 'reasoning'},
            {'type': 'token', 'content': 'Answer'},
            {'type': 'done', 'reason': 'stop'},
        ]
        result = self.engine.chat('q')
        self.assertEqual(result.thinking, 'reasoning')
        self.assertEqual(result.content, 'Answer')

    def test_reasoning_and_thinking_persisted_to_session(self):
        self.engine.config.set('reasoning', 'high')
        self.engine.provider.chat.return_value = [
            {'type': 'thinking', 'content': 'secret reasoning'},
            {'type': 'token', 'content': 'Answer'},
            {'type': 'done', 'reason': 'stop'},
        ]
        result = self.engine.chat('q')
        thinking = [p for t in self.engine.current_session.turns
                    for p in t.get('parts') or [] if p['type'] == 'thinking'][0]
        self.assertEqual(thinking['text'], 'secret reasoning')
        self.assertEqual(self.engine.current_session.turns[0]['reasoning'], 'high')

    def test_reasoning_persisted_when_thinking_hidden_from_display(self):
        self.engine.config.set('show_thinking', False)
        self.engine.config.set('reasoning', 'auto')
        self.engine.provider.chat.return_value = [
            {'type': 'thinking', 'content': 'still logged'},
            {'type': 'token', 'content': 'Answer'},
            {'type': 'done', 'reason': 'stop'},
        ]
        self.engine.chat('q')
        thinking = [p for t in self.engine.current_session.turns
                    for p in t.get('parts') or [] if p['type'] == 'thinking'][0]
        self.assertEqual(thinking['text'], 'still logged')
        self.assertEqual(self.engine.current_session.turns[0]['reasoning'], 'auto')

    def test_error_status_and_errors(self):
        self.engine.provider.chat.return_value = [
            {'type': 'error', 'code': 401, 'message': 'Unauthorized'},
        ]
        result = self.engine.chat('q')
        self.assertEqual(result.status, 'error')
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0]['code'], 401)
        self.assertEqual(result.errors[0]['message'], 'Unauthorized')

    def test_auto_session_name_embeds_id(self):
        name = self.engine.current_session.session_name
        code = self.engine.current_session.session_id
        self.assertTrue(name.startswith('ses_'))
        self.assertTrue(name.endswith(f'_{code}'))
        self.assertEqual(len(code), 6)
        self.assertTrue(all(c in '0123456789abcdefghijklmnopqrstuvwxyz'
                            for c in code))
        self.assertIn('_', name)

    def test_session_name_stable_across_turns(self):
        self.engine.provider.chat.return_value = [
            {'type': 'token', 'content': 'Answer'},
            {'type': 'done', 'reason': 'stop'},
        ]
        name = self.engine.current_session.session_name
        code = self.engine.current_session.session_id
        self.engine.chat('what is 2+2? and <b>html</b>')
        self.assertEqual(self.engine.current_session.session_name, name)
        self.assertEqual(self.engine.current_session.session_id, code)

    def test_load_or_create_session_persists_and_reloads(self):
        self.engine.load_or_create_session('foo')
        self.assertEqual(self.engine.current_session.session_name, 'foo')
        self.engine.provider.chat.return_value = [
            {'type': 'token', 'content': 'Answer'},
            {'type': 'done', 'reason': 'stop'},
        ]
        self.engine.chat('q')
        self.assertEqual(self.engine.current_session.session_name, 'foo')
        self.assertTrue((self.engine.sessions.sessions_dir / 'foo.json').exists())
        self.engine.load_or_create_session('foo')
        self.assertEqual(self.engine.current_session.session_name, 'foo')
        self.assertEqual(len(self.engine.current_session.turns[0]['parts']), 2)

    def test_headless_confirm_policy(self):
        self.engine._init_tooling()
        self.engine._ui = HeadlessUI(auto='deny')
        out = self.engine._run_tool('run_command', {'command': 'echo hi'})
        self.assertEqual(out, '[cancelled] User declined the run_command call')
        self.engine._ui = HeadlessUI(auto='allow')
        self.assertEqual(self.engine._confirm_tool('run_command', {'command': 'echo hi'}), True)

    def test_bash_allow_denies_unlisted_command(self):
        self.engine.config.set('tool_permission', {
            'bash': 'allow', 'bash_allow': ['pytest', 'ruff']})
        self.engine._init_tooling()
        self.engine._ui = HeadlessUI(auto='allow')
        out = self.engine._run_tool('run_command', {'command': 'rm -rf /'})
        self.assertIn('disabled by tool policy', out)
        perms = self.engine.current_session.permissions
        self.assertEqual(perms[-1]['action'], 'deny')
        self.assertEqual(perms[-1]['decision'], 'denied')

    def test_bash_allow_allows_listed_command(self):
        self.engine.config.set('tool_permission', {
            'bash': 'allow', 'bash_allow': ['pytest', 'ruff']})
        self.engine._init_tooling()
        out = self.engine._run_tool('run_command', {'command': 'pytest -q'})
        self.assertIn('exit', out)

    def _register_probe(self, config_action: str = 'ask'):
        self.engine.config.set('tool_permission', {'bash': config_action})
        self.engine._init_tooling()
        params = {'type': 'object', 'properties': {
            'path': {'type': 'string'}, 'cmd': {'type': 'string'}}}
        self.engine._tool_registry.register(
            'probe', 'probe tool', params, permission='bash',
            path_arg='path', key_arg='cmd')(lambda **kw: 'ok')

    def test_permission_recorded_for_ask_granted(self):
        self._register_probe('ask')
        self.engine._ui = HeadlessUI(auto='allow')
        self.engine._run_tool('probe', {'cmd': 'echo hi'})
        perms = self.engine.current_session.permissions
        self.assertEqual(len(perms), 1)
        self.assertEqual(perms[0]['tool'], 'probe')
        self.assertEqual(perms[0]['action'], 'ask')
        self.assertEqual(perms[0]['decision'], 'granted')
        self.assertIn('timestamp', perms[0])

    def test_permission_recorded_for_ask_declined(self):
        self._register_probe('ask')
        self.engine._ui = HeadlessUI(auto='deny')
        out = self.engine._run_tool('probe', {'cmd': 'echo hi'})
        self.assertEqual(out, '[cancelled] User declined the probe call')
        perms = self.engine.current_session.permissions
        self.assertEqual(len(perms), 1)
        self.assertEqual(perms[0]['action'], 'ask')
        self.assertEqual(perms[0]['decision'], 'declined')

    def test_permission_recorded_for_deny(self):
        self._register_probe('deny')
        out = self.engine._run_tool('probe', {'cmd': 'echo hi'})
        self.assertIn('disabled by tool policy', out)
        perms = self.engine.current_session.permissions
        self.assertEqual(len(perms), 1)
        self.assertEqual(perms[0]['action'], 'deny')
        self.assertEqual(perms[0]['decision'], 'denied')

    def test_permission_recorded_for_allow(self):
        self._register_probe('allow')
        self.engine._run_tool('probe', {'cmd': 'echo hi'})
        perms = self.engine.current_session.permissions
        self.assertEqual(len(perms), 1)
        self.assertEqual(perms[0]['action'], 'allow')
        self.assertEqual(perms[0]['decision'], 'granted')

    def test_permission_with_path_recorded(self):
        self._register_probe('ask')
        self.engine._ui = HeadlessUI(auto='allow')
        self.engine._run_tool('probe', {'path': '/definitely/not/here.txt'})
        perms = self.engine.current_session.permissions
        self.assertEqual(perms[0]['path'], '/definitely/not/here.txt')
        self.assertEqual(perms[0]['decision'], 'granted')

    def test_show_tool_status_renders_params_when_enabled(self):
        ui = _CaptureUI()
        self.engine._init_tooling()
        self.engine._ui = ui
        self.engine._show_tool_status(
            'run_command', {'command': 'ls', 'cwd': '/workspace', 'timeout': 10000})
        self.assertEqual(ui.labels, ['$ Run ls [cwd=/workspace, timeout=10000]'])

    def test_show_tool_status_omits_params_when_disabled(self):
        ui = _CaptureUI()
        self.engine._init_tooling()
        self.engine._ui = ui
        self.engine.config.set('glyph_params', False)
        self.engine._show_tool_status('run_command', {'command': 'ls', 'cwd': '/workspace'})
        self.assertEqual(ui.labels, ['$ Run ls'])

    def test_confirm_label_includes_params(self):
        ui = _CaptureUI()
        self.engine._init_tooling()
        self.engine._ui = ui
        self.engine._confirm_tool('run_command', {'command': 'ls', 'cwd': '/x'})
        self.assertEqual(ui.labels, ['confirm: run_command ls [cwd=/x]'])

    def test_run_tool_error_renders_error_line(self):
        ui = _CaptureUI()
        self.engine._init_tooling()
        self.engine._ui = ui
        out = self.engine._run_tool('read_file', {'path': '/definitely/not/here.txt'})
        self.assertIn('Error: file not found', out)
        self.assertEqual(ui.labels, [
            'confirm: read_file /definitely/not/here.txt',
            '← Read /definitely/not/here.txt',
            '! Error: file not found: /definitely/not/here.txt',
        ])

    def test_run_tool_error_suppressed_when_hidden(self):
        ui = _CaptureUI()
        self.engine._init_tooling()
        self.engine._ui = ui
        self.engine.config.set('show_errors', False)
        self.engine._run_tool('read_file', {'path': '/definitely/not/here.txt'})
        self.assertEqual(ui.labels, [
            'confirm: read_file /definitely/not/here.txt',
            '← Read /definitely/not/here.txt',
        ])

    def test_run_tool_success_no_error_line(self):
        ui = _CaptureUI()
        self.engine._init_tooling()
        self.engine._ui = ui
        self.engine._run_tool('run_command', {'command': 'echo hi'})
        self.assertEqual(ui.labels, ['confirm: run_command echo hi', '$ Run echo hi'])
        self.assertFalse(any(l.startswith('! ') for l in ui.labels))

    def test_run_tool_note_renders_soft_result(self):
        ui = _CaptureUI()
        self.engine._init_tooling()
        self.engine._ui = ui
        empty = Path(self.engine._tmp.name) / 'empty.txt'
        empty.write_text('')
        out = self.engine._run_tool('read_file', {'path': str(empty)})
        self.assertIn('(empty file)', out)
        self.assertEqual(ui.labels, [
            f'← Read {empty}',
            '[(empty file)]',
        ])

    def test_run_tool_note_suppressed_when_hidden(self):
        ui = _CaptureUI()
        self.engine._init_tooling()
        self.engine._ui = ui
        self.engine.config.set('show_notes', False)
        empty = Path(self.engine._tmp.name) / 'empty.txt'
        empty.write_text('')
        self.engine._run_tool('read_file', {'path': str(empty)})
        self.assertEqual(ui.labels, [f'← Read {empty}'])

    def test_run_tool_no_note_for_normal_result(self):
        ui = _CaptureUI()
        self.engine._init_tooling()
        self.engine._ui = ui
        (Path(self.engine._tmp.name) / 'found.txt').write_text('hi')
        self.engine._run_tool('glob', {'pattern': '*.txt', 'path': self.engine._tmp.name})
        self.assertFalse(any(l.startswith('[') for l in ui.labels))

    def test_denied_ask_tool_feeds_cancelled_result(self):
        self.engine.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': [{
                'id': 'c1', 'type': 'function',
                'function': {'name': 'run_command', 'arguments': '{"command": "echo hi"}'},
            }]}],
            [{'type': 'token', 'content': 'Final answer'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        result = self.engine.chat('q')
        tool_parts = [p for t in self.engine.current_session.turns
                      for p in t.get('parts') or [] if p['type'] == 'tool']
        self.assertEqual(len(tool_parts), 1)
        self.assertTrue(tool_parts[0]['output'].startswith('[cancelled]'))
        self.assertEqual(result.content, 'Final answer')
        self.assertEqual(result.tool_calls, [{'name': 'run_command', 'arguments': {'command': 'echo hi'}}])

    def test_turn_result_to_dict_json_serializable(self):
        self.engine.provider.chat.return_value = [
            {'type': 'token', 'content': 'Hello'},
            {'type': 'done', 'reason': 'stop', 'usage': {'prompt_tokens': 10}},
        ]
        result = self.engine.chat('q')
        d = result.to_dict()
        self.assertEqual(d['content'], 'Hello')
        self.assertEqual(d['usage'], {'prompt_tokens': 10})
        self.assertIn('session', d)
        self.assertIn('status', d)
        json.dumps(d)


class _RecordUI(NullUI):
    def __init__(self):
        self.calls = []

    def thinking(self, text):
        self.calls.append(('thinking', text))

    def thinking_begin(self):
        self.calls.append(('begin',))

    def thinking_end(self, duration):
        self.calls.append(('end', duration))


class TestEngineCheckConnection(unittest.TestCase):

    def setUp(self):
        self.engine = make_engine()

    def tearDown(self):
        self.engine._tmp.cleanup()

    def _factory(self, models, error=None):
        captured = {}

        def _f(**kwargs):
            captured.update(kwargs)
            p = MagicMock()
            p._fetch_models.return_value = (list(models), error)
            return p
        _f.DEFAULT_BASE_URL = 'https://test.api.com'
        _f.DEFAULT_MODEL = 'test-model'
        _f.captured = captured
        return _f

    def test_check_connection_resolves_and_probes(self):
        factory = self._factory(['m1', 'm2'])
        with patch('polyglav.providers.PROVIDERS', {'ollama': factory}):
            ok, msg, models = self.engine.check_connection()
        self.assertTrue(ok)
        self.assertIn('2 models available', msg)
        self.assertEqual(models, ['m1', 'm2'])
        self.assertEqual(factory.captured['base_url'], 'https://test.api.com')
        self.assertEqual(factory.captured['model'], 'test-model')
        self.assertEqual(factory.captured['api_key'], '')

    def test_check_connection_model_mismatch_note(self):
        factory = self._factory(['a', 'b'])
        with patch('polyglav.providers.PROVIDERS', {'ollama': factory}):
            ok, msg, models = self.engine.check_connection(model='zzz')
        self.assertTrue(ok)
        self.assertIn('"zzz" not in the model list', msg)
        self.assertEqual(models, ['a', 'b'])

    def test_check_connection_overrides_win(self):
        factory = self._factory([], error='HTTP 401: bad')
        with patch('polyglav.providers.PROVIDERS', {'ollama': factory}):
            ok, msg, models = self.engine.check_connection(
                base_url='https://other.example', api_key='sk-new', model='m2')
        self.assertFalse(ok)
        self.assertEqual(msg, 'HTTP 401: bad')
        self.assertEqual(models, [])
        self.assertEqual(factory.captured['base_url'], 'https://other.example')
        self.assertEqual(factory.captured['api_key'], 'sk-new')
        self.assertEqual(factory.captured['model'], 'm2')

    def test_check_connection_unknown_factory(self):
        with patch('polyglav.providers.PROVIDERS', {}):
            ok, msg, models = self.engine.check_connection(
                provider='nope', base_url='http://localhost:11434')
        self.assertFalse(ok)
        self.assertIn('No provider registered', msg)
        self.assertEqual(models, [])

    def test_check_connection_does_not_mutate_state(self):
        before = self.engine.provider
        factory = self._factory(['ok-model'])
        with patch('polyglav.providers.PROVIDERS', {'ollama': factory}):
            self.engine.check_connection(base_url='https://other.example')
        self.assertIs(self.engine.provider, before)
        self.assertEqual(self.engine.config.get('base_url'), 'https://test.api.com')

    def test_check_connection_detects_from_base_url(self):
        factory = self._factory(['g1'])
        factory.HOST_PATTERNS = ('groq.com',)
        with patch('polyglav.providers.PROVIDERS', {'groq': factory}):
            ok, msg, _ = self.engine.check_connection(
                provider='nope', base_url='https://api.groq.com/openai/v1')
        self.assertTrue(ok)
        self.assertEqual(factory.captured['base_url'], 'https://api.groq.com/openai/v1')

    def test_list_models_returns_models(self):
        factory = self._factory(['m1', 'm2'])
        with patch('polyglav.providers.PROVIDERS', {'ollama': factory}):
            models, error = self.engine.list_models()
        self.assertIsNone(error)
        self.assertEqual(models, ['m1', 'm2'])

    def test_list_models_returns_error(self):
        factory = self._factory([], error='HTTP 403: forbidden')
        with patch('polyglav.providers.PROVIDERS', {'ollama': factory}):
            models, error = self.engine.list_models()
        self.assertEqual(models, [])
        self.assertEqual(error, 'HTTP 403: forbidden')

    def test_list_models_unknown_factory(self):
        with patch('polyglav.providers.PROVIDERS', {}):
            models, error = self.engine.list_models(
                provider='nope', base_url='http://localhost:11434')
        self.assertEqual(models, [])
        self.assertIn('No provider registered', error)

    def test_list_models_respects_overrides(self):
        factory = self._factory(['x'])
        with patch('polyglav.providers.PROVIDERS', {'ollama': factory}):
            self.engine.list_models(base_url='https://other.example')
        self.assertEqual(factory.captured['base_url'], 'https://other.example')


class TestEngineSinks(unittest.TestCase):

    def test_usage_counts_extraction(self):
        engine = make_engine()
        try:
            counts = engine._usage_counts({
                'prompt_tokens': 12, 'completion_tokens': 8,
                'completion_tokens_details': {'reasoning_tokens': 5},
            })
            self.assertEqual(counts['in'], 12)
            self.assertEqual(counts['out'], 8)
            self.assertEqual(counts['thinking'], 5)
            self.assertEqual(counts['context'], 12)
        finally:
            engine._tmp.cleanup()

    def test_usage_counts_fallback_reasoning_and_empty(self):
        engine = make_engine()
        try:
            counts = engine._usage_counts({
                'prompt_tokens': 3, 'reasoning_tokens': 4})
            self.assertEqual(counts['thinking'], 4)
            counts = engine._usage_counts(None)
            self.assertNotIn('in', counts)
            self.assertNotIn('out', counts)
            self.assertNotIn('thinking', counts)
            self.assertIn('context', counts)
        finally:
            engine._tmp.cleanup()

    def test_null_ui_confirm_denies(self):
        from polyglav.ui import NullUI
        self.assertEqual(NullUI().confirm('x', 'x'), False)

    def test_headless_ui_auto(self):
        self.assertEqual(HeadlessUI(auto='allow').confirm('x', 'x'), True)
        self.assertEqual(HeadlessUI(auto='deny').confirm('x', 'x'), False)

    def test_thinking_window_begin_and_end(self):
        engine = make_engine()
        try:
            engine._ui = _RecordUI()
            engine.provider.chat.return_value = [
                {'type': 'thinking', 'content': 'reasoning'},
                {'type': 'token', 'content': 'Answer'},
                {'type': 'done', 'reason': 'stop'},
            ]
            engine.chat('q')
            kinds = [c[0] for c in engine._ui.calls]
            self.assertEqual(kinds, ['begin', 'thinking', 'end'])
            self.assertEqual(engine._ui.calls[1], ('thinking', 'reasoning'))
            self.assertEqual(engine._ui.calls[2][0], 'end')
            self.assertGreaterEqual(engine._ui.calls[2][1], 0)
        finally:
            engine._tmp.cleanup()

    def test_thinking_window_skipped_without_thinking(self):
        engine = make_engine()
        try:
            engine._ui = _RecordUI()
            engine.provider.chat.return_value = [
                {'type': 'token', 'content': 'Answer'},
                {'type': 'done', 'reason': 'stop'},
            ]
            engine.chat('q')
            self.assertEqual(engine._ui.calls, [])
        finally:
            engine._tmp.cleanup()


class TestEngineModes(unittest.TestCase):

    def setUp(self):
        self.engine = make_engine()
        self.engine.provider.chat.return_value = [
            {'type': 'token', 'content': 'Answer'},
            {'type': 'done', 'reason': 'stop'},
        ]

    def tearDown(self):
        self.engine._tmp.cleanup()

    def test_plan_mode_filters_write_and_exec_from_schema(self):
        self.engine.config.set('mode', 'plan')
        schema = self.engine._init_tooling()
        names = [s['function']['name'] for s in schema]
        self.assertNotIn('file_write', names)
        self.assertNotIn('run_command', names)
        self.assertIn('file_read', names)
        self.assertIn('web_search', names)

    def test_build_mode_schema_unfiltered(self):
        schema = self.engine._init_tooling()
        names = [s['function']['name'] for s in schema]
        self.assertIn('file_write', names)
        self.assertIn('run_command', names)

    def test_schema_advertises_only_canonical_names(self):
        schema = self.engine._init_tooling()
        names = [s['function']['name'] for s in schema]
        for expected in ('delegate', 'ask', 'run_command', 'file_read', 'list_dir',
                         'file_write', 'glob', 'grep', 'file_edit', 'git',
                         'git_commit', 'code_test', 'code_lint', 'code_format',
                         'mcp_connect', 'mcp_list', 'mcp_disconnect',
                         'web_search', 'web_fetch'):
            self.assertIn(expected, names)
        for alias in ('bash', 'exec', 'read', 'view', 'ls', 'find', 'search',
                      'web', 'open', 'fetch_page', 'read_file', 'write_file',
                      'edit', 'commit'):
            self.assertNotIn(alias, names)

    def test_plan_mode_instruction_sent_to_provider(self):
        self.engine.config.set('mode', 'plan')
        self.engine.chat('q')
        msgs = self.engine.provider.chat.call_args.args[0]
        self.assertEqual(msgs[0]['role'], 'system')
        self.assertIn('plan mode', msgs[0]['content'])
        self.assertIn('read-only', msgs[0]['content'])

    def test_project_instructions_injected_as_system_message(self):
        worktree = self.engine.config.local_path.parent.parent
        (worktree / 'AGENTS.md').write_text('# Polyglav conventions\n\nTest before commit.\n')
        self.engine.chat('q')
        msgs = self.engine.provider.chat.call_args.args[0]
        system = [m for m in msgs if m['role'] == 'system']
        self.assertTrue(any('Project instructions (AGENTS.md)' in m['content']
                            for m in system))
        self.assertTrue(any('Test before commit.' in m['content'] for m in system))

    def test_project_instructions_absent_skipped(self):
        worktree = self.engine.config.local_path.parent.parent
        agents = worktree / 'AGENTS.md'
        if agents.exists():
            agents.rename(agents.with_suffix('.md.bak'))
        try:
            self.engine.chat('q')
            msgs = self.engine.provider.chat.call_args.args[0]
            for m in msgs:
                self.assertNotIn('Project instructions', m.get('content', ''))
        finally:
            bak = worktree / 'AGENTS.md.bak'
            if bak.exists():
                bak.rename(agents)

    def test_project_instructions_disabled_when_unset(self):
        self.engine.config.set('project_instructions', '')
        worktree = self.engine.config.local_path.parent.parent
        (worktree / 'AGENTS.md').write_text('# Should be ignored\n')
        self.engine.chat('q')
        msgs = self.engine.provider.chat.call_args.args[0]
        for m in msgs:
            self.assertNotIn('Should be ignored', m.get('content', ''))

    def test_system_prompt_injected_for_headless(self):
        self.engine.config.set('system_prompt', 'You are a compliance bot.')
        self.engine.chat('q')
        msgs = self.engine.provider.chat.call_args.args[0]
        self.assertEqual(msgs[0]['role'], 'system')
        self.assertIn('compliance bot', msgs[0]['content'])

    def test_mode_recorded_on_assistant_message(self):
        self.engine.config.set('mode', 'plan')
        self.engine.chat('q')
        self.assertEqual(self.engine.current_session.turns[0]['mode'], 'plan')

    def test_mode_recorded_on_tool_call_message(self):
        self.engine.config.set('mode', 'plan')
        self.engine.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': [{
                'id': 'c1', 'type': 'function',
                'function': {'name': 'grep', 'arguments': '{"pattern": "x", "glob": "*.py"}'},
            }]}],
            [{'type': 'token', 'content': 'Final'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self.engine.chat('q')
        self.assertEqual(self.engine.current_session.turns[0]['mode'], 'plan')

    def test_plan_mode_run_tool_refuses_write(self):
        self.engine.config.set('mode', 'plan')
        self.engine._init_tooling()
        out = self.engine._run_tool('write_file', {'path': 'x.txt', 'content': 'x'})
        self.assertIn('disabled by tool policy', out)

    def test_unknown_mode_falls_back_to_build(self):
        self.engine.config.set('mode', 'nosuch')
        schema = self.engine._init_tooling()
        names = [s['function']['name'] for s in schema]
        self.assertIn('file_write', names)


class TestModelRefUnfold(unittest.TestCase):

    def setUp(self):
        self.engine = make_engine()
        self.engine.models.put('opencode-go', 'deepseek-v4-flash')
        self.engine.providers.put('opencode-go',
                                  'https://opencode.ai/zen/go/v1', 'key')

    def tearDown(self):
        self.engine._tmp.cleanup()

    def _write_type(self, name, model):
        types_dir = self.engine.config.local_path.parent / 'roles.json'
        types_dir.write_text(json.dumps(
            {name: {'system_prompt': 'You are a worker.', 'model': model}}))

    def test_reinit_provider_unfolds_ref(self):
        self.engine.config.apply('model', 'opencode-go/deepseek-v4-flash')
        self.engine._reinit_provider()
        self.assertEqual(self.engine.config.get('provider'), 'opencode-go')
        self.assertEqual(self.engine.config.get('base_url'),
                         'https://opencode.ai/zen/go/v1')
        self.assertEqual(self.engine.config.get('model'), 'deepseek-v4-flash')
        self.assertEqual(self.engine.provider.base_url,
                         'https://opencode.ai/zen/go/v1')
        self.assertEqual(self.engine.provider.model, 'deepseek-v4-flash')

    def test_unapproved_ref_denied_headless(self):
        self.engine.models.remove('opencode-go', 'deepseek-v4-flash')
        self.engine.config.apply('model', 'opencode-go/deepseek-v4-flash')
        self.engine._reinit_provider()
        self.assertIsNotNone(self.engine._provider_error)
        self.assertIn('not approved', self.engine._provider_error)

    def test_approve_models_grant_records_model(self):
        self.engine.models.remove('opencode-go', 'deepseek-v4-flash')
        self.engine.approve_models = True
        self.engine.config.apply('model', 'opencode-go/deepseek-v4-flash')
        self.engine._reinit_provider()
        self.assertIsNone(self.engine._provider_error)
        self.assertIsNotNone(
            self.engine.models.find('opencode-go', 'deepseek-v4-flash'))

    def test_chat_short_circuits_on_provider_error(self):
        self.engine.models.remove('opencode-go', 'deepseek-v4-flash')
        self.engine.config.apply('model', 'opencode-go/deepseek-v4-flash')
        self.engine._reinit_provider()
        result = self.engine.chat('hi')
        self.assertEqual(result.status, 'error')
        self.assertTrue(result.errors)

    def test_bare_model_unaffected(self):
        self.engine.config.apply('model', 'test-model')
        self.engine._reinit_provider()
        self.assertEqual(self.engine.config.get('provider'), 'ollama')
        self.assertEqual(self.engine.provider.model, 'test-model')

    def test_run_subagent_unapproved_type_model_raises(self):
        self._write_type('coder', 'opencode-go/deepseek-v4-flash')
        self.engine.models.remove('opencode-go', 'deepseek-v4-flash')
        with self.assertRaises(ValueError):
            self.engine.run_subagent('coder', 'write code')

    def test_run_subagent_approved_type_model_runs(self):
        self._write_type('coder', 'opencode-go/deepseek-v4-flash')
        sub = MagicMock()
        sub.chat.return_value = MagicMock(status='ok', content='done',
                                          session='sub_1')
        with patch.object(self.engine, '_new_sub_engine', return_value=sub):
            result = self.engine.run_subagent('coder', 'write code')
            self.engine._new_sub_engine.assert_called_once()
        self.assertEqual(result.content, 'done')

    def test_new_sub_engine_unfolds_type_model(self):
        self._write_type('coder', 'opencode-go/deepseek-v4-flash')
        sub = self.engine._new_sub_engine('coder')
        self.assertEqual(sub.config.get('provider'), 'opencode-go')
        self.assertEqual(sub.config.get('base_url'),
                         'https://opencode.ai/zen/go/v1')
        self.assertEqual(sub.config.get('model'), 'deepseek-v4-flash')

    def test_run_team_precheck_denies_unapproved_model(self):
        from polyglav.teams import Team, TeamStage
        self._write_type('coder', 'opencode-go/deepseek-v4-flash')
        self.engine.models.remove('opencode-go', 'deepseek-v4-flash')
        team = Team(name='t', stages=[TeamStage(role='coder')])
        result = self.engine.run_team(team, 'task')
        self.assertEqual(result.status, 'error')
        self.assertIn('unapproved model',
                      result.errors[0]['message'])


if __name__ == '__main__':
    unittest.main()
