from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .sessions import private


def worktree(sessions_dir: Path) -> Path:
    return Path(sessions_dir).parent.parent


def path_for(sessions_dir: Path, session: str) -> Path:
    return Path(sessions_dir) / f'{session}.tools.log'


def _relative(path: Path, sessions_dir: Path) -> str:
    try:
        return str(path.relative_to(worktree(sessions_dir)))
    except ValueError:
        return str(path)


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with open(path, encoding='utf-8') as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def summarize(text: str, limit: int = 200) -> str:
    if not text:
        return ''
    for line in text.splitlines():
        line = ' '.join(line.split())
        if line:
            return line[:limit]
    return f'({len(text)} bytes)'


def append(sessions_dir: Path, session: str, turn: int, part: int,
           name: str, text: str) -> dict:
    path = path_for(sessions_dir, session)
    private.mkdir(path.parent)
    start = _line_count(path) + 1
    body = str(text or '')
    lines = body.count('\n') + (0 if body.endswith('\n') else 1)
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    header = (f'# turn {turn} part {part} {name} {stamp} '
              f'{len(body.encode("utf-8"))} bytes')
    chunk = header + '\n' + body
    if not chunk.endswith('\n'):
        chunk += '\n'
    chunk += '---\n\n'
    private.append_text(path, chunk)
    end = start + 1 + lines + 1
    ref = f'{_relative(path, sessions_dir)}#L{start}-L{end}'
    return {
        'ref': ref,
        'bytes': len(body.encode('utf-8')),
        'lines': lines,
        'summary': summarize(body),
    }


def resolve(ref: str, sessions_dir: Path) -> str | None:
    text = str(ref or '').strip()
    if not text:
        return None
    path_text, _, line_range = text.partition('#L')
    path = Path(path_text)
    if not path.is_absolute():
        path = worktree(sessions_dir) / path
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return None
    if not line_range:
        return '\n'.join(lines)
    try:
        start_text, _, end_text = line_range.partition('-L')
        start = max(1, int(start_text))
        end = int(end_text) if end_text else start
    except ValueError:
        return '\n'.join(lines)
    return '\n'.join(lines[start - 1:end])


def delete(sessions_dir: Path, session: str) -> None:
    try:
        path_for(sessions_dir, session).unlink()
    except OSError:
        pass
