import json
import urllib.request
import urllib.error

import jsonrpc

DEFAULT_TIMEOUT = 60.0


class TransportError(Exception):
    pass


class HttpTransport:
    def __init__(self, url: str, headers: dict | None = None,
                 timeout: float = DEFAULT_TIMEOUT, log=None):
        self.url = url
        self.user_headers = dict(headers or {})
        self.timeout = timeout
        self._log = log
        self.session_id = None

    def _base_headers(self, modern: bool, method: str,
                      version: str = jsonrpc.MODERN_VERSION) -> dict:
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream',
        }
        if modern:
            headers['MCP-Protocol-Version'] = version
            headers['Mcp-Method'] = method
        if self.session_id:
            headers['Mcp-Session-Id'] = self.session_id
        return headers

    @staticmethod
    def _name_header(value: str) -> str:
        return jsonrpc.encode_header_value(value)

    def _post(self, body: dict, headers: dict) -> tuple[int, dict, str]:
        data = jsonrpc.encode_message(body).encode('utf-8')
        req = urllib.request.Request(self.url, data=data, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                ctype = resp.headers.get('Content-Type', '')
                sid = resp.headers.get('Mcp-Session-Id')
                if sid:
                    self.session_id = sid
                if 'text/event-stream' in ctype.lower():
                    message = None
                    for event, data_str in jsonrpc.iter_sse(resp):
                        if event not in ('message', ''):
                            continue
                        try:
                            parsed = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(parsed, dict) and 'id' in parsed:
                            message = parsed
                    if message is None:
                        raise TransportError('MCP server returned an empty SSE stream')
                    return 200, message, ctype
                raw = resp.read().decode('utf-8', errors='replace')
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    raise TransportError(f'MCP server returned non-JSON response: {raw[:200]}')
                if not isinstance(message, dict):
                    raise TransportError('MCP server returned a non-object response')
                return resp.status, message, ctype
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            return e.code, body, e.headers.get('Content-Type', '')

    def request(self, method: str, params: dict | None = None,
                modern: bool = True, name: str | None = None,
                version: str = jsonrpc.MODERN_VERSION,
                extra_headers: dict | None = None) -> dict:
        body = jsonrpc.make_request(self._next_id(), method, params)
        headers = self._base_headers(modern, method, version)
        headers.update(self.user_headers)
        if extra_headers:
            headers.update(extra_headers)
        if name is not None:
            headers['Mcp-Name'] = self._name_header(name)
        status, message, ctype = self._post(body, headers)
        if status >= 400:
            self._raise_http_error(status, message)
        if isinstance(message, str):
            raise TransportError(
                f'MCP server returned HTTP {status}: {self._short(message, ctype)}')
        if 'error' in message:
            err = message['error']
            raise jsonrpc.MCPError(err.get('code', 0), err.get('message', 'MCP error'),
                                   err.get('data'))
        return message.get('result') or {}

    @staticmethod
    def _raise_http_error(status: int, message):
        if isinstance(message, str):
            try:
                parsed = json.loads(message)
            except json.JSONDecodeError:
                raise TransportError(f'MCP server returned HTTP {status}: {message[:200]}')
        else:
            parsed = message
        if isinstance(parsed, dict) and isinstance(parsed.get('error'), dict):
            err = parsed['error']
            raise jsonrpc.MCPError(err.get('code', 0), err.get('message', 'MCP error'),
                                   err.get('data'))
        raise TransportError(f'MCP server returned HTTP {status}: {self._short(message, "")}')

    def notify(self, method: str, params: dict | None = None,
               modern: bool = True, version: str = jsonrpc.MODERN_VERSION):
        body = jsonrpc.make_notification(method, params)
        headers = self._base_headers(modern, method, version)
        headers.update(self.user_headers)
        data = jsonrpc.encode_message(body).encode('utf-8')
        req = urllib.request.Request(self.url, data=data, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=self.timeout):
                pass
        except urllib.error.HTTPError:
            pass
        except OSError:
            pass

    def close(self):
        self.session_id = None

    def _next_id(self) -> int:
        if not hasattr(self, '_id_counter'):
            self._id_counter = 0
        self._id_counter += 1
        return self._id_counter

    @staticmethod
    def _short(message, ctype: str) -> str:
        if isinstance(message, str):
            return message[:200]
        return f'JSON-RPC error response ({ctype})'
