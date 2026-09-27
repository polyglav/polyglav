from __future__ import annotations

from pathlib import Path

SCOPES = ('role', 'team', 'job')

_DIRS = {'role': 'roles', 'team': 'teams', 'job': 'jobs'}


def memory_root(worktree) -> Path:
    return (Path(worktree) / '.polyglav' / 'memory').resolve()


def memory_path(worktree, scope: str, name: str) -> Path:
    scope = str(scope or '').strip().lower()
    directory = _DIRS.get(scope, scope or 'misc')
    safe = _safe_name(name)
    return (memory_root(worktree) / directory / f'{safe}.md').resolve()


def read_memory(worktree, scope: str, name: str) -> str:
    path = memory_path(worktree, scope, name)
    if path.exists():
        try:
            return path.read_text(encoding='utf-8').strip()
        except OSError:
            return ''
    legacy = _legacy_path(worktree, scope, name)
    if legacy is not None and legacy.exists():
        try:
            return legacy.read_text(encoding='utf-8').strip()
        except OSError:
            return ''
    return ''


def write_memory(worktree, scope: str, name: str, text: str) -> Path:
    path = memory_path(worktree, scope, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.md.tmp')
    tmp.write_text(str(text or '').strip(), encoding='utf-8')
    tmp.replace(path)
    return path


def memory_enabled(config, scope: str) -> bool:
    if config is None:
        return True
    if not config.get('memory', True):
        return False
    scopes = config.get('memory_scopes')
    if isinstance(scopes, dict):
        return bool(scopes.get(str(scope), True))
    return True


def cap_memory(text: str, config=None) -> str:
    if not text:
        return ''
    limit = 0
    if config is not None:
        limit = int(config.get('memory_max_chars', 0) or 0)
    if limit and len(text) > limit:
        return text[:limit].rsplit(' ', 1)[0] + '\n... (truncated)'
    return text


def memory_section(text: str, config=None, title: str = 'Role memory') -> str:
    body = cap_memory(text, config)
    if not body:
        return ''
    return f'## {title}\n{body}'


def _safe_name(name: str) -> str:
    cleaned = ''.join(c for c in str(name or '') if c.isalnum() or c in '-_.')
    return cleaned.strip('-_ .') or 'default'


def _legacy_path(worktree, scope: str, name: str) -> Path | None:
    base = Path(worktree) / '.polyglav'
    if scope == 'job':
        return base / 'jobs' / f'{name}.memory.md'
    if scope == 'team':
        return base / 'teams' / str(name) / 'memory.md'
    return None
