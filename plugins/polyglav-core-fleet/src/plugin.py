import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

PORT_LO = 8780
PORT_HI = 8890
BACKOFF_START = 5.0
BACKOFF_MAX = 60.0
HEALTH_TIMEOUT = 2.0
UNHEALTHY_THRESHOLD = 2


def _fleet_token() -> str:
    return str(os.environ.get('POLYGLAV_TOKEN', '') or '').strip()

STARTING = 'starting'
RUNNING = 'running'
HEALTHY = 'healthy'
UNHEALTHY = 'unhealthy'
RESTARTING = 'restarting'
STOPPED = 'stopped'
DISABLED = 'disabled'
CRASHED = 'crashed'

_ACTIVE_STATES = {STARTING, RUNNING, HEALTHY, UNHEALTHY}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass
class AgentDef:
    name: str
    dir: str = ''
    enabled: bool = True
    prefer_port: int = 0
    max_restarts: int = 10
    command: list = field(default_factory=list)
    added_at: str = ''

    @classmethod
    def from_dict(cls, d: dict) -> 'AgentDef':
        return cls(
            name=d.get('name', ''),
            dir=d.get('dir', ''),
            enabled=bool(d.get('enabled', True)),
            prefer_port=int(d.get('prefer_port', 0) or 0),
            max_restarts=int(d.get('max_restarts', 10) if d.get('max_restarts') is not None else 10),
            command=list(d.get('command') or []),
            added_at=d.get('added_at', ''),
        )

    def to_dict(self) -> dict:
        body = {
            'name': self.name,
            'dir': self.dir,
            'enabled': self.enabled,
            'prefer_port': self.prefer_port,
            'max_restarts': self.max_restarts,
        }
        if self.command:
            body['command'] = list(self.command)
        if self.added_at:
            body['added_at'] = self.added_at
        return body


@dataclass
class AgentState:
    status: str = STOPPED
    pid: int = 0
    port: int = 0
    started_at: str = ''
    restarts: int = 0
    next_restart_at: str = ''
    last_error: str = ''
    consecutive_unhealthy: int = 0

    @classmethod
    def from_dict(cls, d: dict | None) -> 'AgentState':
        d = d or {}
        return cls(
            status=d.get('status', STOPPED),
            pid=int(d.get('pid', 0) or 0),
            port=int(d.get('port', 0) or 0),
            started_at=d.get('started_at', ''),
            restarts=int(d.get('restarts', 0) or 0),
            next_restart_at=d.get('next_restart_at', ''),
            last_error=d.get('last_error', ''),
            consecutive_unhealthy=int(d.get('consecutive_unhealthy', 0) or 0),
        )

    def to_dict(self) -> dict:
        body = {
            'status': self.status,
            'pid': self.pid,
            'port': self.port,
            'restarts': self.restarts,
            'consecutive_unhealthy': self.consecutive_unhealthy,
        }
        if self.started_at:
            body['started_at'] = self.started_at
        if self.next_restart_at:
            body['next_restart_at'] = self.next_restart_at
        if self.last_error:
            body['last_error'] = self.last_error
        return body


