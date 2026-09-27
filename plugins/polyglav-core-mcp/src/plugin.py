import sys

import client
import jsonrpc
import server as mcp_server

CONNECTIONS: dict[str, client.MCPClient] = {}

GLYPH = '◈'


def _log(text: str):
    print(f'[mcp] {text}', file=sys.stderr)


def _servers(config) -> list[dict]:
    servers = config.get('mcp.servers') if config is not None else None
    if not isinstance(servers, list):
        return []
    return [s for s in servers if isinstance(s, dict) and s.get('name')]


def _find_server(config, name: str) -> dict | None:
    for s in _servers(config):
        if s.get('name') == name:
            return s
    return None


def _call_tool(conn, tool_name: str, **arguments) -> str:
    try:
        result = conn.tools_call(tool_name, arguments)
    except Exception as e:
        return f'Error: MCP tool {conn.prefix}.{tool_name} failed: {e}'
    text = client.result_text(result)
    config = getattr(conn, 'config', None)
    max_chars = 0
    if config is not None:
        try:
            max_chars = max(0, int(config.get('tool_max_result_chars', 0)))
        except (TypeError, ValueError):
            max_chars = 0
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rsplit('\n', 1)[0] + '\n... (truncated)'
    return text


def _mcp_connect(server: str | None = None, _config=None) -> str:
    if _config is None:
        return 'Error: no config available'
    targets = []
    if server:
        found = _find_server(_config, server)
        if found is None:
            return f'Error: MCP server "{server}" not found in mcp.servers'
        targets = [found]
    else:
        targets = _servers(_config)
        if not targets:
            return 'No MCP servers configured - add "mcp.servers" to the config'
    lines = []
    for definition in targets:
        name = str(definition.get('name'))
        current = CONNECTIONS.get(name)
        if current is not None and current.connected:
            lines.append(f'{name}: already connected')
            continue
        conn = client.MCPClient(definition, log=_log)
        try:
            conn.connect()
        except client.ClientError as e:
            conn.close()
            lines.append(f'{name}: error - {e}')
            continue
        conn.config = _config
        CONNECTIONS[name] = conn
        lines.append(f'{name}: connected ({conn.mode}, {len(conn.tools)} tools) - '
                     'tools available from the next prompt')
    return '\n'.join(lines)


def _mcp_list(_config=None) -> str:
    servers = _servers(_config)
    if not servers:
        return 'No MCP servers configured - add "mcp.servers" to the config'
    lines = []
    for definition in servers:
        name = str(definition.get('name'))
        conn = CONNECTIONS.get(name)
        if conn is not None and conn.connected:
            tools = sorted(f'{conn.prefix}.{t.get("name")}'
                           for t in conn.tools if t.get('name'))
            detail = ', '.join(tools) or '(no tools)'
            lines.append(f'{name} ({definition.get("transport")}) - '
                         f'connected ({conn.mode}): {detail}')
        else:
            lines.append(f'{name} ({definition.get("transport")}) - not connected')
    return '\n'.join(lines)


def _mcp_disconnect(server: str | None = None, _config=None) -> str:
    names = [server] if server else list(CONNECTIONS)
    if not names:
        return 'No MCP connections to disconnect'
    lines = []
    for name in names:
        conn = CONNECTIONS.pop(name, None)
        if conn is None:
            lines.append(f'{name}: not connected')
            continue
        conn.close()
        lines.append(f'{name}: disconnected')
    return '\n'.join(lines)


def _register_management(registry):
    registry.register(
        name='mcp_connect',
        description='Connect to an MCP server from mcp.servers and import its tools. '
                    'Pass a server name, or omit it to connect all configured servers. '
                    'Imported tools are prefixed with the server name and become '
                    'available from the next prompt.',
        parameters={
            'type': 'object',
            'properties': {
                'server': {
                    'type': 'string',
                    'description': 'Server name from mcp.servers, or omit to connect all',
                },
            },
        },
        category='mcp',
        permission='web',
        key_arg='server',
        short='Connect to an MCP server',
        glyph=GLYPH,
        verb='MCP',
    )(_mcp_connect)

    registry.register(
        name='mcp_list',
        description='List configured MCP servers with their connection status and imported tools.',
        parameters={'type': 'object', 'properties': {}},
        category='mcp',
        permission='web',
        short='List MCP servers and connections',
        glyph=GLYPH,
        verb='MCP',
    )(_mcp_list)

    registry.register(
        name='mcp_disconnect',
        description='Disconnect from an MCP server and remove its imported tools. '
                    'Pass a server name, or omit it to disconnect all.',
        parameters={
            'type': 'object',
            'properties': {
                'server': {
                    'type': 'string',
                    'description': 'Server name to disconnect, or omit to disconnect all',
                },
            },
        },
        category='mcp',
        permission='web',
        key_arg='server',
        short='Disconnect from an MCP server',
        glyph=GLYPH,
        verb='MCP',
    )(_mcp_disconnect)


def _make_remote_handler(conn, tool_name: str):
    def handler(**arguments):
        return _call_tool(conn, tool_name, **arguments)
    return handler


def _register_connections(registry):
    for conn in list(CONNECTIONS.values()):
        if not conn.connected:
            continue
        for tool in conn.tools:
            tool_name = tool.get('name')
            if not isinstance(tool_name, str) or not tool_name:
                continue
            full = f'{conn.prefix}.{tool_name}' if conn.prefix else tool_name
            schema = tool.get('inputSchema')
            if not isinstance(schema, dict) or not schema:
                schema = {'type': 'object', 'properties': {}}
            description = tool.get('description') or f'MCP tool from server {conn.prefix}'

            registry.register(
                name=full,
                description=description,
                parameters=schema,
                category='mcp',
                permission='mcp',
                short=description[:60],
                status=lambda args, c=conn, t=tool_name: f'{c.prefix}.{t}',
                glyph=GLYPH,
                verb='MCP',
            )(_make_remote_handler(conn, tool_name))


def register_tools(registry):
    _register_management(registry)
    _register_connections(registry)


def register_services(services):
    class MCPServerAccess:
        def serve_stdio(self, engine):
            mcp_server.MCPServer(engine).serve_stdio()

        def handle_http(self, engine, raw_body: bytes):
            return mcp_server.MCPServer(engine).handle_http(raw_body)

    services['mcp_server'] = MCPServerAccess()


def register_commands(commands):
    @commands.register('mcp', description='Manage MCP servers (client and server)',
                       subcommands=[
                           ('list', 'List configured servers and connection status'),
                           ('connect', 'Connect to a server (all if no name)'),
                           ('disconnect', 'Disconnect from a server (all if no name)'),
                       ])
    def mcp_cmd(arg=''):
        chat = commands.chat_loop
        chat._init_tooling()
        if not chat._tool_registry or not chat._tool_policy:
            print('Tool calling is disabled (tool_calling: false)')
            return
        parts = arg.strip().split(maxsplit=1)
        action = parts[0] if parts else 'list'
        name = parts[1] if len(parts) > 1 else ''
        if action == 'connect':
            tool = 'mcp_connect'
        elif action == 'disconnect':
            tool = 'mcp_disconnect'
        elif action == 'list':
            tool = 'mcp_list'
        else:
            print('Usage: /mcp [list|connect <name>|disconnect <name>]')
            return
        arguments = {'server': name} if name and action in ('connect', 'disconnect') else {}
        print(chat._tool_registry.execute(tool, arguments, config=chat.config))
