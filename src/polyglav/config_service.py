from __future__ import annotations

import json

from .config import (CONFIG_CHOICES, CONFIG_DESCRIPTIONS, CONFIG_VALUE_INLINE,
                     DEFAULT_CONFIG, Config)


class ConfigError(ValueError):
    pass


class ConfigService:
    def __init__(self, config: Config):
        self.config = config

    def keys(self) -> list[str]:
        return sorted(self.config.data)

    def get(self, key: str):
        self.validate(key)
        return self.config.get(key)

    def origin(self, key: str) -> str:
        return self.config.origin(key)

    def default(self, key: str) -> str | None:
        if key in DEFAULT_CONFIG:
            return str(DEFAULT_CONFIG[key])
        if key in self.config._plugin_defaults:
            return str(self.config._plugin_defaults[key])
        return None

    def description(self, key: str) -> str:
        return (CONFIG_DESCRIPTIONS.get(key)
                or self.config.plugin_descriptions.get(key, ''))

    def owner(self, key: str) -> str:
        return self.config.plugin_owners.get(key, 'core')

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for key in self.keys():
            out.setdefault(self.owner(key), []).append(key)
        return {name: sorted(keys) for name, keys in out.items()}

    def as_dict(self, keys: list[str] | None = None,
                grouped: bool = False) -> dict:
        keys = keys or self.keys()
        if grouped:
            out: dict[str, dict] = {}
            for key in keys:
                out.setdefault(self.owner(key), {})[key] = self.config.data[key]
            return out
        return {key: self.config.data[key] for key in keys}

    def render_json(self, keys: list[str] | None = None,
                    grouped: bool = True) -> None:
        print(json.dumps(self.as_dict(keys, grouped=grouped), indent=2))

    def options(self, key: str) -> str:
        choices = CONFIG_CHOICES.get(key)
        return ' | '.join(choices) if choices else ''

    def validate(self, key: str) -> None:
        if key not in self.config.data:
            raise ConfigError(f'unknown config key: {key}')

    def set(self, key: str, value, scope: str = 'local') -> None:
        self.validate(key)
        self.config.set(key, value, scope=scope)

    def unset(self, key: str, scope: str = 'local') -> None:
        self.validate(key)
        self.config.unset(key, scope=scope)

    def reload(self) -> None:
        self.config.reload()

    def render_listing(self, verbose: bool = False,
                       grouped: bool = True) -> None:
        keys = self.keys()
        key_width = max((len(k) for k in keys), default=0)
        if not grouped:
            for key in keys:
                self._render_key(key, key_width=key_width, verbose=verbose,
                                 detail=False)
            return
        for owner, names in self.groups().items():
            print(f'{owner}:')
            for key in names:
                self._render_key(key, key_width=key_width, verbose=verbose,
                                 detail=False)

    def render_detail(self, key: str) -> None:
        self.validate(key)
        self._render_key(key, key_width=0, verbose=True, detail=True)

    def _render_key(self, key: str, key_width: int, verbose: bool,
                    detail: bool) -> None:
        value = str(self.config.data[key])
        origin = self.config.origin(key)
        desc = self.description(key)
        default = self.default(key)
        options = self.options(key)
        if detail:
            line = f'  {key}: {value}  ({origin})'
        else:
            line = f'  {key:<{key_width}}  {value}  ({origin})'
        if len(value) <= CONFIG_VALUE_INLINE:
            if verbose and default is not None:
                if len(default) <= CONFIG_VALUE_INLINE:
                    line += f'  default: {default}'
                else:
                    print(line)
                    print(f'    default: {default}')
                    if desc:
                        print(f'    {desc}')
                    return
            print(line)
            if verbose and desc:
                print(f'    {desc}')
            if verbose and options:
                print(f'    options: {options}')
            return
        print(f'  {key}:')
        print(f'    value: {value}')
        print(f'    source: {origin}')
        if verbose and default is not None:
            print(f'    default: {default}')
        if verbose and desc:
            print(f'    description: {desc}')
        if verbose and options:
            print(f'    options: {options}')
