# API

`polyglav serve` runs an HTTP JSON API on `127.0.0.1:8787` by default (override with `--host` / `--port`).

```bash
polyglav serve
# polyglav serve (read mode, no auth) - http://127.0.0.1:8787 (POST /chat, POST /cancel, GET /sessions, GET /health, GET /version)
```

All responses are JSON with `Content-Type: application/json`.

## Authentication

`polyglav serve` refuses to bind a non-loopback host without a token. Supply it with `--token`, `POLYGLAV_TOKEN`, or `serve.token` in config. Every route except `/health` and `/version` requires `Authorization: Bearer <token>`, and a missing or wrong token returns `401`.

```bash
TOKEN=$(openssl rand -hex 16)
polyglav serve --token "$TOKEN"
curl -H "Authorization: Bearer $TOKEN" localhost:8787/chat -X POST \
  -H 'Content-Type: application/json' -d '{"prompt": "Hi"}'
```

`--allow-unauthenticated` (or `serve.allow_unauthenticated`) permits a non-loopback bind without a token. Use it only for a container that publishes its ports on `127.0.0.1`, where the container-internal bind has to be `0.0.0.0` and nothing leaves the host. `/health` stays open so a monitor can poll it without credentials.

## POST /chat

Runs one agent turn on the same engine as the REPL and CLI. Request body:

| Field         | Type     | Description                                             |
|---------------|----------|---------------------------------------------------------|
| `prompt`      | string   | **Required.** The user message                          |
| `session`    | string   | Optional. Load or create a persistent session by name   |

Example:

```bash
curl localhost:8787/chat -X POST -H 'Content-Type: application/json' \
  -d '{"prompt": "Hi", "session": "api"}'
```

Response is the same `TurnResult` the CLI returns (see the README). `session` is the resolved session name. Errors: `400` for a missing/empty `prompt` or invalid JSON body.

`POST /chat` returns the completed turn. The REPL and CLI stream live output.

## As a tool for another agent or UI

`POST /chat` is the full-turn entry point for a UI or another agent. `POST /cancel` stops a paused turn and `GET /sessions` reads saved sessions. In write mode, the prompt can use the `catalog` tool to create roles, teams, and skills. The same mode and tool policy apply to every caller. For structured tool calls and session resources, use MCP. Jobs and fleet are CLI-first today.

## POST /cancel

Cancels the current paused turn. The response is `{"status": "cancelled"}` when a turn was paused, or `{"status": "idle"}` when there was nothing to cancel.

## GET /sessions

Lists saved session names.

```bash
curl localhost:8787/sessions
# {"sessions": ["ses_20260814_192251_ab12cd", "api"]}
```

## GET /health

Liveness check.

```bash
curl localhost:8787/health
# {"status": "ok"}
```

## GET /version

Returns the installed version.

```bash
curl localhost:8787/version
# {"version": "0.57.0"}
```

Unknown routes return `404 {"error": "not found"}`.
