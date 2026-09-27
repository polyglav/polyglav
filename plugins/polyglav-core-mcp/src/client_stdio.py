import json
import os
import subprocess
import sys
import threading

import jsonrpc

DEFAULT_TIMEOUT = 60.0


class TransportError(Exception):
    pass


class StdioTransport:
    def __init__(self, command: str, args: list[str] | None = None,
                 cwd: str | None = None, env: dict | None = None,
                 timeout: float = DEFAULT_TIMEOUT,
                 notify=None, log=None):
        self.command = command
        self.args = list(args or [])
        self.cwd = cwd
        self.env = env
        self.timeout = timeout
        self._notify = notify
        self._log = log
        self._proc = None
        self._pending: dict = {}
        self._lock = threading.Lock()
        self._closed = False
        self._next_id = 0

    def _info(self, text: str):
        if self._log is not None:
            self._log(text)

    def start(self):
        env = os.environ.copy()
        if self.env:
            env.update({str(k): str(v) for k, v in self.env.items()})
        try:
            self._proc = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                env=env,
                bufsize=1,
                text=True,
                encoding='utf-8',
                errors='replace',
            )
        except (OSError, ValueError) as e:
            raise TransportError(f'failed to start MCP server {self.command}: {e}')

        reader = threading.Thread(target=self._read_loop, name='mcp-stdio-reader', daemon=True)
        reader.start()
        err_reader = threading.Thread(target=self._err_loop, name='mcp-stdio-stderr', daemon=True)
        err_reader.start()

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _read_loop(self):
        for line in self._proc.stdout:
            if self._closed:
                break
            msg = jsonrpc.parse_line(line)
            if msg is None:
                continue
            rid = msg.get('id')
            if 'error' in msg or 'result' in msg:
                pending = None
                with self._lock:
                    pending = self._pending.pop(rid, None)
                if pending is not None:
                    event, slot = pending
                    slot['message'] = msg
                    event.set()
                continue
            if self._notify is not None:
                try:
                    self._notify(msg)
                except Exception:
                    pass

    def _err_loop(self):
        for line in self._proc.stderr:
            if self._closed:
                break
            self._info(f'[{self.command} stderr] {line.rstrip()}')

    def _write(self, msg: dict):
        if self._proc is None or not self.alive:
            raise TransportError('MCP server process is not running')
        try:
            self._proc.stdin.write(jsonrpc.encode_message(msg) + '\n')
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise TransportError(f'MCP server pipe closed: {e}')

    def request(self, method: str, params: dict | None = None,
                timeout: float | None = None) -> dict:
        with self._lock:
            self._next_id += 1
            rid = self._next_id
        event = threading.Event()
        slot: dict = {}
        with self._lock:
            self._pending[rid] = (event, slot)
        try:
            self._write(jsonrpc.make_request(rid, method, params))
        except TransportError:
            with self._lock:
                self._pending.pop(rid, None)
            raise
        limit = self.timeout if timeout is None else timeout
        if not event.wait(limit):
            with self._lock:
                self._pending.pop(rid, None)
            self.notify_cancel(rid)
            raise TransportError(f'MCP request {method} timed out after {limit:.0f}s')
        message = slot['message']
        if 'error' in message:
            err = message['error']
            raise jsonrpc.MCPError(err.get('code', 0), err.get('message', 'MCP error'),
                                   err.get('data'))
        return message.get('result') or {}

    def notify(self, method: str, params: dict | None = None):
        self._write(jsonrpc.make_notification(method, params))

    def notify_cancel(self, request_id):
        try:
            self._write(jsonrpc.make_notification(
                'notifications/cancelled',
                {'requestId': request_id, 'reason': 'cancelled by client timeout'},
            ))
        except TransportError:
            pass

    def close(self):
        if self._closed or self._proc is None:
            return
        self._closed = True
        try:
            self._proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        for stream in (self._proc.stdout, self._proc.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except (OSError, ValueError):
                pass


def run_stdio_server(script: str, args: list[str] | None = None,
                     cwd: str | None = None, env: dict | None = None,
                     timeout: float = DEFAULT_TIMEOUT,
                     notify=None, log=None) -> StdioTransport:
    cmd = [sys.executable, '-c', script] + list(args or [])
    return StdioTransport(cmd[0], cmd[1:], cwd=cwd, env=env, timeout=timeout,
                          notify=notify, log=log)
