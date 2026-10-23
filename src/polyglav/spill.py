from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

TEMP_PARENT = 'polyglav'
PERSISTENT_DIR = '.polyglav/tmp'


def worktree(sessions_dir: Path) -> Path:
    return Path(sessions_dir).parent.parent


def temp_root() -> Path:
    return Path(tempfile.gettempdir()) / TEMP_PARENT


def persistent_root(config, sessions_dir: Path) -> Path:
    raw = str(config.get('tools_output_dir') or PERSISTENT_DIR).strip()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = worktree(sessions_dir) / path
    return path


def root_for(config, sessions_dir: Path, persistent: bool | None = None) -> Path:
    if persistent is None:
        persistent = bool(config.get('tools_output_spill'))
    if persistent:
        return persistent_root(config, sessions_dir)
    return temp_root()


def roots_for(config, sessions_dir: Path) -> list[Path]:
    roots = [temp_root(), persistent_root(config, sessions_dir)]
    out: list[Path] = []
    for root in roots:
        if root not in out:
            out.append(root)
    return out


def ref_for(path: Path, sessions_dir: Path) -> str:
    try:
        return str(Path(path).relative_to(worktree(sessions_dir)))
    except ValueError:
        return str(path)


def write_file(root: Path, session: str, filename: str, text: str,
               sessions_dir: Path) -> str:
    path = Path(root) / session / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return ref_for(path, sessions_dir)


def write(root: Path, session: str, turn: int, part: int, text: str,
          sessions_dir: Path) -> str:
    return write_file(root, session, f'{turn}_{part}.txt', text, sessions_dir)


def resolve(ref: str, sessions_dir: Path) -> str | None:
    if not ref:
        return None
    path = Path(str(ref)).expanduser()
    if not path.is_absolute():
        path = worktree(sessions_dir) / path
    try:
        return path.read_text()
    except OSError:
        return None


def prune(root: Path, max_bytes: int = 0) -> None:
    if max_bytes <= 0:
        return
    root = Path(root)
    if not root.exists():
        return
    files = [p for p in root.rglob('*') if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    if total <= max_bytes:
        return
    for path in sorted(files, key=lambda p: p.stat().st_mtime):
        if total <= max_bytes:
            break
        try:
            total -= path.stat().st_size
            path.unlink()
        except OSError:
            pass


def delete(session: str, roots: list[Path]) -> None:
    for root in roots:
        shutil.rmtree(Path(root) / session, ignore_errors=True)
