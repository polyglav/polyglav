# API

`polyglav serve` runs an HTTP JSON API on `127.0.0.1:8787` by default (override with `--host` / `--port`).

```bash
polyglav serve
# polyglav serve - http://127.0.0.1:8787 (POST /chat, POST /mcp, GET /sessions, GET /health, GET /version)
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
# {"version": "0.33.0"}
```

Unknown routes return `404 {"error": "not found"}`.
