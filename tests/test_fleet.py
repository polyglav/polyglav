import io
import json
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from polyglav.config import Config
from polyglav.fleet import (AgentDef, AgentState, FleetController, FleetManifest, FleetState, find_free_port, probe_health)
from polyglav.cli import cmd_fleet

MOCK_HEALTHY = r'''
import os, signal, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
port = int(os.environ['POLYGLAV_FLEET_PORT'])
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.path == '/health'
        b = b'{"status":"ok"}' if ok else b''
        self.send_response(200 if ok else 404)
        self.send_header('Content-Length', str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
print('mock started', flush=True)
def stop(sig, frm): sys.exit(0)
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
HTTPServer(('127.0.0.1', port), H).serve_forever()
'''

MOCK_DOWN = r'''
import os, signal, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
port = int(os.environ['POLYGLAV_FLEET_PORT'])
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        b = b'{"status":"down"}'
        self.send_response(503)
        self.send_header('Content-Length', str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
def stop(sig, frm): sys.exit(0)
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
HTTPServer(('127.0.0.1', port), H).serve_forever()
'''

CRASH_SCRIPT = 'import sys\nsys.exit(3)\n'


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        b = b'{"status":"ok"}' if self.path == '/health' else b''
        self.send_response(200 if self.path == '/health' else 404)
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, fmt, *args):
        pass


def _make_controller(root, **kw):
    return FleetController(root, backoff_start=0.0, backoff_max=0.0, tick=0.05, health_timeout=1.0, unhealthy_threshold=2, **kw)


