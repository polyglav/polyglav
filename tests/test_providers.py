import unittest
import unittest.mock
import tempfile
import json
import io
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from polyglav.config import Config
from polyglav.chat import ChatLoop
from polyglav.plugins.manager import PluginManager
from polyglav.providers import (
    PROVIDERS, detect_provider, merged_providers, OpenAICompatibleProvider,
)

VENDOR_NAMES = ('ollama', 'openai', 'groq', 'anthropic',
                'opencode', 'opencode-go')
KNOWN_HOST_URLS = (
    'https://api.openai.com/v1',
    'https://api.groq.com/openai/v1',
    'https://api.anthropic.com/v1',
    'https://api.ollama.com',
    'https://opencode.ai/zen/v1',
    'https://opencode.ai/zen/go/v1',
)


def _bundled_providers():
    tmp = tempfile.TemporaryDirectory()
    pm = PluginManager(Config(path=tmp.name))
    pm.load()
    merged = dict(PROVIDERS)
    merged.update(pm.provider_classes())
    return merged


class TestProviderDefaults(unittest.TestCase):

    def test_explicit_values_override_defaults(self):
        p = OpenAICompatibleProvider(base_url='https://custom.example.com',
                                     model='my-model')
        self.assertEqual(p.base_url, 'https://custom.example.com')
        self.assertEqual(p.model, 'my-model')

    def test_openai_compatible_has_no_default_base_url(self):
        p = OpenAICompatibleProvider()
        self.assertEqual(p.base_url, '')


