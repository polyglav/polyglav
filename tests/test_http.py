import unittest
import threading
from unittest.mock import MagicMock, patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from polyglav.utils.http import stream_sse


class _FakeResp:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n):
        if not self.chunks:
            return b''
        return self.chunks.pop(0)


class TestStreamSse(unittest.TestCase):

    def _stream(self, chunks):
        resp = _FakeResp(chunks)
        opener = MagicMock()
        opener.open.return_value = resp
        with patch('polyglav.utils.http._opener', return_value=opener):
            return list(stream_sse('https://test.api.com/chat', {}, {'m': 1}))

    def test_parses_data_lines_and_done_marker(self):
        sse = (
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
            'data: [DONE]\n'
        )
        events = self._stream([sse.encode('utf-8')])
        self.assertEqual(events, [
            {'choices': [{'delta': {'content': 'Hello'}}]},
            {'choices': [{'delta': {'content': ' world'}}]},
            {'type': 'done'},
        ])

    def test_survives_multibyte_char_split_across_chunks(self):
        sse = 'data: {"choices":[{"delta":{"content":"héllo wörld"}}]}\n\ndata: [DONE]\n'
        data = sse.encode('utf-8')
        first_byte = data.index(b'\xc3')
        chunks = [data[:first_byte + 1], data[first_byte + 1:]]
        events = self._stream(chunks)
        self.assertEqual(events, [
            {'choices': [{'delta': {'content': 'héllo wörld'}}]},
            {'type': 'done'},
        ])

    def test_error_event_on_http_error(self):
        opener = MagicMock()
        opener.open.side_effect = __import__('urllib.error').error.HTTPError(
            'url', 500, 'boom', {}, None)
        with patch('polyglav.utils.http._opener', return_value=opener):
            events = list(stream_sse('https://test.api.com/chat', {}, {'m': 1}))
        self.assertEqual(events[0]['type'], 'error')
        self.assertEqual(events[0]['code'], 500)


class _RedirectHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_POST(self):
        if self.path == '/start':
            self.send_response(301)
            self.send_header('Location', '/target')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if self.path == '/target':
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            body = b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_GET(self):
        if self.path == '/target':
            self.send_error(405, 'Method Not Allowed')
            return
        self.send_error(404)

    def log_message(self, *args):
        pass


class TestStreamSseRedirect(unittest.TestCase):

    def test_redirect_preserves_post_method(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), _RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/start'
            sse = 'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n'
            events = list(stream_sse(url, {}, {'m': 1}))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(events, [
            {'choices': [{'delta': {'content': 'Hello'}}]},
            {'type': 'done'},
        ])


if __name__ == '__main__':
    unittest.main()
