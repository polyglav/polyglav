from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

TODO_DIR = '.polyglav/todos'
MAX_TODO_CHARS = 2000
STATUSES = ('pending', 'doing', 'done', 'blocked')

_SAFE = re.compile(r'[^A-Za-z0-9_.-]+')


def todos_dir(config) -> Path:
    root = config.local_path.parent.parent
    path = root / TODO_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _rel(config, path: Path) -> str:
    root = config.local_path.parent.parent
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def todo_path(config, session) -> Path:
    name = _SAFE.sub('-', str(getattr(session, 'session_name', '')
                             or 'session')).strip('.-') or 'session'
    return todos_dir(config) / f'{name}.json'


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    items = data.get('items') if isinstance(data, dict) else None
    return {
        'session': data.get('session', '') if isinstance(data, dict) else '',
        'updated_at': data.get('updated_at', '') if isinstance(data, dict) else '',
        'items': list(items) if isinstance(items, list) else [],
    }


def _save(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    state['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(state, indent=2), encoding='utf-8')
    tmp.replace(path)


def _item_line(item: dict) -> str:
    return (f"- [{item.get('status') or 'pending'}] "
            f"{item.get('id')}. {item.get('title') or ''}")


def _render(state: dict, path: Path, config, label: str = 'Todo') -> str:
    items = state.get('items') or []
    lines = [f'{label} ({_rel(config, path)}):']
    if not items:
        lines.append('(empty)')
    else:
        lines.extend(_item_line(item) for item in items)
    return '\n'.join(lines)


def _summary(state: dict) -> str:
    items = state.get('items') or []
    open_items = sum(1 for item in items
                     if item.get('status') in ('pending', 'doing', 'blocked'))
    done = sum(1 for item in items if item.get('status') == 'done')
    return f'Todo updated: {open_items} open, {done} done'


def todo_context(config, session, max_chars: int = MAX_TODO_CHARS) -> str:
    path = todo_path(config, session)
    if not path.exists():
        return ''
    state = _load(path)
    if not state.get('items'):
        return ''
    text = _render(state, path, config, label='Current work')
    if max_chars and len(text) > max_chars:
        text = text[:max_chars].rsplit('\n', 1)[0] + '\n... (truncated)'
    return text


def render_todo(config, path: Path, label: str = 'Todo') -> str:
    return _render(_load(path), path, config, label=label)


def list_todos(config) -> list[Path]:
    return sorted(todos_dir(config).glob('*.json'))


def resolve_todo(config, ident: str) -> Path | None:
    text = str(ident or '').strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = config.local_path.parent.parent / path
    if path.is_file():
        return path.resolve()
    for candidate in list_todos(config):
        if candidate.stem == text:
            return candidate
    return None


def _find(items: list, item_id: int) -> dict | None:
    for item in items:
        if int(item.get('id') or 0) == int(item_id):
            return item
    return None


def todo_action(engine, action: str, title: str = '', id: int = 0,
                note: str = '') -> str:
    action = str(action or 'list').strip().lower()
    session = engine.current_session
    path = todo_path(engine.config, session)
    state = _load(path)
    if not state.get('session'):
        state['session'] = session.session_name
    items = state['items']
    if action == 'add':
        text = str(title or '').strip()
        if not text:
            return 'Error: title is required to add a todo item'
        item_id = max((int(item.get('id') or 0) for item in items), default=0) + 1
        items.append({
            'id': item_id,
            'title': text,
            'status': 'pending',
            'note': str(note or ''),
            'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        })
    elif action in ('start', 'done', 'block', 'remove'):
        item = _find(items, id)
        if item is None:
            return f'Error: no todo item with id {id}'
        if action == 'remove':
            items.remove(item)
        else:
            item['status'] = {'start': 'doing', 'done': 'done',
                              'block': 'blocked'}[action]
            if note:
                item['note'] = str(note)
    elif action in ('list', 'show'):
        return _render(state, path, engine.config)
    else:
        return ('Error: action must be add, start, done, block, remove, '
                'list, or show')
    _save(path, state)
    return _render(state, path, engine.config) + '\n' + _summary(state)


def _is_note(result: str) -> bool:
    lines = [line for line in str(result or '').splitlines() if line]
    return bool(lines) and lines[-1].startswith('Todo updated')


def register_todo_tool(registry, engine) -> Callable:
    @registry.register(
        name='todo',
        description=(
            'Track the current work as a short internal todo list. Use it when '
            'a checklist helps, not for a one-step task. Items live under '
            '.polyglav/todos/ and survive compaction.'
        ),
        parameters={
            'type': 'object',
            'properties': {
                'action': {
                    'type': 'string',
                    'enum': ['add', 'start', 'done', 'block', 'remove',
                             'list', 'show'],
                    'description': 'Add an item, change its status, remove it, '
                                   'or show the list.',
                },
                'title': {
                    'type': 'string',
                    'description': 'Item text for action=add.',
                },
                'id': {
                    'type': 'integer',
                    'description': 'Item id for start, done, block, remove, and show.',
                },
                'note': {
                    'type': 'string',
                    'description': 'Optional note for add or block.',
                },
            },
            'required': ['action'],
        },
        category='todo',
        permission='read',
        key_arg='title',
        short='Track the current work',
        glyph='-',
        verb='Todo',
        note=_is_note,
    )
    def todo(action: str, title: str = '', id: int = 0,
             note: str = '') -> str:
        return todo_action(engine, action, title=title, id=id, note=note)
    return todo
