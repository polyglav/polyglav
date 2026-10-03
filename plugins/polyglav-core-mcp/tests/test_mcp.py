import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _load_plugin(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


import jsonrpc
import client as mcp_client
from client_stdio import StdioTransport, TransportError as StdioTransportError
from client_http import HttpTransport
import server as mcp_server
mcp_plugin = _load_plugin('polyglav_mcp_plugin', SRC_DIR / 'plugin.py')
from polyglav.tools.registry import ToolRegistry
from polyglav.tools.policy import ToolPolicy

LEGACY_SERVER = '''
import json, sys
def send(m):
    sys.stdout.write(json.dumps(m) + '\\n')
    sys.stdout.flush()
for line in sys.stdin:
    msg = json.loads(line)
    m = msg.get('method')
    if m == 'initialize':
        send({'jsonrpc':'2.0','id':msg['id'],'result':{'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'mini','version':'1.0'}}})
    elif m == 'tools/list':
        send({'jsonrpc':'2.0','id':msg['id'],'result':{'tools':[{'name':'echo','description':'echo text','inputSchema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text']}}]}})
    elif m == 'tools/call':
        send({'jsonrpc':'2.0','id':msg['id'],'result':{'content':[{'type':'text','text':'ECHO:'+msg['params']['arguments']['text']}]}})
'''

MODERN_SERVER = '''
import json, sys
def send(m):
    sys.stdout.write(json.dumps(m) + '\\n')
    sys.stdout.flush()
for line in sys.stdin:
    msg = json.loads(line)
    m = msg.get('method')
    if m == 'server/discover':
        send({'jsonrpc':'2.0','id':msg['id'],'result':{'resultType':'complete','supportedVersions':['2026-07-28'],'capabilities':{'tools':{}}}})
    elif m == 'tools/list':
        send({'jsonrpc':'2.0','id':msg['id'],'result':{'resultType':'complete','tools':[{'name':'add','description':'add ints','inputSchema':{'type':'object','properties':{'a':{'type':'integer'},'b':{'type':'integer'}},'required':['a','b']}}]}})
    elif m == 'tools/call':
        a = msg['params']['arguments']
        send({'jsonrpc':'2.0','id':msg['id'],'result':{'resultType':'complete','content':[{'type':'text','text':str(a['a']+a['b'])}]}})
'''

NOTIFY_SERVER = '''
import json, sys
def send(m):
    sys.stdout.write(json.dumps(m) + '\\n')
    sys.stdout.flush()
for line in sys.stdin:
    msg = json.loads(line)
    m = msg.get('method')
    if m == 'notify':
        send({'jsonrpc':'2.0','method':'notifications/message','params':{'level':'info','data':'hi'}})
        send({'jsonrpc':'2.0','id':msg['id'],'result':{'ok':True}})
    elif m == 'hang':
        pass
'''


class TestJsonRpc(unittest.TestCase):
    def test_message_builders(self):
        self.assertEqual(jsonrpc.make_request(1, 'ping'),
                         {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'})
        self.assertEqual(jsonrpc.make_notification('n', {'a': 1}),
                         {'jsonrpc': '2.0', 'method': 'n', 'params': {'a': 1}})
        self.assertIn('result', jsonrpc.make_response(1, {}))
        err = jsonrpc.make_error(1, jsonrpc.CODE_METHOD_NOT_FOUND, 'nope')
        self.assertEqual(err['error']['code'], -32601)

    def test_encode_line_framing(self):
        raw = jsonrpc.encode_message({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'})
        self.assertNotIn('\n', raw)
        self.assertEqual(jsonrpc.parse_line(raw), {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'})

    def test_modern_meta(self):
        meta = jsonrpc.modern_meta()
        self.assertEqual(meta[jsonrpc.META_VERSION], '2026-07-28')
        self.assertIn(jsonrpc.META_CLIENT_CAPS, meta)
        self.assertTrue(jsonrpc.is_modern_request(
            {'params': {'_meta': meta}}))
        self.assertFalse(jsonrpc.is_modern_request({'params': {}}))

    def test_header_value_encoding(self):
        self.assertEqual(jsonrpc.encode_header_value('us-west1'), 'us-west1')
        self.assertEqual(jsonrpc.encode_header_value('Good', ) if False else
                         jsonrpc.encode_header_value('Hello, 世界'), '=?base64?SGVsbG8sIOS4lueVjA==?=')
        self.assertEqual(jsonrpc.encode_header_value('=?base64?literal?='),
                         '=?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?=')

    def test_iter_sse(self):
        import io
        stream = io.BytesIO(b'event: message\ndata: {"a":1}\n\nevent: message\ndata: {"b":2}\n\n')
        events = list(jsonrpc.iter_sse(stream))
        self.assertEqual(events, [('message', '{"a":1}'), ('message', '{"b":2}')])


class TestStdioTransport(unittest.TestCase):
    def _server(self, script, **kw):
        return StdioTransport(sys.executable, ['-c', script], timeout=kw.get('timeout', 5))

    def test_request_response(self):
        t = self._server(MODERN_SERVER)
        t.start()
        try:
            result = t.request('server/discover')
            self.assertEqual(result['resultType'], 'complete')
        finally:
            t.close()

    def test_notifications_delivered(self):
        notifications = []
        t = StdioTransport(sys.executable, ['-c', NOTIFY_SERVER], timeout=5,
                           notify=notifications.append)
        t.start()
        try:
            result = t.request('notify')
            self.assertEqual(result, {'ok': True})
        finally:
            t.close()
        self.assertTrue(any('notifications/message' in n.get('method', '')
                            for n in notifications))

    def test_timeout_raises(self):
        t = StdioTransport(sys.executable, ['-c', NOTIFY_SERVER], timeout=0.3)
        t.start()
        try:
            with self.assertRaises(StdioTransportError):
                t.request('hang')
        finally:
            t.close()

    def test_error_response_raises(self):
        t = StdioTransport(sys.executable, ['-c', 'import sys\n'
                                            'import json\n'
                                            'for line in sys.stdin:\n'
                                            '    msg=json.loads(line)\n'
                                            '    sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":msg["id"],"error":{"code":-32601,"message":"no"}})+"\\n")\n'
                                            '    sys.stdout.flush()'], timeout=5)
        t.start()
        try:
            with self.assertRaises(jsonrpc.MCPError):
                t.request('server/discover')
        finally:
            t.close()


class TestClientNegotiation(unittest.TestCase):
    def _client(self, script, **kw):
        return mcp_client.MCPClient(
            {'name': kw.get('name', 'mini'), 'transport': 'stdio',
             'command': sys.executable, 'args': ['-c', script], 'timeout': 5})

    def test_legacy(self):
        c = self._client(LEGACY_SERVER)
        c.connect()
        self.assertEqual(c.mode, 'legacy')
        self.assertEqual(c.version, '2025-11-25')
        self.assertEqual([t['name'] for t in c.tools], ['echo'])
        self.assertEqual(mcp_client.result_text(c.tools_call('echo', {'text': 'x'})),
                         'ECHO:x')
        c.close()

    def test_modern(self):
        c = self._client(MODERN_SERVER, name='mini2')
        c.connect()
        self.assertEqual(c.mode, 'modern')
        self.assertEqual(c.version, '2026-07-28')
        self.assertEqual(mcp_client.result_text(c.tools_call('add', {'a': 2, 'b': 3})), '5')
        c.close()


class TestResultText(unittest.TestCase):
    def test_text_and_error(self):
        self.assertEqual(mcp_client.result_text({'content': [{'type': 'text', 'text': 'a'}]}), 'a')
        self.assertEqual(mcp_client.result_text(
            {'content': [{'type': 'text', 'text': 'boom'}], 'isError': True}), 'Error: boom')
        self.assertEqual(mcp_client.result_text({'content': [{'type': 'text', 'text': 'Error: e'}]}),
                         'Error: e')
        self.assertEqual(mcp_client.result_text({}), '(empty MCP tool result)')
        self.assertEqual(mcp_client.result_text(
            {'structuredContent': {'x': 1}, 'content': []}), '{"x": 1}')


class TestPluginRegistration(unittest.TestCase):
    def setUp(self):
        mcp_plugin.CONNECTIONS.clear()
        self.reg = ToolRegistry()

    def test_management_tools_registered(self):
        mcp_plugin.register_tools(self.reg)
        self.assertTrue({'mcp_connect', 'mcp_list', 'mcp_disconnect'} <= set(self.reg.names()))
        self.assertEqual(self.reg.permission_for('mcp_connect'), 'mcp')
        self.assertEqual(self.reg.permission_for('mcp_list'), 'read')
        self.assertEqual(self.reg.permission_for('mcp_disconnect'), 'mcp')

    def test_connected_tool_mapping_and_prefix(self):
        conn = mcp_client.MCPClient(
            {'name': 'github', 'prefix': 'github', 'transport': 'stdio',
             'command': sys.executable, 'args': ['-c', MODERN_SERVER]})
        conn.connect()
        conn.config = {'tool_max_result_chars': 1000}
        mcp_plugin.CONNECTIONS['github'] = conn
        mcp_plugin.register_tools(self.reg)
        self.assertIn('github.add', self.reg.names())
        self.assertEqual(self.reg.permission_for('github.add'), 'mcp')
        result = self.reg.execute('github.add', {'a': 4, 'b': 5})
        self.assertEqual(result, '9')
        self.assertEqual(self.reg.status_parts('github.add', {})[0], 'github.add')
        conn.close()
        mcp_plugin.CONNECTIONS.clear()

    def test_unknown_tool_error(self):
        mcp_plugin.register_tools(self.reg)
        self.assertTrue(self.reg.execute('nope', {}).startswith('Error:'))


class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self.engine = _FakeEngine()
        self.srv = mcp_server.MCPServer(self.engine)
        self.meta = jsonrpc.modern_meta()
        self.srv._mode = None

    def _call(self, msg):
        return self.srv.dispatch(msg)

    def test_legacy_initialize(self):
        resp = self._call({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                           'params': {'protocolVersion': '2025-11-25', 'capabilities': {}}})
        self.assertEqual(resp['result']['protocolVersion'], '2025-11-25')
        self.assertEqual(self.srv._mode, 'legacy')

    def test_legacy_tools_and_call(self):
        self._call({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
        listing = self._call({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
        names = [t['name'] for t in listing['result']['tools']]
        self.assertIn('greet', names)
        self.assertNotIn('secret', names)
        call = self._call({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                           'params': {'name': 'greet', 'arguments': {'name': 'Ada'}}})
        self.assertEqual(call['result']['content'][0]['text'], 'Hello, Ada!')

    def test_modern_discover(self):
        resp = self._call({'jsonrpc': '2.0', 'id': 1, 'method': 'server/discover',
                           'params': {'_meta': self.meta}})
        self.assertEqual(resp['result']['resultType'], 'complete')
        self.assertIn('2026-07-28', resp['result']['supportedVersions'])

    def test_modern_missing_capabilities_rejected(self):
        resp = self._call({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list',
                           'params': {'_meta': {'io.modelcontextprotocol/protocolVersion': '2026-07-28'}}})
        self.assertEqual(resp['error']['code'], jsonrpc.CODE_INVALID_PARAMS)

    def test_modern_unsupported_version(self):
        resp = self._call({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list',
                           'params': {'_meta': {'io.modelcontextprotocol/protocolVersion': '1900-01-01',
                                                'io.modelcontextprotocol/clientCapabilities': {}}}})
        self.assertEqual(resp['error']['code'], jsonrpc.CODE_UNSUPPORTED_VERSION)

    def test_policy_deny_and_ask(self):
        self.srv._mode = 'modern'
        denied = self._call({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                             'params': {'name': 'secret', 'arguments': {}, '_meta': self.meta}})
        self.assertTrue(denied['result']['isError'])
        allowed = self._call({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                              'params': {'name': 'run_command', 'arguments': {'cmd': 'ls'},
                                         '_meta': self.meta}})
        self.assertFalse(allowed['result']['isError'])

    def test_ask_denied_when_config_off(self):
        self.engine.config.overrides['mcp_server.allow_ask'] = False
        self.srv._mode = 'modern'
        denied = self._call({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                             'params': {'name': 'run_command', 'arguments': {'cmd': 'ls'},
                                        '_meta': self.meta}})
        self.assertTrue(denied['result']['isError'])

    def test_unknown_tool_is_protocol_error(self):
        resp = self._call({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                           'params': {'name': 'nope', 'arguments': {}, '_meta': self.meta}})
        self.assertEqual(resp['error']['code'], jsonrpc.CODE_INVALID_PARAMS)

    def test_resources(self):
        self.srv._mode = 'modern'
        listing = self._call({'jsonrpc': '2.0', 'id': 1, 'method': 'resources/list',
                              'params': {'_meta': self.meta}})
        uris = [r['uri'] for r in listing['result']['resources']]
        self.assertIn('polyglav://session/one', uris)
        read = self._call({'jsonrpc': '2.0', 'id': 2, 'method': 'resources/read',
                           'params': {'uri': 'polyglav://session/one', '_meta': self.meta}})
        self.assertIn('one', read['result']['contents'][0]['text'])
        missing = self._call({'jsonrpc': '2.0', 'id': 3, 'method': 'resources/read',
                              'params': {'uri': 'polyglav://session/nope', '_meta': self.meta}})
        self.assertEqual(missing['error']['code'], jsonrpc.CODE_INVALID_PARAMS)

    def test_unknown_method(self):
        resp = self._call({'jsonrpc': '2.0', 'id': 1, 'method': 'prompts/list',
                           'params': {'_meta': self.meta}})
        self.assertEqual(resp['error']['code'], jsonrpc.CODE_METHOD_NOT_FOUND)

    def test_notifications_no_response(self):
        self.assertIsNone(self._call({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))


class TestHttpTransport(unittest.TestCase):
    def test_modern_round_trip(self):
        engine = _FakeEngine()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                raw = self.rfile.read(length)
                code, headers, body = mcp_server.MCPServer(engine).handle_http(raw)
                self.send_response(code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{httpd.server_address[1]}/mcp'
            conn = mcp_client.MCPClient(
                {'name': 'httpmini', 'transport': 'http', 'url': url, 'timeout': 5})
            conn.connect()
            self.assertEqual(conn.mode, 'modern')
            self.assertEqual([t['name'] for t in conn.tools], ['greet', 'run_command'])
            self.assertEqual(mcp_client.result_text(conn.tools_call('greet', {'name': 'H'})),
                             'Hello, H!')
            conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()


class _FakeConfig:
    def __init__(self):
        self.overrides = {}

    def get(self, key, default=None):
        if key in self.overrides:
            return self.overrides[key]
        return {
            'tool_calling': True,
            'tool_permission': {'bash': 'ask', 'mcp': 'ask'},
            'mcp_server.allow_ask': True,
        }.get(key, default)


class _FakeEngine:
    def __init__(self):
        self.config = _FakeConfig()
        self.sessions = _FakeSessions()

    def _init_tooling(self):
        self._tool_registry = ToolRegistry()
        self._tool_registry.register(
            name='greet', description='greet someone',
            parameters={'type': 'object', 'properties': {'name': {'type': 'string'}},
                        'required': ['name']},
            category='tool', permission='web')(lambda name: f'Hello, {name}!')
        self._tool_registry.register(
            name='run_command', description='run',
            parameters={'type': 'object', 'properties': {'cmd': {'type': 'string'}},
                        'required': ['cmd']},
            category='exec', permission='bash')(lambda cmd: f'ran: {cmd}')

        def deny_handler(**kw):
            return 'should not run'
        self._tool_registry.register(
            name='secret', description='secret', permission='read',
            parameters={'type': 'object', 'properties': {}})(deny_handler)

        self._tool_policy = ToolPolicy(
            permissions={'bash': 'ask', 'mcp': 'ask'},
            deny=['secret'],
        )


class _FakeSessions:
    def list(self):
        return ['one', 'two']

    def read(self, name):
        if name == 'one':
            return _FakeSession()
        return None


class _FakeSession:
    name = 'one'

    def to_dict(self):
        return {'name': 'one', 'messages': []}


if __name__ == '__main__':
    unittest.main()
