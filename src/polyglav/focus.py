from __future__ import annotations

from .engine import Engine


class FocusManager:
    def __init__(self, root: Engine):
        self.root = root
        self._stack: list[int] = [root.current_run.id]

    @property
    def active(self) -> Engine:
        return self.active_engine()

    def active_engine(self) -> Engine:
        return self._engine_for(self._stack[-1])

    def stack(self) -> list[int]:
        return list(self._stack)

    def engines(self) -> list[Engine]:
        out = [self.root]
        for engine in self.root.runs.engines():
            if engine is not self.root and engine not in out:
                out.append(engine)
        return out

    def is_root(self) -> bool:
        return self._stack[-1] == self.root.current_run.id

    def find_run(self, run_id: int):
        return self.root.runs.get(run_id)

    def enter(self, run_id: int) -> Engine:
        run_id = int(run_id)
        if run_id != self._stack[-1]:
            self._stack.append(run_id)
        engine = self.active_engine()
        self.root.runs.reactivate(run_id)
        self._repoint(engine)
        return engine

    def focus_session(self, session_name: str) -> Engine:
        for run in self.root.runs.runs():
            if run.session == session_name:
                return self.enter(run.id)
        session = self.root.sessions.read(session_name)
        if session is None:
            raise ValueError(f'Unknown session: {session_name}')
        run = self.root.runs.start(
            role=session.role or '', session=session.session_name,
            session_id=session.session_id)
        return self.enter(run.id)

    def back(self) -> Engine:
        if len(self._stack) > 1:
            self._stack.pop()
        engine = self.active_engine()
        self._repoint(engine)
        return engine

    def reset(self) -> Engine:
        self._stack = [self.root.current_run.id]
        self._repoint(self.root)
        return self.root

    def _engine_for(self, run_id: int) -> Engine:
        if run_id == self.root.current_run.id:
            return self.root
        engine = self.root.runs.engine_for(run_id)
        if engine is not None:
            self._adopt_ui(engine)
            return engine
        run = self.root.runs.get(run_id)
        if run is None:
            raise ValueError(f'Unknown run #{run_id}')
        engine = self.root.run_engine(
            run, ui=getattr(self.root, '_ui', None))
        self._adopt_ui(engine)
        return engine

    def _adopt_ui(self, engine: Engine):
        if engine is self.root:
            return
        engine._focus = self
        ui = getattr(self.root, '_ui', None)
        if ui is None or not hasattr(ui, '_loop'):
            return
        engine._ui = ui
        if not getattr(self.root, '_unattended', False):
            engine._ask_ui = ui

    def _repoint(self, engine: Engine):
        ui = getattr(self.root, '_ui', None)
        if ui is not None and hasattr(ui, '_loop'):
            ui._loop = engine