class FleetManifest:
    """Declarative agent roster: `<root>/.polyglav/fleet.json`."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.path = self.root / '.polyglav' / 'fleet.json'
        self._agents: dict[str, AgentDef] = {}
        self.load()

    def load(self):
        self._agents = {}
        if not self.path.exists():
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            for entry in (data.get('agents') or []):
                if isinstance(entry, dict) and entry.get('name'):
                    agent = AgentDef.from_dict(entry)
                    self._agents[agent.name] = agent
        except (OSError, ValueError):
            self._agents = {}

    def reload(self):
        self.load()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {'version': 1, 'agents': [a.to_dict() for a in self.all()]}
        tmp = self.path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(body, indent=2))
        os.replace(tmp, self.path)

    def all(self) -> list[AgentDef]:
        return sorted(self._agents.values(), key=lambda a: a.name)

    def names(self) -> list[str]:
        return sorted(self._agents)

    def find(self, name: str) -> AgentDef | None:
        return self._agents.get(name)

    def add(self, agent: AgentDef) -> None:
        self._agents[agent.name] = agent
        self.save()

    def remove(self, name: str) -> bool:
        if name not in self._agents:
            return False
        del self._agents[name]
        self.save()
        return True


class FleetState:
    """Runtime state: `<root>/.polyglav/fleet.state.json`."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.path = self.root / '.polyglav' / 'fleet.state.json'
        self.supervisor_pid = 0
        self.supervisor_started_at = ''
        self.agents: dict[str, AgentState] = {}
        self.load()

    def load(self):
        self.supervisor_pid = 0
        self.supervisor_started_at = ''
        self.agents = {}
        if not self.path.exists():
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            self.supervisor_pid = int(data.get('supervisor_pid', 0) or 0)
            self.supervisor_started_at = data.get('supervisor_started_at', '') or ''
            agents = data.get('agents') or {}
            for name, d in agents.items():
                if isinstance(d, dict):
                    self.agents[str(name)] = AgentState.from_dict(d)
        except (OSError, ValueError):
            self.supervisor_pid = 0
            self.agents = {}

    def reload(self):
        self.load()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            'supervisor_pid': self.supervisor_pid,
            'supervisor_started_at': self.supervisor_started_at,
            'agents': {name: st.to_dict() for name, st in sorted(self.agents.items())},
        }
        tmp = self.path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(body, indent=2))
        os.replace(tmp, self.path)


