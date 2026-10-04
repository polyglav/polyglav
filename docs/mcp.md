# MCP (Model Context Protocol)

Polyglav speaks MCP in both directions through the bundled `polyglav-core-mcp` plugin. It is stdlib-only, with no third-party `mcp` library, and uses JSON-RPC 2.0 over newline-delimited stdio and SSE over urllib:

- **Client** - connect to external MCP servers (stdio or HTTP), import their tools into the `ToolRegistry`, and call them like any other Polyglav tool. Tool policy, `/tool`, `/help`, glyph activity lines, query refinement and session logging all apply.
- **Server** - expose Polyglav's registered tools and sessions as an MCP server to external agents (Claude, opencode, and other MCP clients) over stdio (`polyglav mcp`) and HTTP (`POST /mcp` on `polyglav serve`).

Both eras are supported and negotiated per connection: the modern stateless revision (`2026-07-28`, per-request `_meta`) and the legacy `initialize`-handshake revisions (`2025-11-25` and earlier). The client probes `server/discover` and falls back to `initialize`. The server serves either, based on how the client opens.

## Client

### Config

```json
{
  "mcp.servers": [
    {
      "name": "github",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "cwd": null,
      "env": {},
      "prefix": "github",
      "timeout": 60
    },
    {
      "name": "filesystem",
      "transport": "http",
      "url": "http://127.0.0.1:8787/mcp",
      "headers": {},
      "prefix": "filesystem"
    }
  ]
}
```

| Key         | Default            | Description                                                                 |
|-------------|--------------------|-----------------------------------------------------------------------------|
| `name`      | *(required)*       | Unique server name, also the tool prefix fallback                            |
| `transport` | `"stdio"`          | `stdio` (subprocess) or `http` (streamable HTTP)                             |
| `command`   | *(stdio required)* | Executable that launches the server                                          |
| `args`      | `[]`               | Command arguments                                                            |
| `cwd`       | `null`             | Working directory for the subprocess                                         |
| `env`       | `{}`               | Extra environment variables                                                   |
| `url`       | *(http required)*  | MCP endpoint URL                                                             |
| `headers`   | `{}`               | Extra HTTP headers (e.g. `Authorization`)                                    |
| `prefix`    | server `name`      | Namespace for imported tools (`<prefix>.<tool>`)                             |
| `timeout`   | `60`               | Seconds before a request to the server is cancelled                          |

### Tools and commands

| Tool / command                 | Purpose                                                                     |
|--------------------------------|-----------------------------------------------------------------------------|
| `mcp_connect` / `/mcp connect <name>` | Connect to a server (or all configured, when no name is given) and import its tools |
| `mcp_list` / `/mcp list`       | Show configured servers, connection status and imported tools                |
| `mcp_disconnect` / `/mcp disconnect <name>` | Disconnect and unregister a server's tools                            |

Imported tools are named `<prefix>.<tool>` (e.g. `github.list_issues`) and inherit the `mcp` permission category, which defaults to `ask`, so each call confirms in the REPL. Flip it to `allow`/`deny` via `tool_permission.mcp` or per-name `tools.allow`/`tools.deny`. A fresh `ToolRegistry` is built each turn, so tools connected mid-prompt become available from the next prompt.

### Security

- Treat server-provided tool descriptions and schemas as untrusted metadata.
- stdio spawns arbitrary commands from your config. Only configure servers you trust.
- HTTP servers are contacted over the network. Credentials in `headers` are sent as-is.
- Every imported tool call routes through `ToolPolicy` (`mcp: ask` by default), giving a user confirmation in the REPL before the remote call runs.
- Tool results are logged to the session like any tool result.

## Server

The server exposes Polyglav's currently registered tools (policy-filtered) and its saved sessions as resources, without mutating the active session. Tool execution follows `ToolPolicy`. `ask` tools run directly (the external MCP client is the user-in-the-loop and shows its own confirmations) unless `mcp_server.allow_ask` is `false`, which refuses them.

### stdio (`polyglav mcp`)

```bash
polyglav mcp                # read JSON-RPC from stdin, write to stdout
```

An MCP client launches this as a subprocess (newline-delimited JSON), `initialize` or `server/discover`, then `tools/list` / `tools/call`.

### HTTP (`POST /mcp` on `polyglav serve`)

```bash
polyglav serve --port 8787  # adds POST /mcp when the plugin is loaded
```

This implements the streamable HTTP transport: each JSON-RPC request is its own POST, answered with JSON (or SSE for streaming-capable requests).

### Resources

Sessions are exposed as MCP resources under `polyglav://session/<name>` with `resources/list` and `resources/read` returning the session JSON.

## Config

| Key                     | Default        | Description                                                        |
|-------------------------|----------------|--------------------------------------------------------------------|
| `tool_permission.mcp`   | `"ask"`        | Permission action for imported MCP tools and the `mcp_*` tools      |
| `mcp.servers`           | `[]`           | Client server definitions                                            |
| `mcp_server.allow_ask`  | `true`         | When serving MCP, run `ask`-policy tools (deferred to the client) vs refuse them |

## Interop notes

- Modern (2026-07-28) clients/servers: `server/discover`, per-request `_meta` (`protocolVersion` + `clientCapabilities`). Missing required `_meta` fields are rejected with `-32602`.
- Legacy (<= 2025-11-25) clients/servers: `initialize` handshake, then `tools/*`.
- The deprecated 2024-11-05 HTTP+SSE transport is not implemented.
- Multi-round-trip requests (MRTR), elicitation, sampling, auth, and the tasks/apps extensions are out of scope for v1. A server asking for input returns an `input_required` result, which the client reports as an unsupported error.
