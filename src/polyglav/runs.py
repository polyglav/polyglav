from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@dataclass
class Run:
    id: int
    role: str
    session: str
    parent: int | None = None
    task: str = ''
    status: str = 'running'
    children: list[int] = field(default_factory=list)
    started_at: str = field(default_factory=_now)
    ended_at: str = ''
    buffer: list[str] = field(default_factory=list)
    session_id: str = ''
    max_buffer_lines: int = 0
    buffer_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False)

    def append_buffer(self, line: str) -> None:
        with self.buffer_lock:
            if line == '' and not self.buffer:
                return
            self.buffer.append(line)
            cap = self.max_buffer_lines
            if cap and len(self.buffer) > cap:
                del self.buffer[:len(self.buffer) - cap]

    def buffer_text(self) -> str:
        with self.buffer_lock:
            return '\n'.join(self.buffer)

    def clear_buffer(self) -> None:
        with self.buffer_lock:
            self.buffer.clear()


class RunRegistry:
    def __init__(self):
        self._runs: dict[int, Run] = {}
        self._order: list[int] = []
        self._engines: dict[int, object] = {}
        self._next_id = 1

    def start(self, role: str, session: str, parent: int | None = None,
              task: str = '', session_id: str = '') -> Run:
        run = Run(id=self._next_id, role=role, session=session,
                  parent=parent, task=task, session_id=session_id or '')
        self._next_id += 1
        self._runs[run.id] = run
        self._order.append(run.id)
        parent_run = self._runs.get(parent) if parent is not None else None
        if parent_run is not None:
            parent_run.children.append(run.id)
        return run

    def get(self, run_id: int) -> Run | None:
        return self._runs.get(run_id)

    def find_by_session_id(self, session_id: str) -> Run | None:
        session_id = (session_id or '').strip().lower()
        if not session_id:
            return None
        for run_id in self._order:
            run = self._runs[run_id]
            if (run.session_id or '').lower() == session_id:
                return run
        return None

    def finish(self, run_id: int, status: str = 'done') -> Run | None:
        run = self._runs.get(run_id)
        if run is None or run.status != 'running':
            return run
        run.status = status
        run.ended_at = _now()
        return run

    def reactivate(self, run_id: int) -> Run | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        run.status = 'running'
        run.ended_at = ''
        return run

    def set_engine(self, run_id: int, engine) -> None:
        self._engines[run_id] = engine

    def engine_for(self, run_id: int):
        return self._engines.get(run_id)

    def engines(self) -> list:
        return [self._engines[i] for i in self._order if i in self._engines]

    def runs(self) -> list[Run]:
        return [self._runs[i] for i in self._order]

    def children(self, run_id: int) -> list[Run]:
        run = self._runs.get(run_id)
        if run is None:
            return []
        return [self._runs[i] for i in run.children if i in self._runs]

    def __len__(self) -> int:
        return len(self._runs)