def _bind_probe(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def find_free_port(preferred: int = 0, lo: int = PORT_LO, hi: int = PORT_HI,
                   in_use: Iterable[int] = ()) -> int:
    used = set(in_use)
    if preferred and preferred not in used and _bind_probe(preferred):
        return preferred
    for port in range(lo, hi + 1):
        if port in used:
            continue
        if _bind_probe(port):
            return port
    raise ValueError(f'no free port in {lo}-{hi}')


def _os_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def probe_health(host: str, port: int, timeout: float = HEALTH_TIMEOUT
                 ) -> tuple[bool, float, str]:
    if port <= 0:
        return False, 0.0, 'no port assigned'
    start = time.monotonic()
    url = f'http://{host}:{port}/health'
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            ok = resp.status == 200
            elapsed = round(time.monotonic() - start, 2)
            return ok, elapsed, '' if ok else f'HTTP {resp.status}'
    except urllib.error.HTTPError as e:
        elapsed = round(time.monotonic() - start, 2)
        e.close()
        return False, elapsed, f'HTTP {e.code}'
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, round(time.monotonic() - start, 2), str(e)


class FleetController:
    """Supervise a fleet of scoped `polyglav serve` agents."""

    def __init__(self, root: str | Path, manifest: FleetManifest | None = None,
                 state: FleetState | None = None, tick: float = 2.0,
                 health_timeout: float = HEALTH_TIMEOUT,
                 unhealthy_threshold: int = UNHEALTHY_THRESHOLD,
                 backoff_start: float = BACKOFF_START,
                 backoff_max: float = BACKOFF_MAX):
        self.root = Path(root).resolve()
        self.manifest = manifest or FleetManifest(self.root)
        self.state = state or FleetState(self.root)
        self.tick = tick
        self.health_timeout = health_timeout
        self.unhealthy_threshold = unhealthy_threshold
        self.backoff_start = backoff_start
        self.backoff_max = backoff_max
        self._procs: dict[int, subprocess.Popen] = {}

    # ------- output helpers -------

    def _log(self, msg: str, error: bool = False):
        stream = sys.stderr if error else sys.stdout
        stream.write(f'[fleet] {msg}\n')
        stream.flush()

    # ------- process helpers -------

    def _alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        proc = self._procs.get(pid)
        if proc is not None:
            return proc.poll() is None
        return _os_alive(pid)

    def _reap(self, pid: int):
        proc = self._procs.pop(pid, None)
        if proc is not None:
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass

    def _signal(self, pid: int, sig: int):
        if pid <= 0 or not self._alive(pid):
            return
        try:
            os.kill(pid, sig)
        except OSError:
            pass

    # ------- agent helpers -------

    def agent_dir(self, agent: AgentDef) -> Path:
        base = Path(agent.dir) if agent.dir else self.root / agent.name
        return base.resolve()

    def log_path(self, agent: AgentDef) -> Path:
        return self.agent_dir(agent) / '.polyglav' / 'logs' / f'{agent.name}.log'

    def _command(self, agent: AgentDef, port: int) -> list[str]:
        if agent.command:
            return list(agent.command)
        cmd = [
            sys.executable, '-m', 'polyglav', 'serve',
            '--host', '127.0.0.1', '--port', str(port),
            '--path', str(self.agent_dir(agent)),
        ]
        token = _fleet_token()
        if token:
            cmd += ['--token', token]
        return cmd

    def spawn(self, agent: AgentDef, port: int) -> subprocess.Popen:
        agent_dir = self.agent_dir(agent)
        agent_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_path(agent)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(log_path, 'ab')
        try:
            env = dict(os.environ)
            env['POLYGLAV_FLEET_PORT'] = str(port)
            env['POLYGLAV_FLEET_DIR'] = str(agent_dir)
            env['POLYGLAV_FLEET_AGENT'] = agent.name
            proc = subprocess.Popen(
                self._command(agent, port),
                stdout=handle, stderr=subprocess.STDOUT,
                cwd=str(agent_dir), env=env,
                start_new_session=True,
            )
        finally:
            handle.close()
        self._procs[proc.pid] = proc
        return proc

    def _stop_proc(self, pid: int, sig: int = signal.SIGINT):
        self._signal(pid, sig)

    def _restart_delay(self, restarts: int) -> float:
        delay = self.backoff_start * (2 ** (max(1, restarts) - 1))
        return min(float(self.backoff_max), delay)

    # ------- lifecycle -------

    def _launch(self, agent: AgentDef, st: AgentState):
        used = {s.port for s in self.state.agents.values()
                if s is not st and s.port and s.pid and self._alive(s.pid)}
        try:
            port = find_free_port(preferred=agent.prefer_port or st.port or 0,
                                  in_use=used)
        except ValueError as e:
            st.status = CRASHED
            st.last_error = str(e)
            return
        try:
            proc = self.spawn(agent, port)
        except OSError as e:
            st.status = CRASHED
            st.last_error = f'spawn failed: {e}'
            return
        st.pid = proc.pid
        st.port = port
        st.status = STARTING
        st.started_at = _now()
        st.next_restart_at = ''
        st.last_error = ''

    def _fail(self, agent: AgentDef, st: AgentState, now: datetime, reason: str):
        if st.pid:
            self._stop_proc(st.pid)
            self._reap(st.pid)
            st.pid = 0
        st.restarts += 1
        st.consecutive_unhealthy = 0
        st.last_error = reason
        if agent.max_restarts and st.restarts > agent.max_restarts:
            st.status = CRASHED
            self._log(f'{agent.name}: {reason} - gave up after '
                      f'{st.restarts - 1} restart(s) (max_restarts '
                      f'{agent.max_restarts})', error=True)
            return
        delay = self._restart_delay(st.restarts)
        st.next_restart_at = (now + timedelta(seconds=delay)).isoformat(
            timespec='seconds')
        st.status = RESTARTING
        self._log(f'{agent.name}: {reason} - restarting in {delay:.0f}s '
                  f'(restart {st.restarts}/{agent.max_restarts or "unlimited"})',
                  error=True)

    def _sweep_agent(self, agent: AgentDef, st: AgentState, now: datetime):
        if not agent.enabled:
            if st.pid and self._alive(st.pid):
                self._stop_proc(st.pid)
                self._reap(st.pid)
                st.pid = 0
            if st.status not in (STOPPED, DISABLED, CRASHED):
                st.status = DISABLED
            return
        if st.status == CRASHED:
            return
        if st.pid and self._alive(st.pid):
            if st.status == STARTING:
                st.status = RUNNING
            ok, _, err = probe_health('127.0.0.1', st.port, self.health_timeout)
            if ok:
                st.status = HEALTHY
                st.consecutive_unhealthy = 0
                st.last_error = ''
            else:
                st.consecutive_unhealthy += 1
                st.status = UNHEALTHY
                if st.consecutive_unhealthy >= self.unhealthy_threshold:
                    self._fail(agent, st, now,
                               f'health check failed: {err or "no response"}')
            return
        if st.pid:
            st.pid = 0
            self._reap(st.pid)
        if st.status in _ACTIVE_STATES:
            self._fail(agent, st, now, 'process exited')
            return
        if st.status == RESTARTING and st.next_restart_at:
            if now < _parse_ts(st.next_restart_at):
                return
        elif st.status == RESTARTING:
            st.status = STOPPED
        self._launch(agent, st)

    def sweep(self):
        self.manifest.reload()
        self.state.reload()
        now = datetime.now(timezone.utc)
        names = set(self.manifest.names())
        for name in list(self.state.agents):
            if name not in names:
                del self.state.agents[name]
        if self.state.supervisor_pid != os.getpid():
            self.state.supervisor_pid = os.getpid()
            self.state.supervisor_started_at = _now()
        for agent in self.manifest.all():
            st = self.state.agents.setdefault(agent.name, AgentState())
            self._sweep_agent(agent, st, now)
        self.state.save()

    def run(self, stop_event: threading.Event | None = None, quiet: bool = False):
        if not quiet:
            self._log('supervisor started - Ctrl-C to stop agents gracefully')
        try:
            while True:
                try:
                    self.sweep()
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    self._log(f'supervisor sweep error: {e}', error=True)
                if stop_event is not None:
                    if stop_event.wait(self.tick):
                        break
                else:
                    try:
                        time.sleep(self.tick)
                    except KeyboardInterrupt:
                        raise
        except KeyboardInterrupt:
            pass
        finally:
            self.down()
        if not quiet:
            self._log('supervisor stopped')
        return 0

    def daemon(self, quiet: bool = True) -> int:
        stop = threading.Event()

        def _handler(signum, frame):
            stop.set()

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)
        return self.run(stop_event=stop, quiet=quiet)

    def stop_agent(self, name: str) -> bool:
        st = self.state.agents.get(name)
        if st is None:
            return False
        if st.pid and self._alive(st.pid):
            self._signal(st.pid, signal.SIGINT)
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and self._alive(st.pid):
                time.sleep(0.05)
            if self._alive(st.pid):
                self._signal(st.pid, signal.SIGKILL)
            self._reap(st.pid)
        st.pid = 0
        st.status = STOPPED
        st.next_restart_at = ''
        st.consecutive_unhealthy = 0
        self.state.save()
        return True

    def down(self, grace: float = 3.0):
        self.state.reload()
        sup = self.state.supervisor_pid
        if sup and sup != os.getpid() and _os_alive(sup):
            self._signal(sup, signal.SIGINT)
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline and _os_alive(sup):
                time.sleep(0.05)
        self.state.reload()
        targets = [st.pid for st in self.state.agents.values()
                   if st.pid and self._alive(st.pid)]
        for pid in targets:
            self._signal(pid, signal.SIGINT)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if not any(self._alive(pid) for pid in targets):
                break
            time.sleep(0.05)
        for pid in targets:
            if self._alive(pid):
                self._signal(pid, signal.SIGKILL)
            self._reap(pid)
        for st in self.state.agents.values():
            st.pid = 0
            st.status = STOPPED
            st.next_restart_at = ''
            st.consecutive_unhealthy = 0
        self.state.supervisor_pid = 0
        self.state.supervisor_started_at = ''
        self.state.save()

    def restart(self, names: list[str] | None = None) -> list[str]:
        self.manifest.reload()
        self.state.reload()
        want = set(names) if names is not None else None
        targets = [a for a in self.manifest.all()
                   if want is None or a.name in want]
        if want is not None and not targets:
            return []
        for agent in targets:
            self.stop_agent(agent.name)
            st = self.state.agents.setdefault(agent.name, AgentState())
            st.restarts = 0
            st.last_error = ''
        self.state.save()
        return [a.name for a in targets]

    def start_agent(self, agent: AgentDef, wait: float = 5.0) -> AgentState:
        st = self.state.agents.setdefault(agent.name, AgentState())
        if st.pid and self._alive(st.pid):
            return st
        self._launch(agent, st)
        self.state.save()
        deadline = time.monotonic() + max(0.0, wait)
        while time.monotonic() < deadline and st.pid:
            ok, _, _ = probe_health('127.0.0.1', st.port,
                                    self.health_timeout)
            if ok:
                st.status = HEALTHY
                self.state.save()
                return st
            if not self._alive(st.pid):
                break
            time.sleep(0.1)
        self.state.save()
        return st

    def ask_agent(self, name: str, prompt: str) -> str:
        agent = self.manifest.find(name)
        if agent is None:
            return f'Agent not found: {name}'
        st = self.state.agents.get(name)
        if st is None or not st.port:
            return f'Agent is not running: {name}'
        url = f'http://127.0.0.1:{st.port}/chat'
        payload = json.dumps({'prompt': prompt}).encode('utf-8')
        headers = {'Content-Type': 'application/json'}
        token = _fleet_token()
        if token:
            headers['Authorization'] = f'Bearer {token}'
        request = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=300) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except (urllib.error.URLError, OSError, ValueError) as e:
            return f'Agent request failed: {e}'
        return str(data.get('content') or data.get('status') or '')

    def status_rows(self) -> list[dict]:
        self.manifest.reload()
        self.state.reload()
        rows = []
        for agent in self.manifest.all():
            st = self.state.agents.get(agent.name, AgentState())
            alive = st.pid and self._alive(st.pid)
            rows.append({
                'name': agent.name,
                'enabled': agent.enabled,
                'port': st.port,
                'pid': st.pid if alive else 0,
                'state': st.status if alive else STOPPED,
                'restarts': st.restarts,
                'max_restarts': agent.max_restarts,
                'last_error': st.last_error,
            })
        return rows


