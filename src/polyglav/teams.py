import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from .config import Config
from .roles import _load_scope


@dataclass
class TeamStage:
    role: str
    mode: str = ''
    task_hint: str = ''
    handoff_note: str = ''
    skills: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d) -> 'TeamStage':
        if isinstance(d, str):
            return cls(role=d)
        return cls(
            role=str(d.get('role', '')),
            mode=str(d.get('mode') or ''),
            task_hint=str(d.get('task_hint') or ''),
            handoff_note=str(d.get('handoff_note') or ''),
            skills=list(d.get('skills') or []),
        )

    def to_body(self) -> dict:
        body = asdict(self)
        return {k: v for k, v in body.items() if v not in ('', [])}


@dataclass
class Team:
    name: str
    stages: list = field(default_factory=list)
    description: str = ''
    tags: list = field(default_factory=list)
    loop: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> 'Team':
        stages = d.get('stages') or []
        if isinstance(stages, dict):
            stages = list(stages.keys())
        return cls(
            name=d.get('name', ''),
            stages=[TeamStage.from_dict(s) for s in stages],
            description=str(d.get('description') or ''),
            tags=list(d.get('tags') or []),
            loop=dict(d.get('loop') or {}),
        )

    def to_body(self) -> dict:
        body = asdict(self)
        body.pop('name', None)
        body['stages'] = [s.to_body() for s in self.stages]
        return {k: v for k, v in body.items() if v not in ('', [], {}, False)}


class TeamRegistry:
    BUNDLED_FILENAME = 'bundled_teams.json'

    def __init__(self, global_dir: Path | None = None,
                 local_path: Path | None = None,
                 bundled_path: Path | None = None):
        base = global_dir if global_dir is not None else (Config.GLOBAL_DIR or Path.home())
        self.global_path = base / '.config' / 'polyglav' / 'teams.json'
        self.local_path = Path(local_path) if local_path is not None else (
            Path.cwd() / '.polyglav' / 'teams.json')
        self.bundled_path = Path(bundled_path) if bundled_path is not None else (
            Path(__file__).with_name(self.BUNDLED_FILENAME))
        self._bundled: dict[str, dict[str, Any]] = {}
        self._plugins: dict[str, dict[str, Any]] = {}
        self._global: dict[str, dict[str, Any]] = {}
        self._local: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self):
        self._bundled = _load_scope(self.bundled_path)
        self._global = _load_scope(self.global_path)
        self._local = _load_scope(self.local_path)

    def add_plugin(self, entry: dict) -> None:
        if not isinstance(entry, dict) or not entry.get('name'):
            return
        self._plugins[str(entry['name'])] = dict(entry)

    def reload(self, plugin_manager=None) -> None:
        self._load()
        self._plugins = {}
        if plugin_manager is not None:
            register = getattr(plugin_manager, 'register_teams', None)
            if register:
                register(self)

    def _save_scope(self, scope: str):
        path = self.global_path if scope == 'global' else self.local_path
        raw = self._global if scope == 'global' else self._local
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(raw, indent=2))
        os.replace(tmp, path)

    def _merged_entries(self) -> dict[str, dict[str, Any]]:
        names = (set(self._bundled) | set(self._plugins)
                 | set(self._global) | set(self._local))
        merged: dict[str, dict[str, Any]] = {}
        for name in names:
            entry: dict[str, Any] = {}
            entry.update(self._bundled.get(name, {}))
            entry.update(self._plugins.get(name, {}))
            entry.update(self._global.get(name, {}))
            entry.update(self._local.get(name, {}))
            entry['name'] = name
            merged[name] = entry
        return merged

    def all(self) -> list[Team]:
        return sorted(
            (Team.from_dict(e) for e in self._merged_entries().values()),
            key=lambda t: t.name)

    def names(self) -> list[str]:
        return sorted(self._merged_entries())

    def find(self, name: str) -> Team | None:
        entry = self._merged_entries().get(name)
        return Team.from_dict(entry) if entry is not None else None

    def origin(self, name: str) -> str:
        has_local = name in self._local
        has_global = name in self._global
        has_bundled = name in self._bundled
        has_plugin = name in self._plugins
        if not any((has_local, has_global, has_bundled, has_plugin)):
            return ''
        layers = sum((has_local, has_global, has_bundled, has_plugin))
        if layers == 1:
            if has_local:
                return 'local'
            if has_global:
                return 'global'
            if has_plugin:
                return 'plugin'
            return 'bundled'
        return 'merged'

    def is_bundled(self, name: str) -> bool:
        return name in self._bundled

    def put(self, team: Team, scope: str = 'local') -> Team:
        raw = self._local if scope == 'local' else self._global
        raw[team.name] = team.to_body()
        self._save_scope(scope)
        return team

    def remove(self, name: str, scope: str = 'local') -> bool:
        raw = self._local if scope == 'local' else self._global
        if name in raw:
            del raw[name]
            self._save_scope(scope)
            return True
        return False


def team_memory_path(worktree: Path, name: str) -> Path:
    from .memory import memory_path
    return memory_path(worktree, 'team', name)


def read_team_memory(worktree: Path, name: str) -> str:
    from .memory import read_memory
    return read_memory(worktree, 'team', name)


def write_team_memory(worktree: Path, name: str, text: str) -> Path:
    from .memory import write_memory
    return write_memory(worktree, 'team', name, text)