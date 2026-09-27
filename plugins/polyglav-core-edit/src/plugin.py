import difflib
from pathlib import Path


def _edit_count(count) -> int:
    try:
        return max(0, int(count))
    except (TypeError, ValueError):
        return 0


def _edit_result(path: str, old: str, new: str, count: int) -> str | None:
    if not old:
        return 'Error: old text must not be empty'
    p = Path(path).expanduser()
    if not p.exists():
        return f'Error: file not found: {path}'
    if p.is_dir():
        return f'Error: {path} is a directory (use file_read instead)'
    try:
        content = p.read_text(encoding='utf-8', errors='replace')
    except OSError as e:
        return f'Error reading {path}: {e}'
    occurrences = content.count(old)
    if occurrences == 0:
        return f'Error: old text not found in {path}'
    count = occurrences if count == 0 else min(count, occurrences)
    updated = content.replace(old, new, count)
    try:
        p.write_text(updated, encoding='utf-8')
    except OSError as e:
        return f'Error writing {path}: {e}'
    return (f'Edited {p.resolve()} ({count} of {occurrences} occurrences, '
            f'{len(updated.splitlines())} lines, {len(updated)} chars)')


def _edit_status(args):
    path = args.get('path')
    old = args.get('old', '')
    new = args.get('new', '')
    count = _edit_count(args.get('count'))
    if not path or not old:
        return ''
    p = Path(path).expanduser()
    try:
        current = p.read_text(encoding='utf-8', errors='replace') if p.exists() else None
    except OSError:
        current = None
    if current is None:
        return f'{path} (file not found)'
    occurrences = current.count(old)
    if occurrences == 0:
        return f'{path} (no match for old text)'
    count = occurrences if count == 0 else min(count, occurrences)
    updated = current.replace(old, new, count)
    diff = list(difflib.unified_diff(
        current.splitlines(), updated.splitlines(),
        fromfile=f'a/{path}', tofile=f'b/{path}', lineterm=''))
    body = [l for l in diff if not l.startswith(('--- ', '+++ '))]
    if len(body) > 40:
        body = body[:40] + [f'… ({len(body) - 40} more diff lines)']
    summary = (f'({p.resolve()} - replacing {count} of {occurrences} occurrences)')
    return '\n'.join([path] + body + [summary])


def register_tools(registry):
    @registry.register(
        name='file_edit',
        description='Targeted search-and-replace edit in a file: replace a specific old text with new text at the given path. Prefer this over file_write for surgical single-hunk edits; use file_write to create, overwrite, or append whole files. Reports how many occurrences were replaced; count=0 replaces all occurrences.',
        parameters={
            'type': 'object',
            'properties': {
                'path': {
                    'type': 'string',
                    'description': 'Path of the file to edit (relative to the current directory or absolute)',
                },
                'old': {
                    'type': 'string',
                    'description': 'The exact text to search for and replace',
                },
                'new': {
                    'type': 'string',
                    'description': 'The replacement text (empty string deletes the old text)',
                },
                'count': {
                    'type': 'integer',
                    'description': 'How many occurrences to replace; 0 replaces all (default 1)',
                },
            },
            'required': ['path', 'old', 'new'],
        },
        category='write',
        permission='edit',
        path_arg='path',
        key_arg='path',
        short='Edit a file via search-and-replace',
        status=_edit_status,
        aliases=['edit'],
        param_aliases={'file': 'path', 'old_text': 'old', 'new_text': 'new'},
    )
    def file_edit(path: str, old: str, new: str = '', count: int = 1) -> str:
        result = _edit_result(path, old, new, _edit_count(count))
        return result or 'Edited (no change)'