def _fleet_root(args) -> Path:
    path = getattr(args, 'path', None)
    return (Path(path) if path else Path.cwd()).resolve()


def _fleet_controller(args) -> FleetController:
        return FleetController(_fleet_root(args))


def cmd_fleet(args) -> int:
    controller = _fleet_controller(args)
    action = getattr(args, 'action', None)

    if action == 'init':
        added = []
        for entry in sorted(controller.root.iterdir()):
            if not entry.is_dir():
                continue
            if (entry / '.polyglav' / 'config.json').exists():
                if controller.manifest.find(entry.name) is None:
                    controller.manifest.add(AgentDef(
                        name=entry.name, dir=str(entry.resolve()), added_at=_now()))
                    added.append(entry.name)
        if added:
            print(f'Discovered {len(added)} agent(s): {", ".join(added)}')
        else:
            print('No new agents found (subdirectories holding .polyglav/config.json)')
        return 0

    if action == 'add':
        if controller.manifest.find(args.name) is not None:
            print(f'Agent already exists: {args.name}', file=sys.stderr)
            return 1
        agent_dir = (Path(args.dir).resolve() if getattr(args, 'dir', '')
                     else (controller.root / args.name).resolve())
        controller.manifest.add(AgentDef(
            name=args.name, dir=str(agent_dir),
            prefer_port=int(getattr(args, 'port', 0) or 0),
            max_restarts=int(getattr(args, 'max_restarts', 10) or 0),
            added_at=_now()))
        print(f'Added agent: {args.name} -> {agent_dir}')
        print('  Run `polyglav fleet config <name>` to generate its config, '
              'then `polyglav fleet up` to start it')
        return 0

    if action == 'remove':
        if controller.manifest.find(args.name) is None:
            print(f'Agent not found: {args.name}', file=sys.stderr)
            return 1
        controller.stop_agent(args.name)
        controller.manifest.remove(args.name)
        print(f'Removed agent: {args.name}')
        return 0

    if action == 'up':
        if getattr(args, 'daemon_', False):
            return controller.daemon()
        if getattr(args, 'detach', False):
            return _fleet_detach(controller)
        return controller.run()

    if action == 'down':
        controller.down()
        print(f'Fleet stopped ({controller.root})')
        return 0

    if action == 'status':
        return _fleet_status(controller)

    if action == 'restart':
        names = [args.name] if getattr(args, 'name', None) else None
        if names and controller.manifest.find(names[0]) is None:
            print(f'Agent not found: {names[0]}', file=sys.stderr)
            return 1
        restarted = controller.restart(names)
        label = ', '.join(restarted) if restarted else '(none running)'
        print(f'Stopped for restart: {label}')
        if restarted:
            print('  Agents relaunch on the next supervisor sweep '
                  '(or run `polyglav fleet up`)')
        return 0

    if action == 'logs':
        return _fleet_logs(controller, args)

    if action == 'config':
        return _fleet_config(controller, args)

    print('Usage: polyglav fleet '
          '[init|add|remove|up|down|status|restart|logs|config]')
    return 1