class TestProviderHeaders(unittest.TestCase):

    def test_no_auth_header_without_key(self):
        p = OpenAICompatibleProvider(api_key='')
        headers = p._headers()
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertNotIn('Authorization', headers)

    def test_bearer_auth_with_key(self):
        p = OpenAICompatibleProvider(api_key='sk-test')
        self.assertEqual(p._headers()['Authorization'], 'Bearer sk-test')

    def test_browser_user_agent(self):
        p = OpenAICompatibleProvider()
        self.assertEqual(p._headers()['User-Agent'],
                         ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'))

    def test_no_host_patterns_on_generic(self):
        self.assertEqual(OpenAICompatibleProvider.HOST_PATTERNS, ())


class TestDetectProvider(unittest.TestCase):

    def test_detects_known_hosts_from_merged_map(self):
        merged = _bundled_providers()
        cases = {
            'https://api.openai.com/v1': 'openai',
            'https://api.groq.com/openai/v1': 'groq',
            'https://api.anthropic.com/v1': 'anthropic',
            'https://api.ollama.com': 'ollama',
            'https://opencode.ai/zen/v1': 'opencode',
            'https://opencode.ai/zen/go/v1': 'opencode-go',
            'http://localhost:11434': 'openai-compatible',
        }
        for url, expected in cases.items():
            self.assertEqual(detect_provider(url, merged), expected, url)

    def test_longest_pattern_wins_for_shared_host(self):
        merged = _bundled_providers()
        self.assertEqual(detect_provider('https://opencode.ai/zen/go/v1', merged),
                         'opencode-go')
        self.assertEqual(detect_provider('https://opencode.ai/zen/v1/models', merged),
                         'opencode')

    def test_detects_empty(self):
        self.assertEqual(detect_provider(''), 'openai-compatible')
        self.assertEqual(detect_provider('', {}), 'openai-compatible')

    def test_honors_provider_map_param(self):
        class _Fake(OpenAICompatibleProvider):
            HOST_PATTERNS = ('fake.example',)
        providers = {'fake': _Fake, 'openai-compatible': OpenAICompatibleProvider}
        self.assertEqual(detect_provider('https://fake.example/v1', providers), 'fake')
        self.assertEqual(detect_provider('https://other.example/v1', providers),
                         'openai-compatible')


class TestProviderRegistry(unittest.TestCase):

    def test_core_registry_is_generic_fallback_only(self):
        self.assertEqual(set(PROVIDERS), {'openai-compatible'})

    def test_merged_includes_bundled_providers(self):
        merged = _bundled_providers()
        for name in VENDOR_NAMES:
            self.assertIn(name, merged)
            self.assertTrue(issubclass(merged[name], OpenAICompatibleProvider),
                            name)

    def test_detected_provider_is_registered(self):
        merged = _bundled_providers()
        for url in KNOWN_HOST_URLS:
            self.assertIn(detect_provider(url, merged), merged)

    def test_merged_providers_helper(self):
        merged = merged_providers()
        for name in VENDOR_NAMES:
            self.assertIn(name, merged)


class TestProviderSwitching(unittest.TestCase):

    def _make_chat(self, data):
        tmp = tempfile.TemporaryDirectory()
        config_dir = Path(tmp.name) / '.polyglav'
        config_dir.mkdir(parents=True)
        with open(config_dir / 'config.json', 'w') as f:
            json.dump(data, f)
        chat = ChatLoop.__new__(ChatLoop)
        chat.config = Config(path=tmp.name)
        chat.provider = None
        chat._tmp = tmp
        pm = PluginManager(chat.config)
        pm.load()
        chat._plugin_manager = pm
        return chat

    def test_switch_resets_default_base_url_and_model(self):
        chat = self._make_chat({
            'provider': 'ollama',
            'base_url': 'https://api.ollama.com',
            'model': 'llama3.2',
        })
        chat._reinit_provider()
        from polyglav.providers.base import OpenAICompatibleProvider
        factory = chat._plugin_manager.provider_classes()['ollama']
        self.assertEqual(type(chat.provider), factory)
        chat.config.set('provider', 'openai')
        chat._reinit_provider()
        openai_factory = chat._plugin_manager.provider_classes()['openai']
        self.assertEqual(type(chat.provider), openai_factory)
        self.assertEqual(chat.provider.base_url, 'https://api.openai.com/v1')
        self.assertEqual(chat.provider.model, 'gpt-4o-mini')
        self.assertEqual(chat.config.get('base_url'), 'https://api.openai.com/v1')
        chat._tmp.cleanup()

    def test_switch_keeps_custom_base_url_and_model(self):
        chat = self._make_chat({
            'provider': 'ollama',
            'base_url': 'https://proxy.example.com',
            'model': 'llama3.3',
        })
        chat._reinit_provider()
        chat.config.set('provider', 'anthropic')
        chat._reinit_provider()
        factory = chat._plugin_manager.provider_classes()['anthropic']
        self.assertEqual(type(chat.provider), factory)
        self.assertEqual(chat.provider.base_url, 'https://proxy.example.com')
        self.assertEqual(chat.provider.model, 'llama3.3')
        chat._tmp.cleanup()

    def test_unknown_provider_auto_detected(self):
        chat = self._make_chat({
            'provider': 'nope',
            'base_url': 'https://api.groq.com/openai/v1',
            'model': 'test',
        })
        chat._reinit_provider()
        factory = chat._plugin_manager.provider_classes()['groq']
        self.assertEqual(type(chat.provider), factory)
        self.assertEqual(chat.config.get('provider'), 'groq')
        chat._tmp.cleanup()


class _RedirectAPIHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_POST(self):
        if self.path == '/start':
            self.send_response(301)
            self.send_header('Location', '/v1/chat/completions')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if self.path == '/v1/chat/completions':
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            body = json.dumps({
                'choices': [{
                    'message': {'role': 'assistant', 'content': 'ok'},
                    'finish_reason': 'stop',
                }],
            }).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_GET(self):
        if self.path == '/v1/chat/completions':
            self.send_error(405, 'Method Not Allowed')
            return
        self.send_error(404)

    def log_message(self, *args):
        pass


class TestPostRedirect(unittest.TestCase):

    def test_nonstreaming_post_survives_301(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), _RedirectAPIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            p = OpenAICompatibleProvider(base_url=base, model='test-model')
            result = p.chat_nonstreaming([{'role': 'user', 'content': 'hi'}])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(result['role'], 'assistant')
        self.assertEqual(result['content'], 'ok')


class TestProviderEndpoints(unittest.TestCase):

    def test_custom_base_without_v1_appends_v1(self):
        p = OpenAICompatibleProvider(base_url='https://x.example')
        self.assertEqual(p._endpoint(), 'https://x.example/v1/chat/completions')

    def test_custom_base_with_v1_not_doubled(self):
        p = OpenAICompatibleProvider(base_url='https://x.example/v1')
        self.assertEqual(p._endpoint(), 'https://x.example/v1/chat/completions')

    def test_bundled_default_endpoints(self):
        merged = _bundled_providers()
        cases = {
            'ollama': 'https://api.ollama.com/v1/chat/completions',
            'openai': 'https://api.openai.com/v1/chat/completions',
            'groq': 'https://api.groq.com/openai/v1/chat/completions',
            'anthropic': 'https://api.anthropic.com/v1/chat/completions',
            'opencode': 'https://opencode.ai/zen/v1/chat/completions',
            'opencode-go': 'https://opencode.ai/zen/go/v1/chat/completions',
        }
        for name, expected in cases.items():
            self.assertEqual(merged[name]()._endpoint(), expected, name)

    def test_list_models_url_normalized(self):
        import urllib.request
        p = OpenAICompatibleProvider(base_url='https://api.openai.com/v1')
        captured = {}

        def _fake_urlopen(req, *args, **kwargs):
            captured['url'] = req.full_url
            raise Exception('stop')

        with unittest.mock.patch('urllib.request.urlopen', _fake_urlopen):
            p.list_models()
        self.assertEqual(captured.get('url'),
                         'https://api.openai.com/v1/models')


class TestCheckConnection(unittest.TestCase):

    def _provider(self, base_url, model=''):
        return OpenAICompatibleProvider(base_url=base_url, model=model)

    def _run_server(self, handler):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            return f'http://127.0.0.1:{server.server_port}', server
        except BaseException:
            server.shutdown()
            server.server_close()
            thread.join()
            raise

    def test_check_connection_success(self):
        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({'data': [{'id': 'm1'}, {'id': 'm2'}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        base, server = self._run_server(_H)
        try:
            ok, msg = self._provider(base).check_connection()
        finally:
            server.shutdown()
            server.server_close()
        self.assertTrue(ok)
        self.assertIn('2 models available', msg)

    def test_check_connection_no_models(self):
        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({'data': []}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        base, server = self._run_server(_H)
        try:
            ok, msg = self._provider(base).check_connection()
        finally:
            server.shutdown()
            server.server_close()
        self.assertTrue(ok)
        self.assertIn('no models listed', msg)

    def test_check_connection_notes_missing_model(self):
        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({'data': [{'id': 'm1'}, {'id': 'm2'}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        base, server = self._run_server(_H)
        try:
            ok, msg = self._provider(base, model='nope').check_connection()
        finally:
            server.shutdown()
            server.server_close()
        self.assertTrue(ok)
        self.assertIn('"nope" not in the model list', msg)

    def test_check_connection_http_error(self):
        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"error": {"message": "invalid api key"}}'
                self.send_response(401)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        base, server = self._run_server(_H)
        try:
            ok, msg = self._provider(base).check_connection()
        finally:
            server.shutdown()
            server.server_close()
        self.assertFalse(ok)
        self.assertIn('HTTP 401', msg)
        self.assertIn('invalid api key', msg)

    def test_check_connection_network_error(self):
        import urllib.error
        p = OpenAICompatibleProvider(base_url='http://192.0.2.1:9', model='m')

        def _raise(req, *args, **kwargs):
            raise urllib.error.URLError('connection refused')
        with unittest.mock.patch('urllib.request.urlopen', _raise):
            ok, msg = p.check_connection()
        self.assertFalse(ok)
        self.assertIn('Network error', msg)

    def test_list_models_still_returns_empty_on_error(self):
        import urllib.error

        def _raise(req, *args, **kwargs):
            raise urllib.error.URLError('boom')
        p = OpenAICompatibleProvider(base_url='http://192.0.2.1:9')
        with unittest.mock.patch('urllib.request.urlopen', _raise):
            self.assertEqual(p.list_models(), [])

    def test_list_models_silent_on_error(self):
        import urllib.error

        def _raise(req, *args, **kwargs):
            raise urllib.error.URLError('boom')
        p = OpenAICompatibleProvider(base_url='http://192.0.2.1:9')
        out = io.StringIO()
        with unittest.mock.patch('urllib.request.urlopen', _raise):
            with unittest.mock.patch('sys.stdout', new=out):
                p.list_models()
        self.assertEqual(out.getvalue(), '')


class TestReasoningPayload(unittest.TestCase):

    def _payload(self, provider, reasoning):
        p = provider(reasoning=reasoning)
        return p._payload([{'role': 'user', 'content': 'hi'}])

    def test_base_off_sends_nothing(self):
        payload = self._payload(OpenAICompatibleProvider, 'off')
        self.assertNotIn('reasoning_effort', payload)

    def test_base_auto_sends_nothing(self):
        payload = self._payload(OpenAICompatibleProvider, 'auto')
        self.assertNotIn('reasoning_effort', payload)

    def test_base_passes_effort_through(self):
        payload = self._payload(OpenAICompatibleProvider, 'high')
        self.assertEqual(payload['reasoning_effort'], 'high')


class TestReasoningEcho(unittest.TestCase):

    def _echo(self):
        class _Echo(OpenAICompatibleProvider):
            ECHO_REASONING = True
        return _Echo(model='m')

    def test_base_strips_thinking_without_reasoning_content(self):
        p = OpenAICompatibleProvider(model='m')
        payload = p._payload([
            {'role': 'assistant', 'content': 'hi', 'thinking': 'reason'},
        ])
        message = payload['messages'][0]
        self.assertNotIn('thinking', message)
        self.assertNotIn('reasoning_content', message)

    def test_echo_adds_reasoning_content_on_assistant(self):
        p = self._echo()
        payload = p._payload([
            {'role': 'assistant', 'content': 'hi', 'thinking': 'reason'},
        ])
        message = payload['messages'][0]
        self.assertEqual(message['reasoning_content'], 'reason')
        self.assertNotIn('thinking', message)

    def test_echo_adds_reasoning_content_on_tool_call_message(self):
        p = self._echo()
        payload = p._payload([
            {'role': 'assistant', 'content': None, 'thinking': 'reason',
             'tool_calls': [{'id': 'c1', 'type': 'function',
                             'function': {'name': 'read', 'arguments': '{}'}}]},
        ])
        message = payload['messages'][0]
        self.assertEqual(message['reasoning_content'], 'reason')
        self.assertNotIn('thinking', message)

    def test_echo_skips_assistant_without_thinking(self):
        p = self._echo()
        payload = p._payload([{'role': 'assistant', 'content': 'hi'}])
        self.assertNotIn('reasoning_content', payload['messages'][0])

    def test_echo_leaves_user_and_tool_messages(self):
        p = self._echo()
        payload = p._payload([
            {'role': 'user', 'content': 'hi', 'thinking': 'nope'},
            {'role': 'tool', 'content': 'out', 'thinking': 'nope'},
        ])
        for message in payload['messages']:
            self.assertNotIn('thinking', message)
            self.assertNotIn('reasoning_content', message)

    def test_prepare_messages_does_not_mutate_input(self):
        p = self._echo()
        original = {'role': 'assistant', 'content': 'hi', 'thinking': 'reason'}
        p._prepare_messages([original])
        self.assertEqual(original['thinking'], 'reason')
        self.assertNotIn('reasoning_content', original)


if __name__ == '__main__':
    unittest.main()