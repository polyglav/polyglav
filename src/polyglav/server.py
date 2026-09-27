import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import get_version


class HeadlessServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, engine=None, mcp_service=None):
        super().__init__(address, handler)
        self.engine = engine
        self.mcp_service = mcp_service
        self.lock = threading.Lock()


class ChatHandler(BaseHTTPRequestHandler):
    def _send(self, code, payload: dict):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_raw(self, code, headers: dict, body: bytes):
        self.send_response(code)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _mcp_request(self):
        server = self.server
        service = server.mcp_service
        if service is None:
            self._send(404, {'error': 'not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length) if length else b''
        except (ValueError, OSError):
            self._send(400, {'error': 'invalid request'})
            return
        code, headers, body = service.handle_http(server.engine, raw)
        self._send_raw(code, headers, body)

    def do_POST(self):
        if self.path == '/mcp':
            self._mcp_request()
            return
        if self.path.startswith('/asks/'):
            self._answer_ask()
            return
        if self.path != '/chat':
            self._send(404, {'error': 'not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length) if length else b'{}'
            body = json.loads(raw.decode('utf-8') or '{}')
        except (ValueError, json.JSONDecodeError):
            self._send(400, {'error': 'invalid JSON body'})
            return
        prompt = body.get('prompt', '')
        if not isinstance(prompt, str) or not prompt.strip():
            self._send(400, {'error': 'missing "prompt"'})
            return
        session_name = body.get('session')
        server = self.server
        with server.lock:
            server.engine.load_or_create_session(session_name)
            result = server.engine.chat(prompt)
        self._send(200, result.to_dict())

    def do_GET(self):
        server = self.server
        if self.path == '/health':
            self._send(200, {'status': 'ok'})
        elif self.path == '/version':
            self._send(200, {'version': get_version()})
        elif self.path == '/sessions':
            with server.lock:
                names = server.engine.sessions.list()
            self._send(200, {'sessions': names})
        elif self.path == '/asks':
            asks = [a.to_dict() for a in server.engine.asks.list()]
            self._send(200, {'asks': asks})
        else:
            self._send(404, {'error': 'not found'})

    def _answer_ask(self):
        server = self.server
        rest = self.path[len('/asks/'):]
        if not rest.endswith('/answer'):
            self._send(404, {'error': 'not found'})
            return
        aid = rest[:-len('/answer')]
        try:
            ask_id = int(aid)
        except ValueError:
            self._send(404, {'error': 'not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length) if length else b'{}'
            body = json.loads(raw.decode('utf-8') or '{}')
        except (ValueError, json.JSONDecodeError):
            self._send(400, {'error': 'invalid JSON body'})
            return
        answer = body.get('answer')
        if not isinstance(answer, str) or not answer.strip():
            self._send(400, {'error': 'missing "answer"'})
            return
        from .asks import inject_answer
        store = server.engine.asks
        asked = store.find(ask_id)
        if asked is None:
            self._send(404, {'error': f'ask not found: {ask_id}'})
            return
        resolved = store.answer(ask_id, answer.strip())
        if resolved is None:
            self._send(404, {'error': f'ask not found: {ask_id}'})
            return
        injected = inject_answer(store, resolved)
        self._send(200, {
            'ask': resolved.to_dict(),
            'session': resolved.origin,
            'resume': f'polyglav run --session-id {resolved.origin} "continue"',
            'injected': injected,
        })

    def log_message(self, fmt, *args):
        sys.stderr.write(f'[polyglav] {fmt % args}\n')