def _fleet_detach(controller) -> int:
    import subprocess
    log_dir = controller.root / '.polyglav' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / 'fleet.log'
    handle = open(log_path, 'ab')
    cmd = [sys.executable, '-m', 'polyglav', 'fleet', '--path', str(controller.root),
           'up', '--daemon']
    try:
        proc = subprocess.Popen(cmd, stdout=handle, stderr=subprocess.STDOUT,
                                cwd=str(controller.root), start_new_session=True)
    finally:
        handle.close()
    print(f'Fleet supervisor detached (pid {proc.pid}, log {log_path})')
    return 0


def _fleet_status(controller) -> int:
    rows = controller.status_rows()
    if not rows:
        print(f'No agents in the manifest ({controller.root}) - '
              'run `polyglav fleet init` or `polyglav fleet add`')
        return 0
    headers = ('AGENT', 'ENABLED', 'PORT', 'PID', 'STATE', 'RESTARTS', 'LAST ERROR')
    cells = []
    for r in rows:
        budget = f"{r['max_restarts']}" if r['max_restarts'] else 'unlim'
        cells.append([
            r['name'],
            'yes' if r['enabled'] else 'no',
            str(r['port'] or '-'),
            str(r['pid'] or '-'),
            r['state'],
            f"{r['restarts']}/{budget}",
            r['last_error'] or '',
        ])
    widths = [len(h) for h in headers]
    for c in cells:
        for i, value in enumerate(c):
            widths[i] = max(widths[i], len(value))
    fmt = '  '.join('{:<%d}' % w for w in widths)
    print(fmt.format(*headers))
    for c in cells:
        print(fmt.format(*c))
    return 0


