import json

import jsonrpc
from client_http import HttpTransport, TransportError as HttpTransportError
from client_stdio import StdioTransport, TransportError as StdioTransportError

TransportError = (HttpTransportError, StdioTransportError)


class ClientError(Exception):
    pass


def _client_info() -> dict:
    try:
        from polyglav import get_version
        version = get_version()
    except Exception:
        version = '0.0.0'
    return {'name': 'polyglav', 'version': version}


def _param_headers(schema: dict | None, arguments: dict) -> dict:
    headers = {}
    props = (schema or {}).get('properties', {})
    if not isinstance(props, dict):
        return headers
    for prop, spec in props.items():
        if not isinstance(spec, dict):
            continue
        marker = spec.get('x-mcp-header')
        if not marker or not isinstance(marker, str):
            continue
        if not all(c.isalnum() or c in '-._~' for c in marker):
            continue
        if prop in arguments and arguments[prop] is not None:
            value = arguments[prop]
            if isinstance(value, bool):
                value = str(value).lower()
            else:
                value = str(value)
            headers[f'Mcp-Param-{marker}'] = jsonrpc.encode_header_value(value)
    return headers


class MCPClient:
    def __init__(self, server: dict, log=None):
        self._server_data = dict(server)
        self.name = str(server.get('name') or '')
        self.transport_name = str(server.get('transport') or 'stdio')
        self.prefix = str(server.get('prefix') or self.name)
        self.timeout = float(server.get('timeout') or 60)
        self._log = log
        self.mode: str | None = None
        self.version: str = jsonrpc.MODERN_VERSION
        self.server_info: dict | None = None
        self.tools: list[dict] = []
        self._transport = None
        self._connected = False
        self._setup()

    def _setup(self):
        if self.transport_name == 'http':
            url = self._server.get('url')
            if not url:
                raise ClientError(f'MCP server {self.name}: "url" is required for http transport')
            self._transport = HttpTransport(url, headers=self._server.get('headers'),
                                            timeout=self.timeout, log=self._log)
        elif self.transport_name == 'stdio':
            command = self._server.get('command')
            if not command:
                raise ClientError(f'MCP server {self.name}: "command" is required for stdio transport')
            self._transport = StdioTransport(
                str(command), self._server.get('args'), self._server.get('cwd'),
                self._server.get('env'), timeout=self.timeout, log=self._log,
            )
        else:
            raise ClientError(f'MCP server {self.name}: unknown transport "{self.transport_name}"')

    @property
    def _server(self) -> dict:
        return self._server_data

    def _info(self, text: str):
        if self._log is not None:
            self._log(text)

    @property
    def connected(self) -> bool:
        if not self._connected or self._transport is None:
            return False
        if isinstance(self._transport, StdioTransport):
            return self._transport.alive
        return True

    def _request(self, method: str, params: dict | None = None,
                 modern: bool = True, name: str | None = None,
                 extra_headers: dict | None = None) -> dict:
        if isinstance(self._transport, StdioTransport):
            return self._transport.request(method, params, timeout=self.timeout)
        return self._transport.request(method, params, modern=modern, name=name,
                                       version=self.version,
                                       extra_headers=extra_headers)

    def connect(self):
        self._negotiate()
        self.tools = self._fetch_tools()
        self._connected = True

    def _negotiate(self):
        probe = {'_meta': jsonrpc.modern_meta(version=jsonrpc.MODERN_VERSION,
                                              client_info=_client_info())}
        if isinstance(self._transport, StdioTransport):
            try:
                self._transport.start()
            except StdioTransportError as e:
                raise ClientError(f'MCP server {self.name}: {e}')
            try:
                result = self._transport.request('server/discover', probe,
                                                 timeout=self.timeout)
                self._negotiated_modern(result)
                return
            except jsonrpc.MCPError as e:
                if e.code == jsonrpc.CODE_UNSUPPORTED_VERSION:
                    self._pick_version(e)
                    return
                raise ClientError(f'MCP server {self.name}: {e.message}')
            except StdioTransportError:
                pass
            self._fallback_legacy()
            return
        try:
            result = self._transport.request('server/discover', probe, modern=True,
                                             version=jsonrpc.MODERN_VERSION)
            self._negotiated_modern(result)
            return
        except jsonrpc.MCPError as e:
            if e.code == jsonrpc.CODE_UNSUPPORTED_VERSION:
                self._pick_version(e)
                return
            raise ClientError(f'MCP server {self.name}: {e.message}')
        except TransportError:
            pass
        self._fallback_legacy()

    def _negotiated_modern(self, result: dict):
        self.mode = 'modern'
        supported = result.get('supportedVersions') or [jsonrpc.MODERN_VERSION]
        self.version = self._choose_version(supported)
        if 'serverInfo' in result:
            self.server_info = result.get('serverInfo')
        if isinstance(result.get('capabilities'), dict):
            pass
        self._info(f'[mcp] {self.name}: modern protocol {self.version}')

    def _pick_version(self, error: jsonrpc.MCPError):
        supported = []
        if isinstance(error.data, dict) and isinstance(error.data.get('supported'), list):
            supported = [str(v) for v in error.data['supported']]
        if not supported:
            raise ClientError(
                f'MCP server {self.name} does not support protocol {jsonrpc.MODERN_VERSION}')
        self.mode = 'modern'
        self.version = self._choose_version(supported)
        self._info(f'[mcp] {self.name}: negotiated modern protocol {self.version}')

    @staticmethod
    def _choose_version(supported: list[str]) -> str:
        if jsonrpc.MODERN_VERSION in supported:
            return jsonrpc.MODERN_VERSION
        if jsonrpc.LEGACY_VERSION in supported:
            return jsonrpc.LEGACY_VERSION
        return supported[0]

    def _fallback_legacy(self):
        self.mode = 'legacy'
        self.version = jsonrpc.LEGACY_VERSION
        self._info(f'[mcp] {self.name}: legacy initialize protocol')
        try:
            params = {
                'protocolVersion': jsonrpc.LEGACY_VERSION,
                'capabilities': {},
                'clientInfo': _client_info(),
            }
            result = self._request('initialize', params, modern=False)
            if isinstance(result, dict):
                self.server_info = result.get('serverInfo')
                negotiated = result.get('protocolVersion')
                if isinstance(negotiated, str) and negotiated:
                    self.version = negotiated
            if isinstance(self._transport, HttpTransport):
                self._transport.notify('notifications/initialized', modern=False)
            else:
                self._transport.notify('notifications/initialized')
        except (jsonrpc.MCPError, TransportError) as e:
            raise ClientError(f'MCP server {self.name}: initialize failed: {e}')

    def _fetch_tools(self) -> list[dict]:
        tools = []
        cursor = None
        for _ in range(100):
            params = {}
            if cursor:
                params['cursor'] = cursor
            if self.mode == 'modern':
                params['_meta'] = jsonrpc.modern_meta(
                    version=self.version, client_info=_client_info())
            result = self._request('tools/list', params, modern=self.mode == 'modern')
            items = result.get('tools') or []
            tools.extend(i for i in items if isinstance(i, dict))
            next_cursor = result.get('nextCursor')
            if not next_cursor:
                break
            cursor = next_cursor
        return tools

    def tools_call(self, name: str, arguments: dict) -> dict:
        params = {'name': name, 'arguments': arguments}
        extra = {}
        schema = None
        for tool in self.tools:
            if tool.get('name') == name:
                schema = tool
                break
        if self.mode == 'modern':
            params['_meta'] = jsonrpc.modern_meta(version=self.version,
                                                  client_info=_client_info())
            if isinstance(schema, dict):
                extra = _param_headers(schema.get('inputSchema'), arguments)
        return self._request('tools/call', params, modern=self.mode == 'modern',
                             name=name, extra_headers=extra)

    def close(self):
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception:
                pass
        self._transport = None
        self._connected = False
        self.tools = []


def result_text(result: dict) -> str:
    is_error = bool(result.get('isError'))
    parts = []
    for item in result.get('content') or []:
        if not isinstance(item, dict):
            continue
        if item.get('type') == 'text' and isinstance(item.get('text'), str):
            parts.append(item['text'])
    structured = result.get('structuredContent')
    if structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False))
    text = '\n'.join(parts).strip()
    if not text:
        text = '(empty MCP tool result)'
    if is_error and not text.startswith('Error'):
        text = f'Error: {text}'
    return text
