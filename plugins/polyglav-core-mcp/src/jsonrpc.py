import json

MODERN_VERSION = '2026-07-28'
LEGACY_VERSION = '2025-11-25'
SUPPORTED_VERSIONS = [MODERN_VERSION, LEGACY_VERSION]

META_VERSION = 'io.modelcontextprotocol/protocolVersion'
META_CLIENT_INFO = 'io.modelcontextprotocol/clientInfo'
META_CLIENT_CAPS = 'io.modelcontextprotocol/clientCapabilities'
META_SERVER_INFO = 'io.modelcontextprotocol/serverInfo'

CODE_PARSE_ERROR = -32700
CODE_INVALID_REQUEST = -32600
CODE_METHOD_NOT_FOUND = -32601
CODE_INVALID_PARAMS = -32602
CODE_INTERNAL_ERROR = -32603
CODE_HEADER_MISMATCH = -32020
CODE_UNSUPPORTED_VERSION = -32022


class MCPError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def make_request(request_id, method: str, params: dict | None = None) -> dict:
    msg = {'jsonrpc': '2.0', 'id': request_id, 'method': method}
    if params is not None:
        msg['params'] = params
    return msg


def make_notification(method: str, params: dict | None = None) -> dict:
    msg = {'jsonrpc': '2.0', 'method': method}
    if params is not None:
        msg['params'] = params
    return msg


def make_response(request_id, result) -> dict:
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def make_error(request_id, code: int, message: str, data=None) -> dict:
    error = {'code': code, 'message': message}
    if data is not None:
        error['data'] = data
    return {'jsonrpc': '2.0', 'id': request_id, 'error': error}


def encode_message(msg: dict) -> str:
    return json.dumps(msg, separators=(',', ':'))


def parse_line(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def modern_meta(version: str = MODERN_VERSION, client_info: dict | None = None,
                capabilities: dict | None = None) -> dict:
    meta = {
        META_VERSION: version,
        META_CLIENT_CAPS: capabilities or {},
    }
    if client_info is not None:
        meta[META_CLIENT_INFO] = client_info
    return meta


def is_modern_request(msg: dict) -> bool:
    params = msg.get('params')
    if not isinstance(params, dict):
        return False
    meta = params.get('_meta')
    return isinstance(meta, dict) and META_VERSION in meta


def iter_sse(resp, chunk_size: int = 4096):
    buffer = b''
    event = None
    data_lines = []
    while True:
        chunk = resp.read(chunk_size)
        if not chunk:
            break
        buffer += chunk
        while b'\n' in buffer:
            line, buffer = buffer.split(b'\n', 1)
            line = line.rstrip(b'\r')
            if not line:
                if data_lines:
                    yield event, '\n'.join(data_lines)
                event = None
                data_lines = []
                continue
            if line.startswith(b':'):
                continue
            if line.startswith(b'event:'):
                event = line[6:].strip().decode('utf-8', errors='replace')
            elif line.startswith(b'data:'):
                data_lines.append(line[5:].strip().decode('utf-8', errors='replace'))
    if data_lines:
        yield event, '\n'.join(data_lines)


def header_safe(value: str) -> bool:
    if not value or value != value.strip():
        return False
    if value.startswith('=?base64?') and value.endswith('?='):
        return False
    return all(0x20 <= ord(ch) <= 0x7E for ch in value)


def encode_header_value(value: str) -> str:
    if header_safe(value):
        return value
    import base64
    encoded = base64.b64encode(value.encode('utf-8')).decode('ascii')
    return f'=?base64?{encoded}?='