def _fleet_logs(controller, args) -> int:
    import time
    agent = controller.manifest.find(args.name)
    if agent is None:
        print(f'Agent not found: {args.name}', file=sys.stderr)
        return 1
    log_path = controller.log_path(agent)
    if not log_path.exists():
        print(f'No log yet: {log_path}', file=sys.stderr)
        return 1
    n = max(1, int(getattr(args, 'n', 50) or 50))
    if getattr(args, 'follow', False):
        size = log_path.stat().st_size
        with open(log_path) as f:
            f.seek(size)
            try:
                while True:
                    line = f.readline()
                    if line:
                        print(line, end='')
                    else:
                        time.sleep(0.25)
            except KeyboardInterrupt:
                pass
        return 0
    lines = log_path.read_text().splitlines()
    if not lines:
        print(f'(empty log) {log_path}')
        return 0
    for line in lines[-n:]:
        print(line)
    return 0


def _fleet_config(controller, args) -> int:
    import json
    from polyglav.config import Config
    from polyglav.plugins.manager import PluginManager
    agent = controller.manifest.find(args.name)
    if agent is None:
        print(f'Agent not found: {args.name}', file=sys.stderr)
        return 1
    agent_dir = controller.agent_dir(agent)
    patch: dict = {}
    if getattr(args, 'provider', ''):
        patch['provider'] = args.provider
    if getattr(args, 'model', ''):
        patch['model'] = args.model
    if getattr(args, 'system_prompt', ''):
        patch['system_prompt'] = args.system_prompt
    if getattr(args, 'mode', ''):
        patch['mode'] = args.mode
    deny = list(getattr(args, 'tools_deny', []) or [])
    if deny:
        patch['tools.deny'] = deny
    perms: dict = {}
    for pair in (getattr(args, 'tool_permission', []) or []):
        if '=' not in pair:
            print(f'Invalid --tool-permission "{pair}" (want category=action)',
                  file=sys.stderr)
            return 1
        category, _, action = pair.partition('=')
        perms[category.strip()] = action.strip()
    role_name = getattr(args, 'role', '') or ''
    agent_role = None
    if role_name:
        pm = PluginManager(Config(path=str(agent_dir)))
        pm.load()
        factory = pm.service('role_registry')
        registry = (factory(local_path=agent_dir / '.polyglav' / 'roles.json')
                    if factory is not None else None)
        if registry is None:
            print('Role registry plugin is not loaded', file=sys.stderr)
            return 1
        agent_role = registry.find(role_name)
        if agent_role is None:
            print(f'Unknown role: {role_name}', file=sys.stderr)
            return 1
        if agent_role.system_prompt and 'system_prompt' not in patch:
            patch['system_prompt'] = agent_role.system_prompt
        if agent_role.model and 'model' not in patch:
            patch['model'] = agent_role.model
        for key, value in agent_role.tool_permission.items():
            perms.setdefault(key, value)
    if perms:
        patch['tool_permission'] = perms
    if not patch:
        print('Nothing to set - give at least one of --provider/--model/'
              '--role/--system-prompt/--mode/--tools-deny/--tool-permission',
              file=sys.stderr)
        return 1
    target = agent_dir / '.polyglav' / 'config.json'
    existing: dict = {}
    if target.exists():
        try:
            existing = json.loads(target.read_text())
        except (OSError, ValueError):
            existing = {}
    if getattr(args, 'approve_model', False) or getattr(args, 'model', ''):
        from polyglav.config import Config
        from polyglav.models import ModelRegistry
        from polyglav.providers import merged_providers
        from polyglav.providers.registry import resolve_model_ref
        model_target = getattr(args, 'model', '') or (agent_role.model if agent_role else '')
        if model_target:
            model_registry = ModelRegistry()
            model_provider = patch.get('provider') or existing.get('provider') or ''
            ref = resolve_model_ref(
                model_target, merged_providers(Config(path=str(agent_dir))))
            if ref:
                model_provider, _, model_target = ref
            if model_provider and model_target:
                model_registry.put(model_provider, model_target)
    existing.update(patch)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(existing, indent=2))
    print(f'Updated {target}')
    for key, value in patch.items():
        shown = value
        if key == 'system_prompt' and len(str(value)) > 60:
            shown = str(value)[:60] + '...'
        print(f'  {key} = {shown}')
    return 0

