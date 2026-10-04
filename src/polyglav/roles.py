import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from .config import Config


_ACTION_RANK = {'deny': 0, 'ask': 1, 'allow': 2}


def clamp_action(action: str, cap: str) -> str:
    if not isinstance(action, str) or action not in _ACTION_RANK:
        return action
    if not isinstance(cap, str) or cap not in _ACTION_RANK:
        return action
    return action if _ACTION_RANK[action] <= _ACTION_RANK[cap] else cap


def resolve_permissions(parent_self: dict, parent_grant: dict,
                        role_permission: dict) -> dict:
    parent_self = parent_self or {}
    parent_grant = parent_grant or {}
    role_permission = role_permission or {}
    out: dict = {}
    for key in set(parent_self) | set(role_permission):
        cap = parent_grant.get(key, parent_self.get(key, 'ask'))
        want = role_permission.get(key, parent_self.get(key, cap))
        out[key] = clamp_action(want, cap)
    return out


def resolve_grant_ceiling(parent_self: dict, parent_grant: dict, role_grant: dict,
                          self_permissions: dict) -> dict:
    parent_self = parent_self or {}
    parent_grant = parent_grant or {}
    self_permissions = self_permissions or {}
    base = role_grant if role_grant else self_permissions
    out: dict = {}
    for key in set(base) | set(self_permissions):
        cap = parent_grant.get(key, parent_self.get(key, 'ask'))
        want = base.get(key, self_permissions.get(key, 'deny'))
        out[key] = clamp_action(want, cap)
    return out


@dataclass
class Role:
    name: str
    system_prompt: str = ''
    description: str = ''
    model: str = ''
    skills: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    tool_permission: dict = field(default_factory=dict)
    grant_permission: dict = field(default_factory=dict)
    ask_policy: dict = field(default_factory=dict)
    instructions: str = ''

    @classmethod
    def from_dict(cls, d: dict) -> 'Role':
        return cls(
            name=d.get('name', ''),
            system_prompt=d.get('system_prompt', ''),
            description=d.get('description', ''),
            model=d.get('model', ''),
            skills=list(d.get('skills') or []),
            tags=list(d.get('tags') or []),
            tool_permission=dict(d.get('tool_permission') or {}),
            grant_permission=dict(d.get('grant_permission') or {}),
            ask_policy=dict(d.get('ask_policy') or {}),
            instructions=d.get('instructions', ''),
        )

    def to_body(self) -> dict:
        body = asdict(self)
        body.pop('name', None)
        return {k: v for k, v in body.items() if v not in ('', [], {})}


def _parse_value(raw: str):
    raw = raw.strip()
    if raw == '':
        return ''
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def parse_frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            end = i
            break
    if end is None:
        return {}, text
    meta: dict[str, Any] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, sep, raw = line.partition(':')
        if not sep:
            continue
        meta[key.strip()] = _parse_value(raw)
    body = '\n'.join(lines[end + 1:]).strip('\n')
    return meta, body


def _instructions_dir(path: Path) -> Path:
    return path.parent / path.stem


def _apply_instructions(entry: dict, name: str, base: Path) -> None:
    ref = str(entry.get('instructions') or '').strip()
    if ref and Path(ref).name != ref:
        return
    path = base / (ref or f'{name}.md')
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return
    meta, body = parse_frontmatter(text)
    for key, value in meta.items():
        entry.setdefault(key, value)
    body = body.strip('\n')
    if body and not entry.get('system_prompt'):
        entry['system_prompt'] = body


def _load_scope(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    if isinstance(data, dict):
        for name, d in data.items():
            if isinstance(d, dict):
                entry = dict(d)
                entry.setdefault('name', str(name))
                out[str(name)] = entry
    elif isinstance(data, list):
        for d in data:
            if isinstance(d, dict) and d.get('name'):
                out[str(d['name'])] = dict(d)
    base = _instructions_dir(path)
    for name, entry in out.items():
        _apply_instructions(entry, name, base)
    return out


class RoleRegistry:
    def __init__(self, global_dir: Path | None = None,
                 local_path: Path | None = None):
        base = global_dir if global_dir is not None else (Config.GLOBAL_DIR or Path.home())
        self.global_path = base / '.config' / 'polyglav' / 'roles.json'
        self.local_path = Path(local_path) if local_path is not None else (
            Path.cwd() / '.polyglav' / 'roles.json')
        self._global: dict[str, dict[str, Any]] = {}
        self._local: dict[str, dict[str, Any]] = {}
        self._plugins: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self):
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
        names = self._plugins.keys() | self._global.keys() | self._local.keys()
        merged: dict[str, dict[str, Any]] = {}
        for name in names:
            entry: dict[str, Any] = {}
            entry.update(self._plugins.get(name, {}))
            entry.update(self._global.get(name, {}))
            entry.update(self._local.get(name, {}))
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