import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from .config import Config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@dataclass
class ModelEntry:
    provider: str = ''
    model: str = ''
    added_at: str = ''
    last_used: str = ''

    @classmethod
    def from_dict(cls, d: dict) -> 'ModelEntry':
        return cls(
            provider=d.get('provider', ''),
            model=d.get('model', ''),
            added_at=d.get('added_at', ''),
            last_used=d.get('last_used', ''),
        )


class ModelRegistry:
    def __init__(self, global_dir: Path | None = None):
        base = global_dir if global_dir is not None else (Config.GLOBAL_DIR or Path.home())
        self.path = base / '.config' / 'polyglav' / 'models.json'
        self._entries: list[ModelEntry] = []
        self._load()

    def _load(self):
        self._entries = []
        if not self.path.exists():
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            self._entries = [ModelEntry.from_dict(d) for d in data if isinstance(d, dict)]
        except (OSError, ValueError):
            self._entries = []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps([asdict(e) for e in self._entries], indent=2))
        os.replace(tmp, self.path)

    def all(self) -> list[ModelEntry]:
        return list(self._entries)

    def find(self, provider: str, model: str) -> ModelEntry | None:
        for e in self._entries:
            if e.provider == provider and e.model == model:
                return e
        return None

    def put(self, provider: str, model: str) -> ModelEntry:
        now = _now()
        entry = self.find(provider, model)
        if entry is None:
            entry = ModelEntry(provider=provider, model=model,
                               added_at=now, last_used=now)
            self._entries.append(entry)
        else:
            entry.last_used = now
        self._save()
        return entry

    def touch(self, provider: str, model: str) -> ModelEntry | None:
        entry = self.find(provider, model)
        if entry is None:
            return None
        entry.last_used = _now()
        self._save()
        return entry

    def remove(self, provider: str, model: str) -> bool:
        entry = self.find(provider, model)
        if entry is None:
            return False
        self._entries.remove(entry)
        self._save()
        return True

    def grouped(self) -> list[tuple[str, list[ModelEntry]]]:
        groups: dict[str, list[ModelEntry]] = {}
        for e in self.all():
            groups.setdefault(e.provider, []).append(e)
        return list(groups.items())