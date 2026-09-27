import json
import sys

import jsonrpc
import resources


def _version() -> str:
    try:
        from polyglav import get_version
        return get_version()
    except Exception:
        return '0.0.0'


class MCPServer:
    def __init__(self, engine):
        self.engine = engine
        self._mode = None

    def _server_info(self) -> dict:
        return {'name': 'polyglav', 'version': _version()}

    def _tooling(self):
        try:
            self.engine._init_tooling()
        except Exception:
            pass
        return getattr(self.engine, '_tool_registry', None), \
            getattr(self.engine, '_tool_policy', None)

    def _result(self, request_id, body: dict) -> dict:
        result = dict(body)
        if self._mode == 'modern':
            result['resultType'] = 'complete'
            result['_meta'] = {jsonrpc.META_SERVER_INFO: self._server_info()}
        return jsonrpc.make_response(request_id, result)

    def dispatch(self, msg) -> dict | None:
        if not isinstance(msg, dict):
            return jsonrpc.make_error(None, jsonrpc.CODE_INVALID_REQUEST, 'Invalid request')
        rid = msg.get('id')
        method = msg.get('method')
        if not isinstance(method, str) or not method:
            return jsonrpc.make_error(rid, jsonrpc.CODE_INVALID_REQUEST,
                                      'Invalid request: missing method')
        if method == 'initialize':
            self._mode = 'legacy'
            return jsonrpc.make_response(rid, {
                'protocolVersion': jsonrpc.LEGACY_VERSION,
                'capabilities': {'tools': {}},
                'serverInfo': self._server_info(),
            })
        if method == 'server/discover':
            self._mode = 'modern'
            return jsonrpc.make_response(rid, {
                'resultType': 'complete',
                'supportedVersions': jsonrpc.SUPPORTED_VERSIONS,
                'capabilities': {'tools': {}, 'resources': {}},
                '_meta': {jsonrpc.META_SERVER_INFO: self._server_info()},
            })
        if method in ('notifications/initialized', 'notifications/cancelled'):
            return None
        if method == 'ping':
            return jsonrpc.make_response(rid, {})
        modern = jsonrpc.is_modern_request(msg) or self._mode == 'modern'
        if modern:
            self._mode = 'modern'
            error = self._validate_modern(msg)
            if error:
                return error
        if method == 'tools/list':
            return self._tools_list(msg)
        if method == 'tools/call':
            return self._tools_call(msg)
        if method == 'resources/list':
            return self._resources_list(msg)
        if method == 'resources/read':
            return self._resources_read(msg)
        return jsonrpc.make_error(rid, jsonrpc.CODE_METHOD_NOT_FOUND,
                                  f'Method not found: {method}')

    def _validate_modern(self, msg) -> dict | None:
        rid = msg.get('id')
        params = msg.get('params') or {}
        meta = params.get('_meta') or {}
        version = meta.get(jsonrpc.META_VERSION)
        if version is not None and version not in jsonrpc.SUPPORTED_VERSIONS:
            return jsonrpc.make_error(
                rid, jsonrpc.CODE_UNSUPPORTED_VERSION,
                'Unsupported protocol version',
                {'supported': jsonrpc.SUPPORTED_VERSIONS, 'requested': version},
            )
        if jsonrpc.META_CLIENT_CAPS not in meta:
            return jsonrpc.make_error(
                rid, jsonrpc.CODE_INVALID_PARAMS,
                f'Missing required _meta field {jsonrpc.META_CLIENT_CAPS}')
        return None

    def _tools_list(self, msg) -> dict:
        registry, policy = self._tooling()
        tools = []
        if registry is not None:
            for name in registry.names():
                if policy is not None and not policy.allowed(
                        name, registry.permission_for(name)):
                    continue
                info = registry.info(name)
                if info is None:
                    continue
                tools.append({
                    'name': name,
                    'description': info['description'],
                    'inputSchema': info['parameters'],
                })
        return self._result(msg.get('id'), {'tools': tools})

    def _tools_call(self, msg) -> dict:
        rid = msg.get('id')
        params = msg.get('params') or {}
        name = params.get('name')
        arguments = params.get('arguments') or {}
        registry, policy = self._tooling()
        if registry is None or name not in registry.names():
            return jsonrpc.make_error(rid, jsonrpc.CODE_INVALID_PARAMS,
                                      f'Unknown tool: {name}')
        cleaned = registry.clean_args(name, arguments)
        if policy is not None:
            path_arg = registry.path_arg_for(name)
            path = cleaned.get(path_arg) if path_arg else None
            action = policy.action(name, registry.permission_for(name), path)
            if action == 'deny':
                return self._tool_result(rid, f'Error: tool "{name}" is disabled by tool policy',
                                         is_error=True)
            if action == 'ask':
                allow = bool(self.engine.config.get('mcp_server.allow_ask', True))
                if not allow:
                    return self._tool_result(rid, f'Error: tool "{name}" requires confirmation',
                                             is_error=True)
        output = registry.execute(name, cleaned, config=self.engine.config)
        is_error = output.startswith(('Error', '[cancelled]'))
        return self._tool_result(rid, output, is_error=is_error)

    def _tool_result(self, request_id, output: str, is_error: bool = False) -> dict:
        return self._result(request_id, {
            'content': [{'type': 'text', 'text': output}],
            'isError': is_error,
        })

    def _resources_list(self, msg) -> dict:
        return self._result(msg.get('id'), {'resources': resources.list_resources(self.engine)})

    def _resources_read(self, msg) -> dict:
        rid = msg.get('id')
        uri = (msg.get('params') or {}).get('uri')
        content = resources.read_resource(self.engine, uri) if isinstance(uri, str) else None
        if content is None:
            return jsonrpc.make_error(rid, jsonrpc.CODE_INVALID_PARAMS,
                                      f'Resource not found: {uri}')
        return self._result(rid, {'contents': [content]})

    def serve_stdio(self):
        self._mode = None
        for line in sys.stdin:
            msg = jsonrpc.parse_line(line)
            if msg is None:
                continue
            response = self.dispatch(msg)
            if response is not None:
                sys.stdout.write(jsonrpc.encode_message(response) + '\n')
                sys.stdout.flush()

    def handle_http(self, raw_body: bytes) -> tuple[int, dict, bytes]:
        try:
            msg = json.loads(raw_body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = jsonrpc.encode_message(
                jsonrpc.make_error(None, jsonrpc.CODE_PARSE_ERROR, 'Parse error'))
            return 400, {'Content-Type': 'application/json'}, body.encode('utf-8')
        response = self.dispatch(msg)
        if response is None:
            return 202, {}, b''
        body = jsonrpc.encode_message(response)
        return 200, {'Content-Type': 'application/json'}, body.encode('utf-8')
