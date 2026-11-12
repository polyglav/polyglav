import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "polyglav_core_serve",
    Path(__file__).resolve().parents[1] / "src" / "plugin.py")
_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_server)
HeadlessServer = _server.HeadlessServer
ChatHandler = _server.ChatHandler
from tests.test_engine import make_engine


class TestServer(unittest.TestCase):

    def setUp(self):
        self.engine = make_engine()
        self.engine.provider.chat.return_value = [
            {'type': 'token', 'content': 'server answer'},
            {'type': 'done', 'reason': 'stop'},
        ]
        self.server = HeadlessServer(('127.0.0.1', 0), ChatHandler, engine=self.engine)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.engine._tmp.cleanup()

    def _post(self, path, body):
        req = Request(f'http://127.0.0.1:{self.port}{path}',
                      data=json.dumps(body).encode('utf-8'),
                      headers={'Content-Type': 'application/json'}, method='POST')
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read())

    def test_chat(self):
        status, data = self._post('/chat', {'prompt': 'hello'})
        self.assertEqual(status, 200)
        self.assertEqual(data['content'], 'server answer')
        self.assertEqual(data['status'], 'ok')

    def test_chat_with_session(self):
        status, data = self._post('/chat', {'prompt': 'hello', 'session': 'api'})
        self.assertEqual(status, 200)
        self.assertEqual(data['session'], 'api')
        self.assertEqual(data['status'], 'ok')

    def test_health(self):
        with urlopen(f'http://127.0.0.1:{self.port}/health') as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(json.loads(resp.read()), {'status': 'ok'})

    def test_version(self):
        from polyglav import get_version
        with urlopen(f'http://127.0.0.1:{self.port}/version') as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(json.loads(resp.read()), {'version': get_version()})

    def test_sessions_list(self):
        self._post('/chat', {'prompt': 'hello', 'session': 'api'})
        with urlopen(f'http://127.0.0.1:{self.port}/sessions') as resp:
            data = json.loads(resp.read())
        self.assertIn('api', data['sessions'])

    def test_chat_missing_prompt(self):
        with self.assertRaises(HTTPError) as ctx:
            self._post('/chat', {})
        self.assertEqual(ctx.exception.code, 400)

    def test_cancel_idle(self):
        status, data = self._post('/cancel', {})
        self.assertEqual(status, 200)
        self.assertEqual(data['status'], 'idle')

    def test_unknown_route(self):
        with self.assertRaises(HTTPError) as ctx:
            self._post('/nope', {'prompt': 'x'})
        self.assertEqual(ctx.exception.code, 404)


class TestServerAuth(unittest.TestCase):

    def setUp(self):
        self.engine = make_engine()
        self.engine.provider.chat.return_value = [
            {'type': 'token', 'content': 'server answer'},
            {'type': 'done', 'reason': 'stop'},
        ]
        self.server = HeadlessServer(('127.0.0.1', 0), ChatHandler,
                                     engine=self.engine, token='s3cret')
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.engine._tmp.cleanup()

    def _post(self, path, body, token=''):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        req = Request(f'http://127.0.0.1:{self.port}{path}',
                      data=json.dumps(body).encode('utf-8'),
                      headers=headers, method='POST')
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read())

    def _get(self, path, token=''):
        headers = {'Authorization': f'Bearer {token}'} if token else {}
        req = Request(f'http://127.0.0.1:{self.port}{path}', headers=headers)
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read())

    def test_chat_requires_token(self):
        with self.assertRaises(HTTPError) as ctx:
            self._post('/chat', {'prompt': 'hello'})
        self.assertEqual(ctx.exception.code, 401)

    def test_chat_with_token(self):
        status, data = self._post('/chat', {'prompt': 'hello'}, token='s3cret')
        self.assertEqual(status, 200)
        self.assertEqual(data['content'], 'server answer')

    def test_chat_with_wrong_token(self):
        with self.assertRaises(HTTPError) as ctx:
            self._post('/chat', {'prompt': 'hello'}, token='nope')
        self.assertEqual(ctx.exception.code, 401)

    def test_chat_with_non_bearer_scheme(self):
        req = Request(f'http://127.0.0.1:{self.port}/chat',
                      data=json.dumps({'prompt': 'hello'}).encode('utf-8'),
                      headers={'Content-Type': 'application/json',
                               'Authorization': 'Token s3cret'}, method='POST')
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)
        self.assertEqual(ctx.exception.code, 401)

    def test_cancel_requires_token(self):
        with self.assertRaises(HTTPError) as ctx:
            self._post('/cancel', {})
        self.assertEqual(ctx.exception.code, 401)

    def test_sessions_requires_token(self):
        with self.assertRaises(HTTPError) as ctx:
            self._get('/sessions')
        self.assertEqual(ctx.exception.code, 401)

    def test_sessions_with_token(self):
        status, data = self._get('/sessions', token='s3cret')
        self.assertEqual(status, 200)
        self.assertIn('sessions', data)

    def test_health_stays_open(self):
        status, data = self._get('/health')
        self.assertEqual(status, 200)
        self.assertEqual(data, {'status': 'ok'})

    def test_version_stays_open(self):
        status, data = self._get('/version')
        self.assertEqual(status, 200)
        self.assertIn('version', data)


class TestServerBindPolicy(unittest.TestCase):

    def _args(self, host, token=None, allow=False):
        class Args:
            pass
        args = Args()
        args.host = host
        args.port = 0
        args.path = None
        args.mode = None
        if token is not None:
            args.token = token
        if allow:
            args.allow_unauthenticated = True
        return args

    def test_non_loopback_without_token_refuses(self):
        args = self._args('0.0.0.0')
        self.assertEqual(_server._run(args), 2)

    def test_loopback_without_token_is_allowed(self):
        args = self._args('127.0.0.1')
        self.assertFalse(_server._allow_unauthenticated(args, _FakeConfig()))
        self.assertEqual(_server._resolve_token(args, _FakeConfig()), '')

    def test_resolve_token_from_environment(self):
        import os
        from unittest.mock import patch
        args = self._args('127.0.0.1')
        with patch.dict(os.environ, {'POLYGLAV_TOKEN': 'env-token'}):
            self.assertEqual(_server._resolve_token(args, _FakeConfig()), 'env-token')

    def test_resolve_token_from_config(self):
        args = self._args('127.0.0.1')
        config = _FakeConfig({'serve.token': 'cfg-token'})
        self.assertEqual(_server._resolve_token(args, config), 'cfg-token')

    def test_allow_unauthenticated_flag(self):
        args = self._args('0.0.0.0', allow=True)
        self.assertTrue(_server._allow_unauthenticated(args, _FakeConfig()))

    def test_allow_unauthenticated_config(self):
        args = self._args('0.0.0.0')
        config = _FakeConfig({'serve.allow_unauthenticated': True})
        self.assertTrue(_server._allow_unauthenticated(args, config))


class _FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


if __name__ == '__main__':
    unittest.main()
