from typing import Callable
import inspect


ACTIVITY_DEFAULTS: dict[str, tuple[str, str]] = {
    'read': ('←', 'Read'),
    'write': ('→', 'Write'),
    'search': ('%', 'Search'),
    'exec': ('$', 'Run'),
    'ask': ('~', 'Ask'),
    'todo': ('-', 'Todo'),
    'delegate': ('↳', 'Call'),
}


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, dict] = {}
        self._schema: list[dict] = []

    def register(self, name: str, description: str, parameters: dict,
                 refine: bool = False, category: str = 'tool',
                 permission: str = 'web', path_arg: str | None = None,
                 key_arg: str | None = None, short: str = '',
                 status: Callable[[dict], str] | None = None,
                 echo: bool = False, glyph: str = '', verb: str = '',
                 aliases: list[str] | None = None,
                 param_aliases: dict | None = None,
                 note: Callable[[str], bool] | None = None,
                 permission_fn: Callable[[dict], str] | None = None,
                 loop: bool = False, confirm: bool = True,
                 error: Callable[[str], bool] | None = None):
        def wrapper(fn):
            def build_schema(tool_name: str) -> dict:
                return {
                    'type': 'function',
                    'function': {
                        'name': tool_name,
                        'description': description,
                        'parameters': parameters,
                    },
                }

            entry = {
                'name': name,
                'fn': fn,
                'refine': refine,
                'category': category,
                'permission': permission,
                'path_arg': path_arg,
                'key_arg': key_arg,
                'short': short,
                'status': status,
                'echo': echo,
                'glyph': glyph,
                'verb': verb,
                'param_aliases': dict(param_aliases or {}),
                'note': note,
                'permission_fn': permission_fn,
                'loop': loop,
                'confirm': confirm,
                'error': error,
                'schema': build_schema(name),
            }
            self._tools[name] = entry
            self._schema.append(entry['schema'])
            for alias in (aliases or []):
                self._tools[alias] = {'alias_of': name, 'schema': build_schema(alias)}
                self._schema.append(self._tools[alias]['schema'])
            return fn
        return wrapper

    def _canonical(self, name: str) -> tuple[str, dict | None]:
        tool = self._tools.get(name)
        if not tool:
            return name, None
        if 'alias_of' in tool:
            return tool['alias_of'], self._tools.get(tool['alias_of'])
        return name, tool

    def clean_args(self, name: str, arguments: dict) -> dict:
        canon, tool = self._canonical(name)
        if not tool:
            return {}
        props = tool['schema']['function']['parameters'].get('properties', {})
        args = dict(arguments)
        for alias, target in tool.get('param_aliases', {}).items():
            if alias in args and target not in args:
                args[target] = args.pop(alias)
        return {k: v for k, v in args.items() if k in props and v is not None}

    def execute(self, name: str, arguments: dict, config=None,
                echo: bool = True) -> str:
        canon, tool = self._canonical(name)
        if not tool:
            return f'Error: unknown tool "{name}"'
        args = self.clean_args(name, arguments)
        fn = tool['fn']
        if config is not None:
            try:
                params = inspect.signature(fn).parameters
                if '_config' in params:
                    args = {**args, '_config': config}
                if '_echo' in params:
                    args = {**args, '_echo': echo}
            except (TypeError, ValueError):
                pass
        try:
            return fn(**args)
        except Exception as e:
            return f'Error executing {name}: {e}'

    def status_parts(self, name: str, arguments: dict) -> tuple[str, list[str]]:
        canon, tool = self._canonical(name)
        args = self.clean_args(name, arguments)
        if not tool:
            return name, []
        status_fn = tool.get('status')
        if status_fn:
            try:
                block = status_fn(args) or ''
                lines = block.split('\n')
                return lines[0], lines[1:]
            except Exception:
                pass
        key_arg = tool.get('key_arg')
        if key_arg and args.get(key_arg):
            return str(args[key_arg])[:80], []
        return name, []

    def echo_for(self, name: str) -> bool:
        canon, tool = self._canonical(name)
        return bool(tool and tool.get('echo'))

    def is_note_result(self, name: str, result: str) -> bool:
        canon, tool = self._canonical(name)
        if not tool or not tool.get('note'):
            return False
        try:
            return bool(tool['note'](result))
        except Exception:
            return False

    def is_error_result(self, name: str, result: str) -> bool:
        canon, tool = self._canonical(name)
        if not tool or not tool.get('error'):
            return False
        try:
            return bool(tool['error'](result))
        except Exception:
            return False

    def refine_required(self, name: str) -> bool:
        canon, tool = self._canonical(name)
        return bool(tool and tool.get('refine'))

    def permission_for(self, name: str) -> str:
        canon, tool = self._canonical(name)
        return tool['permission'] if tool else 'web'

    def resolver_for(self, name: str) -> Callable | None:
        canon, tool = self._canonical(name)
        return tool.get('permission_fn') if tool else None

    def path_arg_for(self, name: str) -> str | None:
        canon, tool = self._canonical(name)
        return tool['path_arg'] if tool else None

    def key_arg_for(self, name: str) -> str | None:
        canon, tool = self._canonical(name)
        return tool['key_arg'] if tool else None

    def loop_for(self, name: str) -> bool:
        canon, tool = self._canonical(name)
        return bool(tool and tool.get('loop'))

    def confirm_for(self, name: str) -> bool:
        canon, tool = self._canonical(name)
        return bool(tool.get('confirm', True)) if tool else True

    def params_str(self, name: str, arguments: dict,
                   exclude: tuple[str, ...] = ()) -> str:
        canon, tool = self._canonical(name)
        if not tool:
            return ''
        args = self.clean_args(name, arguments)
        key_arg = tool.get('key_arg')
        if key_arg:
            args.pop(key_arg, None)
        for k in exclude:
            args.pop(k, None)
        if not args:
            return ''
        props = tool['schema']['function']['parameters'].get('properties', {})
        ordered = sorted(args.items(),
                         key=lambda kv: list(props).index(kv[0]) if kv[0] in props else 99)
        parts = []
        for k, v in ordered:
            text = str(v)
            if '\n' in text or len(text) > 60:
                text = f'<{len(text)} chars>'
            parts.append(f'{k}={text}')
        return ', '.join(parts)

    def activity(self, name: str, arguments: dict) -> tuple[str, str, str, str] | None:
        canon, tool = self._canonical(name)
        if not tool:
            return None
        args = self.clean_args(name, arguments)
        glyph = tool.get('glyph')
        verb = tool.get('verb')
        if not glyph or not verb:
            defaults = ACTIVITY_DEFAULTS.get(tool['category'])
            if defaults is None:
                return None
            d_glyph, d_verb = defaults
            glyph = glyph or d_glyph
            verb = verb or d_verb
        label = None
        status_fn = tool.get('status')
        if status_fn:
            try:
                first = (status_fn(args) or '').split('\n', 1)[0].strip()
                if first:
                    label = first[:80]
            except Exception:
                pass
        if label is None:
            key_arg = tool.get('key_arg')
            label = str(args[key_arg])[:80] if key_arg and args.get(key_arg) else name
        exclude = tuple(k for k, v in args.items() if str(v)[:80] == label)
        return glyph, verb, label, self.params_str(name, arguments, exclude=exclude)

    def info(self, name: str) -> dict | None:
        canon, tool = self._canonical(name)
        if not tool:
            return None
        return {
            'name': name,
            'description': tool['schema']['function']['description'],
            'short': tool['short'] or tool['schema']['function']['description'][:60],
            'category': tool['category'],
            'permission': tool['permission'],
            'parameters': tool['schema']['function']['parameters'],
        }

    def schema(self) -> list[dict]:
        return list(self._schema)

    def schema_filtered(self, allowed: set[str]) -> list[dict]:
        return [tool['schema']
                for name, tool in self._tools.items()
                if 'alias_of' not in tool and name in allowed]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def is_registered(self, name: str) -> bool:
        return name in self._tools

    def canonical_name(self, name: str) -> str:
        canon, _ = self._canonical(name)
        return canon

    def primary_names(self) -> list[str]:
        return [n for n, t in self._tools.items() if 'alias_of' not in t]
