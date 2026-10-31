import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from polyglav import get_version
from polyglav.config import Config, verbosity_level
from polyglav.engine import Engine
from polyglav.ui import HeadlessUI


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
        if self.path == '/cancel':
            server = self.server
            with server.lock:
                paused = server.engine.paused_turn() is not None
                if paused:
                    server.engine.cancel_turn()
            self._send(200, {'status': 'cancelled' if paused else 'idle'})
            return
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


def _run(args):
    config = Config(path=args.path)
    if getattr(args, 'mode', None):
        config.apply('mode', args.mode)
    ui = HeadlessUI(auto='deny', verbose=False, stream=False,
                    thinking_level=verbosity_level(config, 'thinking'),
                    footer_level=verbosity_level(config, 'footer'),
                    footer_tokens=config.get('footer_tokens', ['context']))
    engine = Engine(config, ui=ui)
    pm = getattr(engine, '_plugin_manager', None)
    mcp_service = pm.service('mcp_server') if pm is not None else None
    server = HeadlessServer((args.host, args.port), ChatHandler,
                            engine=engine, mcp_service=mcp_service)
    print(f'polyglav serve ({config.get("mode")} mode) - http://{args.host}:{args.port} '
          f'(POST /chat, POST /cancel, GET /sessions, GET /health, GET /version'
          f'{", POST /mcp" if mcp_service else ""})', file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def register_cli(cli):
    import argparse
    p = cli.add_parser('serve', help='HTTP JSON API server (stdlib http.server)')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8787)
    p.add_argument('--path', default=argparse.SUPPRESS,
                   help='Project path (default: current directory)')
    p.add_argument('--mode', help='Agent mode override (read or write, default read)')
    p.set_defaults(func=_run)
