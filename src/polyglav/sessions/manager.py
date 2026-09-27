import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .. import get_version
from . import turns

_BASE36 = '0123456789abcdefghijklmnopqrstuvwxyz'
SESSION_ID_LEN = 6
_SESSION_ID_IN_NAME = re.compile(r'^(?:ses|job|sub)_\d{8}_\d{6}_([0-9a-z]{6})$')


def session_id_hash(*parts, length: int = SESSION_ID_LEN) -> str:
    digest = hashlib.blake2b(digest_size=8)
    for part in parts:
        digest.update(str(part).encode())
        digest.update(b'\n')
    n = int.from_bytes(digest.digest(), 'big')
    if n == 0:
        return '0' * length
    out = ''
    while n and len(out) < length:
        n, rem = divmod(n, 36)
        out = _BASE36[rem] + out
    return out.rjust(length, '0')


def coded_session_name(prefix: str, *parts, sessions_dir: Path | None = None) -> str:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    while True:
        session_id = session_id_hash(prefix, ts, *parts, uuid4().hex)
        session_name = f'{prefix}_{ts}_{session_id}'
        taken = sessions_dir is not None and \
            (Path(sessions_dir) / f'{session_name}.json').exists()
        if not taken:
            return session_name


def session_id_from_name(session_name: str) -> str:
    match = _SESSION_ID_IN_NAME.match(session_name or '')
    return match.group(1) if match else ''


class Session:
    def __init__(self, session_name: str, turns_list: list | None = None,
                 errors: list | None = None,
                 permissions: list | None = None,
                 created_at: str | None = None,
                 updated_at: str | None = None,
                 parent_id: str = '',
                 sub_sessions: list | None = None,
                 role: str = '',
                 session_id: str = '',
                 version: str = ''):
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        self.session_name = session_name
        self.session_id = session_id or ''
        self.version = version or ''
        self.turns = turns_list or []
        self.errors = errors or []
        self.permissions = permissions or []
        self.created_at = created_at or now
        self.updated_at = updated_at or now
        self.parent_id = parent_id or ''
        self.sub_sessions = sub_sessions or []
        self.role = role or ''
        self._open: dict | None = None

    def _touch(self):
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec='seconds')

    def open_turn(self) -> dict | None:
        return self._open

    def start_turn(self, model: str = '', provider: str = '',
                   mode: str = '', reasoning=None) -> dict:
        if self._open is not None and self._open.get('status') == 'running':
            self.end_turn('ok')
        turn = turns.new_turn(len(self.turns) + 1, model=model, provider=provider,
                              mode=mode, reasoning=reasoning)
        self.turns.append(turn)
        self._open = turn
        self._touch()
        return turn

    def end_turn(self, status: str = 'ok', ended_at: str | None = None):
        if self._open is not None:
            turns.finish_turn(self._open, status, ended_at)
            self._open = None
            self._touch()

    def add_part(self, part: dict) -> dict:
        if self._open is None:
            self.start_turn()
        turns.add_part(self._open, part)
        self._touch()
        return part

    def add_user(self, text: str, timestamp: str | None = None, **meta) -> dict:
        self.start_turn(**meta)
        return self.add_part(turns.user_part(text, timestamp))

    def add_system(self, text: str, timestamp: str | None = None) -> dict:
        return self.add_part(turns.system_part(text, timestamp))

    def add_thinking(self, text: str | None, timestamp: str | None = None):
        if not text:
            return None
        return self.add_part(turns.thinking_part(text, timestamp))

    def add_text(self, text: str, timestamp: str | None = None) -> dict:
        return self.add_part(turns.text_part(text, timestamp))

    def add_tool(self, name: str, input=None, **kwargs) -> dict:
        return self.add_part(turns.tool_part(name, input, **kwargs))

    def add_command(self, command: str, summary: str = '', compact_from=None,
                    timestamp: str | None = None) -> dict:
        turn = turns.new_turn(len(self.turns) + 1)
        self.turns.append(turn)
        part = turns.command_part(command, summary, compact_from, timestamp)
        turns.add_part(turn, part)
        turns.finish_turn(turn, 'ok')
        self._touch()
        return part

    def last_command_part(self) -> dict | None:
        for turn in reversed(self.turns):
            for part in reversed(turn.get('parts') or []):
                if part.get('type') == 'command':
                    return part
        return None

    def set_compaction(self, summary: str, compact_from: int) -> dict:
        part = self.last_command_part()
        if part is None or part.get('summary'):
            part = self.add_command('/compact')
        part['summary'] = summary
        part['compact_from'] = compact_from
        self._touch()
        return part

    def add_error(self, code, message: str, timestamp: str | None = None):
        ts = timestamp or datetime.now(timezone.utc).isoformat(timespec='seconds')
        self.errors.append({'code': code, 'message': message, 'timestamp': ts})
        self._touch()

    def add_permission(self, tool: str, action: str, decision: str,
                       path: str | None = None, timestamp: str | None = None,
                       **extra):
        ts = timestamp or datetime.now(timezone.utc).isoformat(timespec='seconds')
        entry = {'tool': tool, 'action': action, 'decision': decision,
                 'timestamp': ts}
        if path is not None:
            entry['path'] = path
        entry.update(extra)
        self.permissions.append(entry)
        self._touch()

    def to_dict(self, tool_max_chars: int = 0, noise_tools: list[str] | None = None):
        noise_tools = set(noise_tools or [])
        out_turns = []
        for turn in self.turns:
            serialized = {k: v for k, v in turn.items() if k != 'parts'}
            parts = []
            for part in turn.get('parts') or []:
                p = dict(part)
                output = p.get('output')
                if p.get('type') == 'tool' and isinstance(output, str):
                    if p.get('name') in noise_tools:
                        p['output'] = (
                            f'[{p["name"]} result excluded from log; '
                            'see tool call above for parameters]')
                    elif tool_max_chars > 0 and len(output) > tool_max_chars:
                        p['output'] = output[:tool_max_chars] + (
                            f'… (truncated from {len(output)} chars)')
                parts.append(p)
            serialized['parts'] = parts
            out_turns.append(serialized)
        return {
            'session_name': self.session_name,
            'session_id': self.session_id,
            'turns': out_turns,
            'errors': self.errors,
            'permissions': self.permissions,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'parent_id': self.parent_id,
            'sub_sessions': self.sub_sessions,
            'role': self.role,
            'version': self.version,
        }

    @classmethod
    def from_dict(cls, data):
        if 'turns' not in data:
            raise ValueError('legacy session format (no turns)')
        return cls(
            data['session_name'],
            data.get('turns', []),
            data.get('errors', []),
            data.get('permissions', []),
            data.get('created_at'),
            data.get('updated_at'),
            data.get('parent_id', ''),
            data.get('sub_sessions', []),
            data.get('role', ''),
            data.get('session_id', ''),
            data.get('version', ''),
        )


