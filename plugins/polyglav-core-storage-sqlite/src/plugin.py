import json
import sqlite3
from contextlib import closing
from pathlib import Path

from polyglav.sessions.manager import Session


class SQLiteSessionStore:
    def __init__(self, sessions_dir: Path):
        self.sessions_dir = Path(sessions_dir)
        self.path = self.sessions_dir / 'sessions.db'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            with db:
                db.execute(
                    'CREATE TABLE IF NOT EXISTS sessions ('
                    'name TEXT PRIMARY KEY, data TEXT NOT NULL)')

    def _connect(self):
        return sqlite3.connect(self.path)

    def save(self, session, max_chars: int = 0,
             drop_tools: list[str] | None = None, spill=None) -> None:
        data = json.dumps(session.to_dict(
            max_chars=max_chars, drop_tools=drop_tools, spill=spill),
            separators=(',', ':'))
        with closing(self._connect()) as db:
            with db:
                db.execute(
                    'INSERT INTO sessions (name, data) VALUES (?, ?) '
                    'ON CONFLICT(name) DO UPDATE SET data = excluded.data',
                    (session.session_name, data))

    def read(self, name: str):
        with closing(self._connect()) as db:
            row = db.execute(
                'SELECT data FROM sessions WHERE name = ?', (name,)).fetchone()
        if row is None:
            return None
        try:
            session = Session.from_dict(json.loads(row[0]))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None
        last = session.turns[-1] if session.turns else None
        if last is not None and last.get('status') in ('running', 'paused'):
            session._open = last
        return session

    def list(self) -> list[str]:
        with closing(self._connect()) as db:
            rows = db.execute('SELECT name FROM sessions ORDER BY name').fetchall()
        return [row[0] for row in rows]

    def delete(self, name: str) -> bool:
        with closing(self._connect()) as db:
            with db:
                cursor = db.execute('DELETE FROM sessions WHERE name = ?', (name,))
            return cursor.rowcount > 0

    def materialize(self, session) -> Path | None:
        path = self.sessions_dir / f'{session.session_name}.json'
        tmp = path.with_suffix('.json.tmp')
        with open(tmp, 'w') as f:
            json.dump(session.to_dict(), f, separators=(',', ':'))
        tmp.replace(path)
        return path


def register_services(services):
    services['session_store'] = SQLiteSessionStore
