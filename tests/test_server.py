import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from polyglav.server import HeadlessServer, ChatHandler
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

    def test_unknown_route(self):
        with self.assertRaises(HTTPError) as ctx:
            self._post('/nope', {'prompt': 'x'})
        self.assertEqual(ctx.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