class SessionManager:
    def __init__(self, sessions_dir: Path):
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.current: Session | None = None

    def create(self, session_name: str | None = None, role: str = '') -> Session:
        if not session_name:
            session_name = coded_session_name('ses', role, sessions_dir=self.sessions_dir)
        self.current = Session(
            session_name, session_id=session_id_from_name(session_name), role=role,
            version=get_version())
        return self.current

    def find_by_session_id(self, session_id: str) -> Session | None:
        session_id = (session_id or '').strip().lower()
        if not session_id:
            return None
        for path in sorted(self.sessions_dir.glob(f'*_{session_id}.json')):
            session = self.read(path.stem)
            if session is not None:
                return session
        return None

    def load(self, session_name: str) -> Session | None:
        s = self.read(session_name)
        if s is not None:
            self.current = s
        return s

    def read(self, session_name: str) -> Session | None:
        path = self.sessions_dir / f'{session_name}.json'
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        try:
            return Session.from_dict(data)
        except (ValueError, KeyError, TypeError):
            return None

    def save(self, session: Session | None = None, tool_max_chars: int = 0,
             noise_tools: list[str] | None = None):
        s = session or self.current
        if s is None:
            return
        with open(self.sessions_dir / f'{s.session_name}.json', 'w') as f:
            json.dump(s.to_dict(tool_max_chars=tool_max_chars, noise_tools=noise_tools),
                      f, indent=2)

    def list(self) -> list[str]:
        return sorted(p.stem for p in self.sessions_dir.glob('*.json'))

    def delete(self, session_name: str) -> bool:
        path = self.sessions_dir / f'{session_name}.json'
        if path.exists():
            path.unlink()
            return True
        return False
