# Deployment

You can run `polyglav serve` directly, but a fleet of agents is best supervised by Docker: one container per agent, restarted on failure, with config and sessions on a mounted folder. Polyglav has two install paths:

- **Single interactive agent** - install with pipx and run the REPL, `polyglav run`, or `polyglav serve` by hand. See [INSTALL.md](../INSTALL.md).
- **Supervised fleet or always-on server** - this page. Build the image from the repo's `Dockerfile` and run one container per agent with `docker-compose.yml.example`.

The Docker templates live at the repo root (`Dockerfile`, `polyglav-entrypoint.sh`, `docker-compose.yml.example`) and work as-is. Per-agent values (the project path, the port, and the API key) are configured on your machine, never in the templates. A deployed agent is always `polyglav serve` pointed at a folder inside the container. The folder holds `.polyglav/config.json` (provider, model, system prompt, tool permissions, plugins) and writes sessions under `.polyglav/sessions/`. Mount that folder into the container and the agent keeps its state across restarts.

## Docker

The image runs `polyglav serve` and takes three environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `POLYGLAV_HOST` | `0.0.0.0` | Bind address |
| `POLYGLAV_PORT` | `8787` | Bind port |
| `POLYGLAV_PATH` | (unset) | Project path the agent is scoped to. When set, the server uses `--path` and reads `.polyglav/config.json` from that directory |

Build the image from the repo root:

```bash
docker build -t polyglav .
```

### Single agent

```bash
docker run -d --name docs-agent -p 127.0.0.1:8781:8781 \
  -e POLYGLAV_PORT=8781 \
  -e POLYGLAV_PATH=/srv/docs \
  -v "$PWD/agents/docs:/srv/docs" \
  polyglav
```

The mounted `agents/docs` directory holds the agent's `.polyglav/config.json` (model and permissions) and its sessions. The API key resolves from the global provider registry (`~/.config/polyglav/providers.json`), so mount that file into the container (or register the connection with `/connect` inside it) for keyed providers. The container runs as root, so agent-written session files are root-owned on the host. Add `--user "$(id -u):$(id -g)"` if you want them owned by your uid.

### Fleet with Docker Compose

The repo root's `docker-compose.yml.example` defines one service per agent. Copy it to `docker-compose.yml` and adjust the services (name, `POLYGLAV_PATH`, port, and volume, since the API key and model come from the mounted `.polyglav/config.json`):

```yaml
services:
  docs-agent:
    build:
      context: .
    environment:
      POLYGLAV_PORT: 8781
      POLYGLAV_PATH: /srv/docs
    volumes:
      - ./agents/docs:/srv/docs
    ports:
      - "127.0.0.1:8781:8781"
    restart: unless-stopped
```

Ports publish on `127.0.0.1` so the JSON API stays host-local behind your reverse proxy. Containers run as root. Add `user: "1000:1000"` (your uid) to a service if you want agent-written files in the mounted folders owned by you. Add an agent by copying a service block and changing the name, port, and volume. Bring the fleet up:

```bash
docker compose up -d
```

Compose's `restart: unless-stopped` restarts a dead agent. See [docs/usage/programming.md](usage/programming.md) for a full role-based programming fleet built on this template.

## Health checks

Every deployed agent exposes `GET /health`, which returns `{"status": "ok"}`. For an external monitor, poll the health endpoint on each agent's port:

```bash
curl -fsS localhost:8781/health
```
