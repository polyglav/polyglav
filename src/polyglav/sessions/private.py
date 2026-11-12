from __future__ import annotations

import os
from pathlib import Path

DIR_MODE = 0o700
FILE_MODE = 0o600


def chmod(path: Path, mode: int) -> None:
    try:
        Path(path).chmod(mode)
    except OSError:
        pass


def mkdir(path: Path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)
    chmod(path, DIR_MODE)


def write_text(path: Path, text: str) -> None:
    fd = os.open(Path(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write(text)
    chmod(path, FILE_MODE)


def append_text(path: Path, text: str) -> None:
    fd = os.open(Path(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, FILE_MODE)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write(text)
    chmod(path, FILE_MODE)
