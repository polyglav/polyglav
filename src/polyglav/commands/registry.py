from typing import Callable


class CommandRegistry:
    def __init__(self, chat_loop):
        self.chat_loop = chat_loop
        self.commands: dict[str, Callable] = {}
        self.meta: dict[str, dict] = {}

    def register(self, name: str, aliases: list[str] | None = None,
                 handler: Callable | None = None, description: str = '',
                 subcommands: list[tuple[str, str]] | None = None):
        def store(fn):
            self.commands[name] = fn
            for alias in (aliases or []):
                self.commands[alias] = fn
            self.meta[name] = {
                'description': description,
                'aliases': list(aliases or []),
                'subcommands': list(subcommands or []),
            }
            return fn
        if handler is None:
            return store
        return store(handler)

    def dispatch(self, line: str):
        parts = line.strip().split(maxsplit=1)
        cmd = parts[0].lstrip('/')
        arg = parts[1] if len(parts) > 1 else ''
        handler = self.commands.get(cmd)
        if handler:
            try:
                handler(arg)
            except TypeError:
                handler()
        else:
            print(f'Unknown command: /{cmd}. Type /help for available commands.')

    def canonical(self, key: str) -> str | None:
        if key in self.meta:
            return key
        for name, meta in self.meta.items():
            if key in meta.get('aliases', []):
                return name
        return None
