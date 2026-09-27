from __future__ import annotations

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
        return [
            sys.executable, '-m', 'polyglav', 'serve',
            '--host', '127.0.0.1', '--port', str(port),
            '--path', str(self.agent_dir(agent)),
        ]

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