def _run(args):
    return cmd_fleet(args)


def register_commands(commands):
    import shlex
    chat = commands.chat_loop

    @commands.register(
        'spawn',
        description='Launch, list, stop, or ask a scoped serve agent',
        subcommands=[
            ('', 'List supervised agents'),
            ('<name> <path>', 'Launch an agent for a project path'),
            ('ask <name> <prompt>', 'Ask a running agent'),
            ('stop <name>', 'Stop an agent'),
        ])
    def spawn_cmd(arg=''):
        root = chat.config.local_path.parent.parent
        controller = FleetController(root)
        text = arg.strip()
        if not text or text in ('list', 'status'):
            rows = controller.status_rows()
            if not rows:
                print('  (no agents)')
                return
            for row in rows:
                print(f"  {row['name']}  {row['state']}  "
                      f"port={row['port'] or '-'}  pid={row['pid'] or '-'}")
            return
        tokens = shlex.split(text)
        action = tokens[0]
        if action == 'stop':
            name = tokens[1] if len(tokens) > 1 else ''
            if not name:
                print('Usage: /spawn stop <name>')
                return
            if controller.stop_agent(name):
                print(f'Stopped agent: {name}')
            else:
                print(f'Agent not found: {name}')
            return
        if action == 'ask':
            name = tokens[1] if len(tokens) > 1 else ''
            prompt = ' '.join(tokens[2:]).strip()
            if not name or not prompt:
                print('Usage: /spawn ask <name> <prompt>')
                return
            print(controller.ask_agent(name, prompt))
            return
        path_text = tokens[1] if len(tokens) > 1 else tokens[0]
        name = tokens[0] if len(tokens) > 1 else Path(path_text).name
        path = Path(path_text).expanduser()
        if not path.is_absolute():
            path = (root / path).resolve()
        agent = controller.manifest.find(name)
        if agent is None:
            agent = AgentDef(name=name, dir=str(path), added_at=_now())
            controller.manifest.add(agent)
        else:
            agent.dir = str(path)
            controller.manifest.add(agent)
        state = controller.start_agent(agent)
        print(f"Spawned {name}: {state.status} on port {state.port or '-'}")


