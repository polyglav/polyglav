import json
import os
from pathlib import Path
from typing import Any

from polyglav.config import Config
from polyglav.role_model import (
    Role, _apply_instructions, _instructions_dir, _load_scope,
    _resolved_scope,
)

class RoleRegistry:
    def __init__(self, global_dir: Path | None = None,
                 local_path: Path | None = None):
        base = global_dir if global_dir is not None else (Config.GLOBAL_DIR or Path.home())
        self.global_path = base / '.config' / 'polyglav' / 'roles.json'
        self.local_path = Path(local_path) if local_path is not None else (
            Path.cwd() / '.polyglav' / 'roles.json')
        self._global: dict[str, dict[str, Any]] = {}
        self._local: dict[str, dict[str, Any]] = {}
        self._global_view: dict[str, dict[str, Any]] = {}
        self._local_view: dict[str, dict[str, Any]] = {}
        self._plugins: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self):
        self._global = _load_scope(self.global_path)
        self._local = _load_scope(self.local_path)
        self._global_view = _resolved_scope(self._global, self.global_path)
        self._local_view = _resolved_scope(self._local, self.local_path)

    def add_plugin(self, entry: dict) -> None:
        if not isinstance(entry, dict) or not entry.get('name'):
            return
        self._plugins[str(entry['name'])] = dict(entry)

    def reload(self, plugin_manager=None) -> None:
        self._load()
        self._plugins = {}
        if plugin_manager is not None:
            register = getattr(plugin_manager, 'register_roles', None)
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
        names = self._plugins.keys() | self._global_view.keys() | self._local_view.keys()
        merged: dict[str, dict[str, Any]] = {}
        for name in names:
            entry: dict[str, Any] = {}
            entry.update(self._plugins.get(name, {}))
            entry.update(self._global_view.get(name, {}))
            entry.update(self._local_view.get(name, {}))
            entry['name'] = name
            merged[name] = entry
        return merged

    def all(self) -> list[Role]:
        return sorted(
            (Role.from_dict(e) for e in self._merged_entries().values()),
            key=lambda p: p.name)

    def names(self) -> list[str]:
        return sorted(self._merged_entries())

    def find(self, name: str) -> Role | None:
        entry = self._merged_entries().get(name)
        return Role.from_dict(entry) if entry is not None else None

    def origin(self, name: str) -> str:
        has_local = name in self._local
        has_global = name in self._global
        has_plugin = name in self._plugins
        if not any((has_local, has_global, has_plugin)):
            return ''
        layers = sum((has_local, has_global, has_plugin))
        if layers == 1:
            if has_local:
                return 'local'
            if has_global:
                return 'global'
            return 'plugin'
        return 'merged'

    def _scope_path(self, scope: str) -> Path:
        return self.global_path if scope == 'global' else self.local_path

    def _write_instructions(self, name: str, prompt: str, scope: str) -> None:
        base = _instructions_dir(self._scope_path(scope))
        base.mkdir(parents=True, exist_ok=True)
        path = base / f'{name}.md'
        tmp = path.with_suffix('.md.tmp')
        tmp.write_text(prompt.rstrip() + '\n', encoding='utf-8')
        os.replace(tmp, path)

    def _remove_instructions(self, name: str, scope: str) -> None:
        path = _instructions_dir(self._scope_path(scope)) / f'{name}.md'
        try:
            path.unlink()
        except OSError:
            pass

    def put(self, agent_role: Role, scope: str = 'local') -> Role:
        raw = self._local if scope == 'local' else self._global
        body = agent_role.to_body()
        prompt = body.pop('system_prompt', '')
        if prompt:
            self._write_instructions(agent_role.name, prompt, scope)
            body.setdefault('instructions', f'{agent_role.name}.md')
        raw[agent_role.name] = body
        self._save_scope(scope)
        self._load()
        return agent_role

    def remove(self, name: str, scope: str = 'local') -> bool:
        raw = self._local if scope == 'local' else self._global
        if name in raw:
            del raw[name]
            self._remove_instructions(name, scope)
            self._save_scope(scope)
            self._load()
            return True
        return False