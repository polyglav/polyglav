import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Ask:
    def __init__(self, id: int, question: str, origin: str,
                 context: str = '', options: list | None = None,
                 kind: str = 'direction', permission: str = '',
                 status: str = 'pending', answer: str = '',
                 created_at: str | None = None,
                 answered_at: str | None = None):
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        self.id = id
        self.question = question
        self.origin = origin
        self.context = context
        self.options = options or []
        self.kind = kind
        self.permission = permission
        self.status = status
        self.answer = answer
        self.created_at = created_at or now
        self.answered_at = answered_at or ''

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'question': self.question,
            'origin': self.origin,
            'context': self.context,
            'options': self.options,
            'kind': self.kind,
            'permission': self.permission,
            'status': self.status,
            'answer': self.answer,
            'created_at': self.created_at,
            'answered_at': self.answered_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Ask':
        return cls(
            int(data['id']),
            data.get('question', ''),
            data.get('origin', ''),
            data.get('context', ''),
            data.get('options', []),
            data.get('kind', 'direction'),
            data.get('permission', ''),
            data.get('status', 'pending'),
            data.get('answer', ''),
            data.get('created_at'),
            data.get('answered_at'),
        )


class AskStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path) as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [d for d in data if isinstance(d, dict)]

    def _write(self, asks: list[dict]):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.json.tmp')
        with open(tmp, 'w') as f:
            json.dump(asks, f, indent=2)
        tmp.replace(self.path)

    def add(self, question: str, origin: str, context: str = '',
            options: list | None = None, kind: str = 'direction',
            permission: str = '') -> Ask:
        with self._lock:
            asks = self._read()
            next_id = max((int(a.get('id', 0)) for a in asks), default=0) + 1
            ask = Ask(next_id, question, origin, context, options,
                      kind, permission)
            asks.append(ask.to_dict())
            self._write(asks)
        return ask

    def find(self, id: int) -> Ask | None:
        asks = self._read()
        for a in asks:
            if int(a.get('id', -1)) == int(id):
                return Ask.from_dict(a)
        return None

    def list(self, status: str | None = None) -> list[Ask]:
        asks = [Ask.from_dict(a) for a in self._read()]
        if status is not None:
            asks = [a for a in asks if a.status == status]
        return sorted(asks, key=lambda a: a.id)

    def answer(self, id: int, text: str) -> Ask | None:
        text = text.strip()
        if not text:
            return None
        with self._lock:
            asks = self._read()
            target = None
            for a in asks:
                if int(a.get('id', -1)) == int(id):
                    target = a
                    break
            if target is None:
                return None
            now = datetime.now(timezone.utc).isoformat(timespec='seconds')
            target['status'] = 'answered'
            target['answer'] = text
            target['answered_at'] = now
            self._write(asks)
        return Ask.from_dict(target)


def inject_answer(store: AskStore, ask: Ask):
    latest = store.find(ask.id)
    if latest is None:
        return False
    sessions_dir = store.path.parent / 'sessions'
    from .sessions.manager import SessionManager
    manager = SessionManager(sessions_dir)
    session = manager.read(latest.origin)
    if session is None:
        return False
    session.add_user(
        f'[answer to parked ask #{latest.id}] {latest.answer}')
    manager.save(session)
    return True