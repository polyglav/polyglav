import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from .config import Config


_ACTION_RANK = {'deny': 0, 'ask': 1, 'allow': 2}


def _coerce_action(value):
    if isinstance(value, bool):
        return 'allow' if value else 'deny'
    return value


def clamp_action(action: str, cap: str) -> str:
    action = _coerce_action(action)
    cap = _coerce_action(cap)
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
    callable: str = 'allow'

    @classmethod
    def from_dict(cls, d: dict) -> 'Role':
        action = _coerce_action(d.get('callable', 'allow'))
        if action not in _ACTION_RANK:
            action = 'allow'
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
            callable=action,
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
    return out


def _resolved_scope(raw: dict[str, dict[str, Any]],
                    path: Path) -> dict[str, dict[str, Any]]:
    base = _instructions_dir(path)
    out: dict[str, dict[str, Any]] = {}
    for name, entry in raw.items():
        resolved = dict(entry)
        _apply_instructions(resolved, name, base)
        out[name] = resolved
    return out