def register_cli(cli):
    import argparse
    p = cli.add_parser(
        'fleet',
        help='Supervise a fleet of scoped polyglav serve agents '
             '(ports, health checks, restart policy, config generation)')
    p.add_argument('--path', default=argparse.SUPPRESS,
                   help='Fleet root (default: current directory)')
    g = p.add_subparsers(dest='action', required=True)
    g.add_parser('init', help='Scan subdirectories holding .polyglav/config.json '
                 'into the fleet manifest')
    ga = g.add_parser('add', help='Add an agent to the manifest')
    ga.add_argument('name')
    ga.add_argument('--dir', help='Agent directory (default: <root>/<name>)')
    ga.add_argument('--port', type=int, default=0,
                    help='Preferred port (0 = auto-allocate)')
    ga.add_argument('--max-restarts', type=int, default=10,
                    help='Restart budget before the supervisor pauses the agent '
                         '(0 = unlimited)')
    grm = g.add_parser('remove', help='Remove an agent from the manifest (stops it)')
    grm.add_argument('name')
    gu = g.add_parser('up', help='Start agents (Ctrl-C = graceful down)')
    gu.add_argument('--detach', action='store_true',
                    help='Run the supervisor as a background daemon')
    gu.add_argument('--daemon', dest='daemon_', action='store_true',
                    help=argparse.SUPPRESS)
    g.add_parser('down', help='Stop the supervised agents and the daemon if running')
    g.add_parser('status', help='Live status table of the fleet')
    gr = g.add_parser('restart', help='Stop and relaunch agents, resetting backoff')
    gr.add_argument('name', nargs='?', help='Agent name (default: all)')
    gl = g.add_parser('logs', help='Show an agent log (tail)')
    gl.add_argument('name')
    gl.add_argument('n', nargs='?', type=int, default=50,
                    help='Last N lines (default: 50)')
    gl.add_argument('--follow', '-f', action='store_true',
                    help='Keep watching appended output (Ctrl-C to stop)')
    gc = g.add_parser('config', help='Write selected keys into <agent>/.polyglav/config.json')
    gc.add_argument('name')
    gc.add_argument('--provider', help='Provider override')
    gc.add_argument('--model', help='Model override')
    gc.add_argument('--role', help='Inline a role prompt, model, and permissions')
    gc.add_argument('--system-prompt', help='System prompt override')
    gc.add_argument('--mode', help='Agent mode override (read or write)')
    gc.add_argument('--tools-deny', action='append', default=[],
                    help='Tool name to deny (repeatable)')
    gc.add_argument('--tool-permission', action='append', default=[],
                    help='category=action override (repeatable), e.g. bash=allow')
    gc.add_argument('--approve-model', action='store_true',
                    help='Approve the model referenced by --role or --model '
                         'in the global models registry')
    p.set_defaults(func=_run)
