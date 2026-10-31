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
            result = server.engine.chat(prompt, origin='api')
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
        else:
            self._send(404, {'error': 'not found'})

    def log_message(self, fmt, *args):
        sys.stderr.write(f'[polyglav] {fmt % args}\n')
