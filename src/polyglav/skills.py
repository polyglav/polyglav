import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config


@dataclass
class Skill:
    name: str
    content: str = ''
    description: str = ''
    tags: list = field(default_factory=list)

    @classmethod
    def from_entry(cls, name: str, entry: dict) -> 'Skill':
        content = str(entry.get('content') or '')
        description = str(entry.get('description') or '')
        if not description and content:
            description = content.strip().splitlines()[0]
        return cls(
            name=name,
            content=content,
            description=description,
            tags=list(entry.get('tags') or []),
        )


def _load_dir(directory: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob('*.md')):
        try:
            content = path.read_text()
        except OSError:
            continue
        out[path.stem] = {'name': path.stem, 'content': content}
    return out


def skills_section(registry, names: list) -> str:
    parts = []
    for name in names:
        skill = registry.find(name)
        if skill is None or not skill.content:
            continue
        parts.append(f'### {skill.name}\n\n{skill.content.strip()}')
    if not parts:
        return ''
    return '## Skills\n\n' + '\n\n'.join(parts)


class SkillRegistry:
    def __init__(self, local_dir: Path | None = None,
                 global_dir: Path | None = None):
        base = global_dir if global_dir is not None else (Config.GLOBAL_DIR or Path.home())
        self.global_dir = base / '.config' / 'polyglav' / 'skills'
        self.local_dir = Path(local_dir) if local_dir is not None else (
            Path.cwd() / '.polyglav' / 'skills')
        self._plugins: dict[str, dict[str, Any]] = {}
        self._global: dict[str, dict[str, Any]] = {}
        self._local: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self):
        self._global = _load_dir(self.global_dir)
        self._local = _load_dir(self.local_dir)

    def add_plugin(self, entry: dict) -> None:
        if not isinstance(entry, dict) or not entry.get('name'):
            return
        self._plugins[str(entry['name'])] = dict(entry)

    def reload(self, plugin_manager=None) -> None:
        self._load()
        self._plugins = {}
        if plugin_manager is not None:
            register = getattr(plugin_manager, 'register_skills', None)
            if register:
                register(self)

    def _merged_entries(self) -> dict[str, dict[str, Any]]:
        names = (set(self._plugins) | set(self._global) | set(self._local))
        merged: dict[str, dict[str, Any]] = {}
        for name in names:
            entry: dict[str, Any] = {}
            entry.update(self._plugins.get(name, {}))
            entry.update(self._global.get(name, {}))
            entry.update(self._local.get(name, {}))
            entry['name'] = name
            merged[name] = entry
        return merged

    def all(self) -> list[Skill]:
        return sorted(
            (Skill.from_entry(name, e)
             for name, e in self._merged_entries().items()),
            key=lambda s: s.name)

    def names(self) -> list[str]:
        return sorted(self._merged_entries())

    def find(self, name: str) -> Skill | None:
        entry = self._merged_entries().get(name)
        return Skill.from_entry(name, entry) if entry is not None else None

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

    def put(self, skill: Skill, scope: str = 'local') -> Skill:
        directory = self.global_dir if scope == 'global' else self.local_dir
        raw = self._global if scope == 'global' else self._local
        raw[skill.name] = {
            'name': skill.name,
            'content': skill.content,
            'description': skill.description,
            'tags': list(skill.tags),
        }
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'{skill.name}.md'
        tmp = path.with_suffix('.md.tmp')
        tmp.write_text(skill.content)
        os.replace(tmp, path)
        return skill

    def remove(self, name: str, scope: str = 'local') -> bool:
        raw = self._global if scope == 'global' else self._local
        directory = self.global_dir if scope == 'global' else self.local_dir
        path = directory / f'{name}.md'
        if name in raw or path.exists():
            raw.pop(name, None)
            if path.exists():
                path.unlink()
            return True
        return False