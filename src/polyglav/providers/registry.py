import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def resolve_model_ref(ref: str, providers: dict) -> tuple[str, str, str] | None:
    if not ref or '/' not in ref:
        return None
    name, _, model = ref.partition('/')
    if not name or not model:
        return None
    factory = (providers or {}).get(name)
    if factory is None or not getattr(factory, 'DEFAULT_BASE_URL', ''):
        return None
    return name, factory.DEFAULT_BASE_URL, model


@dataclass
class ProviderEntry:
    provider: str = ''
    base_url: str = ''
    api_key: str = ''
    added_at: str = ''
    last_used: str = ''

    @classmethod
    def from_dict(cls, d: dict) -> 'ProviderEntry':
        return cls(
            provider=d.get('provider', ''),
            base_url=d.get('base_url', ''),
            api_key=d.get('api_key', ''),
            added_at=d.get('added_at', ''),
            last_used=d.get('last_used', ''),
        )


class ProviderRegistry:
    FILENAME = 'providers.json'

    def __init__(self, global_dir: Path | None = None):
        base = global_dir if global_dir is not None else (Config.GLOBAL_DIR or Path.home())
        self.path = base / '.config' / 'polyglav' / self.FILENAME
        self._entries: dict[str, ProviderEntry] = {}
        self._load()

    def _load(self):
        self._entries = {}
        if not self.path.exists():
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                for name, d in data.items():
                    if isinstance(d, dict):
                        entry = ProviderEntry.from_dict(d)
                        entry.provider = entry.provider or str(name)
                        self._entries[str(name)] = entry
        except (OSError, ValueError):
            self._entries = {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(
            {name: asdict(e) for name, e in self._entries.items()}, indent=2))
        os.replace(tmp, self.path)
        if any(e.api_key for e in self._entries.values()):
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def all(self) -> list[ProviderEntry]:
        return list(self._entries.values())

    def find(self, provider: str) -> ProviderEntry | None:
        return self._entries.get(provider)

    def api_key_for(self, provider: str) -> str:
        entry = self.find(provider)
        return entry.api_key if entry is not None else ''

    def base_url_for(self, provider: str, default: str = '') -> str:
        entry = self.find(provider)
        if entry is None or not entry.base_url:
            return default
        return entry.base_url

    def put(self, provider: str, base_url: str = '', api_key: str = '',
            touch: bool = True) -> ProviderEntry:
        now = _now()
        entry = self._entries.get(provider)
        if entry is None:
            entry = ProviderEntry(provider=provider, base_url=base_url,
                                  api_key=api_key, added_at=now, last_used=now)
            self._entries[provider] = entry
        else:
            if base_url:
                entry.base_url = base_url
            if api_key:
                entry.api_key = api_key
            if touch:
                entry.last_used = now
        self._save()
        return entry

    def remove(self, provider: str) -> bool:
        if provider in self._entries:
            del self._entries[provider]
            self._save()
            return True
        return False

    def touch(self, provider: str) -> ProviderEntry | None:
        entry = self.find(provider)
        if entry is None:
            return None
        entry.last_used = _now()
        self._save()
        return entry