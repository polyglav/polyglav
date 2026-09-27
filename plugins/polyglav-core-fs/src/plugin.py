import difflib
import fnmatch
import os
import re
from pathlib import Path

SKIP_DIRS = frozenset({'__pycache__', '.git', '.venv', '.polyglav',
                       '.opencode', 'dist', 'node_modules'})


def _cap(config=None) -> int:
    if config is None:
        return 0
    try:
        return max(0, int(config.get('tool_max_result_chars', 0)))
    except (TypeError, ValueError):
        return 0


def _truncate(text: str, max_chars: int = 0) -> str:
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rsplit('\n', 1)[0] + '\n... (truncated)'
    return text


def _walk(p, entries, indent, depth_left, lines, appended, total, cap):
    pad = '  ' * indent
    for e in entries:
        total[0] += 1
        if appended[0] < cap:
            if e.is_dir():
                lines.append(f'{pad}{e.name}/')
                appended[0] += 1
            else:
                try:
                    size = e.stat().st_size
                except OSError:
                    size = 0
                lines.append(f'{pad}{e.name}  {size}')
                appended[0] += 1
        if e.is_dir() and depth_left > 1 and e.name not in SKIP_DIRS:
            try:
                sub = sorted(e.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except OSError:
                sub = []
            _walk(e, sub, indent + 1, depth_left - 1, lines, appended, total, cap)


def _write_file_status(args):
    path = args.get('path')
    content = args.get('content', '')
    if not path:
        return ''
    p = Path(path).expanduser()
    try:
        old = p.read_text(encoding='utf-8', errors='replace') if p.exists() else None
    except OSError:
        old = None
    count = len(content)
    lines = content.splitlines()
    action = ('appended' if args.get('mode') == 'a'
              else 'created' if old is None else 'overwritten')
    summary = f'({p.resolve()} - {len(lines)} lines, {count} chars, {action})'
    if old is None:
        body = [f'+ {l}' for l in lines[:20]]
        if len(lines) > 20:
            body.append(f'+ … ({len(lines)} lines total)')
        return '\n'.join([path] + body + [summary])
    diff = list(difflib.unified_diff(
        old.splitlines(), content.splitlines(),
        fromfile=f'a/{path}', tofile=f'b/{path}', lineterm=''))
    body = [l for l in diff if not l.startswith(('--- ', '+++ '))]
    if len(body) > 40:
        body = body[:40] + [f'… ({len(body) - 40} more diff lines)']
    return '\n'.join([path] + body + [summary])


def register_tools(registry):
    @registry.register(
        name='file_read',
        description='Read the contents of a text file. Use to inspect source code, configs, logs, or any file on disk after locating it with glob. Returns numbered lines with a header reporting the total line and character count; limit=0 returns just the header as a size probe, use offset/limit to page through large files.',
        parameters={
            'type': 'object',
            'properties': {
                'path': {
                    'type': 'string',
                    'description': 'Path to the file to read (relative to the project or absolute)',
                },
                'offset': {
                    'type': 'integer',
                    'description': '1-based line number to start reading from',
                },
                'limit': {
                    'type': 'integer',
                    'description': 'Maximum number of lines to return',
                },
            },
            'required': ['path'],
        },
        category='read',
        permission='read',
        path_arg='path',
        key_arg='path',
        short='Read the contents of a text file',
        aliases=['read_file', 'read', 'view'],
        param_aliases={'file': 'path'},
        note=lambda r: r.endswith('(empty file)'),
    )
    def file_read(path: str, offset: int = 1, limit: int = 500,
                  _config=None) -> str:
        p = Path(path).expanduser()
        if not p.exists():
            return f'Error: file not found: {path}'
        if p.is_dir():
            return f'Error: {path} is a directory (use list_dir instead)'
        try:
            content = p.read_text(encoding='utf-8', errors='replace')
        except OSError as e:
            return f'Error reading {path}: {e}'
        lines = content.splitlines()
        header = f'# {path} - {len(lines)} lines, {len(content)} chars'
        if int(limit) == 0:
            return header
        start = max(0, int(offset) - 1)
        end = len(lines) if not limit else min(len(lines), start + int(limit))
        width = len(str(end))
        out = [f'{i:>{width}}|{line}'
               for i, line in enumerate(lines[start:end], start=start + 1)]
        if end < len(lines):
            header += f' (showing {start + 1}-{end})'
        if not out:
            return f'{header}\n(empty file)'
        return _truncate(header + '\n' + '\n'.join(out), _cap(_config))

    @registry.register(
        name='list_dir',
        description='List a directory\'s contents. Returns sorted entries with a trailing / for subdirectories and file sizes. depth=1 lists only the immediate contents; higher values recurse into subdirectories as an indented tree. Use glob for finding files by pattern.',
        parameters={
            'type': 'object',
            'properties': {
                'path': {
                    'type': 'string',
                    'description': 'Directory to list (relative to the project or absolute)',
                },
                'depth': {
                    'type': 'integer',
                    'description': 'How many levels deep to recurse; 1 = immediate contents only',
                },
            },
            'required': ['path'],
        },
        category='read',
        permission='list',
        path_arg='path',
        key_arg='path',
        short="List a directory's contents",
        aliases=['ls'],
        param_aliases={'directory': 'path'},
        glyph='*',
        verb='List',
        note=lambda r: r == '(empty directory)',
    )
    def list_dir(path: str = '.', depth: int = 1, _config=None) -> str:
        p = Path(path).expanduser()
        if not p.exists():
            return f'Error: path not found: {path}'
        if not p.is_dir():
            return f'Error: {path} is not a directory (use file_read instead)'
        level = max(1, int(depth))
        try:
            entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError as e:
            return f'Error listing {path}: {e}'
        if not entries:
            return '(empty directory)'
        try:
            cap = max(0, int(_config.get('list_dir_max_entries', 0))) if _config else 0
        except (TypeError, ValueError):
            cap = 0
        if cap <= 0:
            cap = 10**9
        lines = [f'{p}:']
        appended = [0]
        total = [0]
        _walk(p, entries, 1, level, lines, appended, total, cap)
        if total[0] > cap:
            lines.append(f'... (showing first {appended[0]} of {total[0]} entries)')
        return _truncate('\n'.join(lines), _cap(_config))

    @registry.register(
        name='file_write',
        description='Write content to a file, creating parent directories as needed. Use to create or update files such as source code, configs, and notes. Relative paths resolve against the current working directory - the result reports the resolved absolute path.',
        parameters={
            'type': 'object',
            'properties': {
                'path': {
                    'type': 'string',
                    'description': 'Path of the file to write (relative to the current directory or absolute)',
                },
                'content': {
                    'type': 'string',
                    'description': 'Full contents to write to the file',
                },
                'mode': {
                    'type': 'string',
                    'enum': ['w', 'a'],
                    'description': 'Write mode: w to overwrite, a to append',
                },
            },
            'required': ['path', 'content'],
        },
        category='write',
        permission='edit',
        path_arg='path',
        key_arg='path',
        short='Write content to a file',
        status=_write_file_status,
        aliases=['write_file', 'write'],
        param_aliases={'file': 'path'},
    )
    def file_write(path: str, content: str, mode: str = 'w') -> str:
        p = Path(path).expanduser()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            exists = p.exists()
            if mode == 'a':
                with open(p, 'a', encoding='utf-8') as f:
                    f.write(content)
                action = 'Appended'
            else:
                p.write_text(content, encoding='utf-8')
                action = 'Overwritten' if exists else 'Created'
        except (OSError, ValueError) as e:
            return f'Error writing {path}: {e}'
        return (f'{action} {p.resolve()} '
                f'({len(content.splitlines())} lines, {len(content)} chars)')

    @registry.register(
        name='glob',
        description='Find files and directories matching a glob pattern (e.g. "**/*.py", "src/**/chat.py"). Use to locate a file path before reading or listing it - do not guess paths.',
        parameters={
            'type': 'object',
            'properties': {
                'pattern': {
                    'type': 'string',
                    'description': 'Glob pattern; ** matches across directories',
                },
                'path': {
                    'type': 'string',
                    'description': 'Directory to search from (defaults to the current directory)',
                },
            },
            'required': ['pattern'],
        },
        category='read',
        permission='list',
        path_arg='path',
        key_arg='pattern',
        short='Find files matching a glob pattern',
        glyph='*',
        verb='Glob',
        note=lambda r: r.startswith('(no matches for'),
    )
    def glob(pattern: str, path: str = '.', _config=None) -> str:
        base = Path(path).expanduser()
        if not base.exists() or not base.is_dir():
            return f'Error: not a directory: {path}'
        matches = []
        for m in sorted(base.glob(pattern)):
            if any(p in SKIP_DIRS for p in m.relative_to(base).parts):
                continue
            try:
                rel = m.relative_to(base)
            except ValueError:
                rel = m
            matches.append(f'{rel}{"/" if m.is_dir() else ""}')
        if not matches:
            return f'(no matches for "{pattern}")'
        result = '\n'.join(matches[:200])
        if len(matches) > 200:
            result += f'\n... (showing 200 of {len(matches)} matches)'
        return _truncate(result, _cap(_config))

    @registry.register(
        name='grep',
        description='Search file contents for a regex pattern. Returns matching file:line: text. Use to find where something is defined or used.',
        parameters={
            'type': 'object',
            'properties': {
                'pattern': {
                    'type': 'string',
                    'description': 'Regular expression to search for',
                },
                'path': {
                    'type': 'string',
                    'description': 'Directory or file to search (defaults to the current directory)',
                },
                'glob': {
                    'type': 'string',
                    'description': 'Glob to limit which files are searched (e.g. "*.py")',
                },
            },
            'required': ['pattern'],
        },
        category='read',
        permission='list',
        path_arg='path',
        key_arg='pattern',
        short='Search file contents for a pattern',
        aliases=['find'],
        param_aliases={'query': 'pattern'},
        glyph='*',
        verb='Grep',
        note=lambda r: r.startswith('(no matches for'),
    )
    def grep(pattern: str, path: str = '.', glob: str = '*',
             _config=None) -> str:
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f'Error: invalid regex: {e}'
        base = Path(path).expanduser()
        if not base.exists():
            return f'Error: path not found: {path}'
        files = [base] if base.is_file() else []
        if not files:
            for root, dirs, names in os.walk(base):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for name in sorted(names):
                    if fnmatch.fnmatch(name, glob):
                        files.append(Path(root) / name)
        results = []
        for f in files:
            try:
                text = f.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            if base.is_file():
                rel = base.name
            else:
                try:
                    rel = f.relative_to(base)
                except ValueError:
                    rel = f
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    results.append(f'{rel}:{i}: {line[:120].strip()}')
                    if len(results) >= 100:
                        break
            if len(results) >= 100:
                break
        if not results:
            return f'(no matches for "{pattern}")'
        result = '\n'.join(results[:100])
        if len(results) >= 100:
            result += '\n... (showing first 100 matches)'
        return _truncate(result, _cap(_config))