class TestPortAllocation(unittest.TestCase):

    def _bind(self, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', port))
        return s

    def test_preferred_free_returns_it(self):
        left, right = 16080, 16099
        port = find_free_port(preferred=left, lo=left, hi=right)
        self.assertEqual(port, left)

    def test_preferred_occupied_falls_back_to_scan(self):
        sock = self._bind(16100)
        try:
            port = find_free_port(preferred=16100, lo=16100, hi=16110)
        finally:
            sock.close()
        self.assertEqual(port, 16101)

    def test_in_use_skipped(self):
        port = find_free_port(preferred=0, lo=16120, hi=16130, in_use=[16120])
        self.assertEqual(port, 16121)

    def test_exhaustion_raises(self):
        sock = self._bind(16190)
        try:
            with self.assertRaises(ValueError):
                find_free_port(preferred=0, lo=16190, hi=16190)
        finally:
            sock.close()


class TestHealthProbe(unittest.TestCase):

    def test_probe_ok_and_failure(self):
        server = HTTPServer(('127.0.0.1', 0), _HealthHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            ok, elapsed, err = probe_health('127.0.0.1', port, timeout=1.0)
            self.assertTrue(ok)
            self.assertEqual(err, '')
            self.assertGreaterEqual(elapsed, 0)
        finally:
            server.shutdown()
            server.server_close()
        ok2, _, err2 = probe_health('127.0.0.1', port, timeout=1.0)
        self.assertFalse(ok2)
        self.assertTrue(err2)

    def test_probe_no_port(self):
        ok, _, err = probe_health('127.0.0.1', 0, timeout=1.0)
        self.assertFalse(ok)
        self.assertIn('port', err)


class TestManifestAndState(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_manifest_round_trip(self):
        m = FleetManifest(self.root)
        m.add(AgentDef(name='a', dir=str(self.root / 'a'), prefer_port=8780, max_restarts=5))
        m.save()
        m2 = FleetManifest(self.root)
        self.assertEqual(m2.names(), ['a'])
        agent = m2.find('a')
        self.assertEqual(agent.dir, str(self.root / 'a'))
        self.assertEqual(agent.prefer_port, 8780)
        self.assertEqual(agent.max_restarts, 5)
        self.assertTrue(m2.remove('a'))
        self.assertEqual(FleetManifest(self.root).names(), [])

    def test_manifest_corrupt_tolerated(self):
        (self.root / '.polyglav').mkdir(parents=True)
        (self.root / '.polyglav' / 'fleet.json').write_text('{not json')
        m = FleetManifest(self.root)
        self.assertEqual(m.names(), [])

    def test_state_round_trip(self):
        s = FleetState(self.root)
        s.supervisor_pid = 42
        s.agents['x'] = AgentState(status='healthy', pid=7, port=8780, restarts=2, last_error='boom')
        s.save()
        s2 = FleetState(self.root)
        self.assertEqual(s2.supervisor_pid, 42)
        st = s2.agents['x']
        self.assertEqual((st.status, st.pid, st.port, st.restarts,
                          st.last_error), ('healthy', 7, 8780, 2, 'boom'))


class TestControllerLifecycle(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._made = []

    def tearDown(self):
        for ctrl in self._made:
            try:
                ctrl.down(grace=1.0)
            except Exception:
                pass
        self.tmp.cleanup()

    def _ctrl(self, **kw):
        if self._made:
            return self._made[0]
        ctrl = _make_controller(self.root, **kw)
        self._made.append(ctrl)
        return ctrl

    def _add(self, name, script=MOCK_HEALTHY, **kw):
        cmd = [sys.executable, '-c', script]
        defaults = dict(name=name, dir=str(self.root / name), command=cmd)
        defaults.update(kw)
        agent = AgentDef(**defaults)
        self._ctrl().manifest.add(agent)
        return agent

    def _wait_healthy(self, ctrl, name, timeout=15.0):
        st = ctrl.state.agents[name]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if st.status == 'healthy':
                return st
            time.sleep(1.0)
            ctrl.sweep()
            st = ctrl.state.agents[name]
        return st

    def _healthy(self):
        ctrl = self._ctrl()
        self._add('alpha')
        ctrl.sweep()
        st = self._wait_healthy(ctrl, 'alpha')
        self.assertEqual(st.status, 'healthy')
        self.assertGreater(st.pid, 0)
        self.assertGreater(st.port, 0)
        return st

    def test_launch_health_restart_down_cycle(self):
        ctrl = self._ctrl()
        st = self._healthy()
        self.assertTrue(ctrl._alive(st.pid))

        ctrl._signal(st.pid, signal.SIGINT)
        time.sleep(0.4)
        ctrl.sweep()
        st = ctrl.state.agents['alpha']
        self.assertEqual(st.status, 'restarting')
        self.assertEqual(st.restarts, 1)

        time.sleep(0.1)
        ctrl.sweep()
        st = ctrl.state.agents['alpha']
        self.assertEqual(st.restarts, 1)

        st.next_restart_at = ''
        ctrl.state.save()
        ctrl.sweep()
        st = self._wait_healthy(ctrl, 'alpha')
        self.assertEqual(st.status, 'healthy')
        self.assertGreater(st.pid, 0)

        ctrl.down(grace=1.0)
        self.assertEqual(ctrl.state.agents['alpha'].status, 'stopped')

    def test_unhealthy_threshold_triggers_restart(self):
        ctrl = self._ctrl()
        self._add('alpha', script=MOCK_DOWN)
        ctrl.sweep()
        time.sleep(0.6)
        for _ in range(20):
            ctrl.sweep()
            time.sleep(0.1)
            st = ctrl.state.agents['alpha']
            if st.restarts >= 1:
                break
        self.assertEqual(st.status, 'restarting')
        self.assertGreaterEqual(st.restarts, 1)
        self.assertIn('health', st.last_error)

    def test_max_restarts_gives_up(self):
        ctrl = self._ctrl()
        self._add('alpha', script=CRASH_SCRIPT, max_restarts=2)
        for _ in range(12):
            ctrl.sweep()
            time.sleep(0.05)
        st = ctrl.state.agents['alpha']
        self.assertEqual(st.status, 'crashed')
        self.assertEqual(st.restarts, 3)

    def test_restart_resets_and_relaunches(self):
        ctrl = self._ctrl()
        st = self._healthy()
        ctrl.restart(['alpha'])
        st = ctrl.state.agents['alpha']
        self.assertEqual(st.status, 'stopped')
        self.assertEqual(st.restarts, 0)
        st = self._wait_healthy(ctrl, 'alpha')
        self.assertEqual(st.status, 'healthy')

    def test_disabled_agent_not_supervised(self):
        ctrl = self._ctrl()
        self._add('alpha')
        ctrl.sweep()
        st = self._wait_healthy(ctrl, 'alpha')
        self.assertEqual(st.status, 'healthy')
        ctrl.manifest.find('alpha').enabled = False
        ctrl.manifest.save()
        time.sleep(0.2)
        ctrl.sweep()
        st = ctrl.state.agents['alpha']
        self.assertEqual(st.status, 'disabled')
        self.assertEqual(st.pid, 0)

    def test_log_file_written(self):
        ctrl = self._ctrl()
        self._healthy()
        log = ctrl.log_path(ctrl.manifest.find('alpha'))
        self.assertTrue(log.exists())
        self.assertIn('mock started', log.read_text())

    def test_spawn_env_seams(self):
        ctrl = self._ctrl()
        script = ('import os, signal, sys, time\n'
                  'print(os.environ["POLYGLAV_FLEET_PORT"], flush=True)\n'
                  'signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))\n'
                  'signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))\n'
                  'time.sleep(60)\n')
        agent = self._add('encoder', script=script)
        port = find_free_port(preferred=0, lo=18180, hi=18199)
        agent.command = [sys.executable, '-c', script]
        proc = ctrl.spawn(agent, port)
        log = ctrl.log_path(agent)
        for _ in range(40):
            if log.exists() and str(port) in log.read_text():
                break
            time.sleep(0.1)
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=3)
        content = log.read_text() if log.exists() else ''
        self.assertEqual(content.strip(), str(port))


class TestFleetCli(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        Config.GLOBAL_DIR = Path(self.tmp.name) / 'global-home'
        self._controllers = []

    def tearDown(self):
        Config.GLOBAL_DIR = None
        self.tmp.cleanup()

    def _ctrl(self):
        ctrl = FleetController(self.root, backoff_start=0.0, backoff_max=0.0, tick=0.05, health_timeout=1.0, unhealthy_threshold=2)
        self._controllers.append(ctrl)
        return ctrl

    def _args(self, **kw):
        base = dict(path=str(self.root))
        base.update(kw)
        return SimpleNamespace(**base)

    def _capture(self, args):
        out = io.StringIO()
        err = io.StringIO()
        with patch('sys.stdout', new=out), patch('sys.stderr', new=err):
            rc = cmd_fleet(args)
        return rc, out.getvalue(), err.getvalue()

    def test_init_discovers_config_dirs(self):
        for name in ('alpha', 'beta'):
            (self.root / name / '.polyglav').mkdir(parents=True)
            (self.root / name / '.polyglav' / 'config.json').write_text('{}')
        (self.root / 'plain').mkdir()
        rc, out, _ = self._capture(self._args(action='init'))
        self.assertEqual(rc, 0)
        self.assertIn('alpha', out)
        m = FleetManifest(self.root)
        self.assertEqual(m.names(), ['alpha', 'beta'])
        self.assertEqual(m.find('alpha').dir, str((self.root / 'alpha').resolve()))

    def test_add_remove(self):
        rc, _, _ = self._capture(self._args(action='add', name='alpha', dir=str(self.root / 'alpha'), port=0, max_restarts=10))
        self.assertEqual(rc, 0)
        rc, out, _ = self._capture(self._args(action='status'))
        self.assertEqual(rc, 0)
        self.assertIn('alpha', out)
        rc, _, _ = self._capture(self._args(action='remove', name='alpha'))
        self.assertEqual(rc, 0)
        self.assertIsNone(FleetManifest(self.root).find('alpha'))

    def test_config_writes_selected_keys(self):
        ctrl = self._ctrl()
        ctrl.manifest.add(AgentDef(name='alpha',
                                   dir=str(self.root / 'alpha')))
        rc, out, _ = self._capture(self._args(
            action='config', name='alpha', provider='ollama', model='m1',
            system_prompt='hello', mode='plan', tools_deny=['run_command'],
            tool_permission=['bash=deny', 'web=allow'], role=''))
        self.assertEqual(rc, 0)
        target = self.root / 'alpha' / '.polyglav' / 'config.json'
        data = json.loads(target.read_text())
        self.assertEqual(data['provider'], 'ollama')
        self.assertEqual(data['model'], 'm1')
        self.assertEqual(data['system_prompt'], 'hello')
        self.assertEqual(data['mode'], 'plan')
        self.assertEqual(data['tools.deny'], ['run_command'])
        self.assertEqual(data['tool_permission'],
                         {'bash': 'deny', 'web': 'allow'})
        self.assertIn('Updated', out)

    def test_config_type_inlined(self):
        ctrl = self._ctrl()
        ctrl.manifest.add(AgentDef(name='alpha', dir=str(self.root / 'alpha')))
        lp = self.root / 'alpha' / '.polyglav' / 'roles.json'
        lp.parent.mkdir(parents=True)
        lp.write_text(json.dumps({
            'archivist': {
                'system_prompt': 'You organise notes.',
                'model': 'tiny-model',
                'tool_permission': {'bash': 'deny'}},
        }))
        rc, _, _ = self._capture(self._args(
            action='config', name='alpha', provider='', model='',
            system_prompt='', mode='', tools_deny=[], tool_permission=[],
            role='archivist'))
        self.assertEqual(rc, 0)
        data = json.loads((self.root / 'alpha' / '.polyglav' / 'config.json').read_text())
        self.assertEqual(data['system_prompt'], 'You organise notes.')
        self.assertEqual(data['model'], 'tiny-model')
        self.assertEqual(data['tool_permission']['bash'], 'deny')

    def test_config_unknown_type_errors(self):
        ctrl = self._ctrl()
        ctrl.manifest.add(AgentDef(name='alpha',
                                   dir=str(self.root / 'alpha')))
        rc, _, err = self._capture(self._args(
            action='config', name='alpha', provider='', model='',
            system_prompt='', mode='', tools_deny=[], tool_permission=[],
            role='nosuch'))
        self.assertEqual(rc, 1)
        self.assertIn('Unknown role: nosuch', err)

    def test_config_nothing_to_set_errors(self):
        ctrl = self._ctrl()
        ctrl.manifest.add(AgentDef(name='alpha', dir=str(self.root / 'alpha')))
        rc, _, err = self._capture(self._args(
            action='config', name='alpha', provider='', model='',
            system_prompt='', mode='', tools_deny=[], tool_permission=[],
            role=''))
        self.assertEqual(rc, 1)
        self.assertIn('Nothing to set', err)

    def test_restart_missing_agent_errors(self):
        ctrl = self._ctrl()
        rc, _, err = self._capture(self._args(action='restart', name='nosuch'))
        self.assertEqual(rc, 1)
        self.assertIn('nosuch', err)

    def test_status_guided_when_empty(self):
        rc, out, _ = self._capture(self._args(action='status'))
        self.assertEqual(rc, 0)
        self.assertIn('No agents', out)


class TestDetachedSupervisor(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        ctrl = FleetController(self.root)
        ctrl.manifest.add(AgentDef(name='beta', dir=str(self.root / 'beta'), command=[sys.executable, '-c', MOCK_HEALTHY]))

    def tearDown(self):
        try:
            subprocess.run(
                [sys.executable, '-m', 'polyglav', 'fleet', '--path',
                 str(self.root), 'down'],
                capture_output=True, timeout=30)
        except subprocess.SubprocessError:
            pass
        self.tmp.cleanup()

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, '-m', 'polyglav', 'fleet', '--path', str(self.root),
             *args],
            capture_output=True, text=True, timeout=40)

    def _state(self) -> dict:
        return json.loads((self.root / '.polyglav' / 'fleet.state.json').read_text())

    def test_detach_daemon_status_down(self):
        r = self._run('up', '--detach')
        self.assertEqual(r.returncode, 0)
        state = {}
        for _ in range(20):
            time.sleep(0.5)
            if (self.root / '.polyglav' / 'fleet.state.json').exists():
                state = self._state()
                if state['agents']['beta']['status'] == 'healthy':
                    break
        self.assertEqual(state['agents']['beta']['status'], 'healthy')
        self.assertGreater(state['supervisor_pid'], 0)

        r = self._run('status')
        self.assertIn('beta', r.stdout)
        self.assertIn('healthy', r.stdout)

        r = self._run('down')
        self.assertEqual(r.returncode, 0)
        time.sleep(0.5)
        state = self._state()
        self.assertEqual(state['supervisor_pid'], 0)
        self.assertEqual(state['agents']['beta']['status'], 'stopped')


if __name__ == '__main__':
    unittest.main()
