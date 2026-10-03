from typing import NamedTuple

from .config import Config


PROMPT_COLORS = {
    'cyan': '\033[1;36m',
    'orange': '\033[1;38;5;208m',
}

DEFAULT_PROMPT_COLOR = 'orange'

DEFAULT_READ_KEYS = ['read', 'list', 'web', 'catalog', 'ask', 'handoff',
                     'offload']


def read_keys(config: Config) -> set:
    listed = (config.get('access') or {}).get('read_tools')
    return set(listed if isinstance(listed, list) else DEFAULT_READ_KEYS)


def is_write_key(config: Config, permission_key: str) -> bool:
    return str(permission_key) not in read_keys(config)


def mode_name(config: Config, mode: str | None = None) -> str:
    return resolve_mode(config, mode)[0].name


class ModeSpec(NamedTuple):
    name: str
    instruction: str
    permissions: dict
    deny: list
    allow: list
    color: str = ''


def _normalize_spec(name: str, spec: dict) -> ModeSpec:
    spec = spec or {}
    permissions = dict(spec.get('tool_permission') or {})
    deny = [str(n) for n in (spec.get('tools.deny') or [])]
    allow = [str(n) for n in (spec.get('tools.allow') or [])]
    instruction = str(spec.get('system_prompt') or '')
    color = str(spec.get('color') or '')
    return ModeSpec(name, instruction, permissions, deny, allow, color)


def mode_color(spec: ModeSpec) -> str:
    name = str(spec.color or '').strip().lower()
    if name in PROMPT_COLORS:
        return PROMPT_COLORS[name]
    permissions = spec.permissions or {}
    if (permissions.get('edit') == 'deny'
            and permissions.get('bash') == 'deny'):
        return PROMPT_COLORS['cyan']
    return PROMPT_COLORS[DEFAULT_PROMPT_COLOR]


def unknown_mode(config: Config, mode: str | None = None) -> str | None:
    name = str(mode if mode is not None else (config.get('mode') or 'read'))
    specs = {str(k): v for k, v in (config.get('modes') or {}).items()}
    return name if name not in specs else None


def resolve_mode(config: Config, mode: str | None = None) -> tuple[ModeSpec, list[str]]:
    name = str(mode if mode is not None else (config.get('mode') or 'read'))
    specs = {str(k): v for k, v in (config.get('modes') or {}).items()}
    if name not in specs:
        name = 'read'
    return _normalize_spec(name, specs.get(name) or {}), sorted(specs)


def mode_list(config: Config) -> list[ModeSpec]:
    specs = {str(k): v for k, v in (config.get('modes') or {}).items()}
    return [_normalize_spec(n, s) for n, s in sorted(specs.items())]


def merge_policy(config: Config, mode: str | None = None) -> tuple[dict, list, list]:
    spec, _ = resolve_mode(config, mode)
    permissions = dict(config.get('tool_permission') or {})
    permissions.update(spec.permissions)
    deny = [str(n) for n in (config.get('tools.deny') or [])] + spec.deny
    allow = spec.allow if spec.allow else [str(n) for n in (config.get('tools.allow') or [])]
    if spec.name == 'read':
        for key in list(permissions):
            if is_write_key(config, key):
                permissions[key] = 'deny'
    return permissions, allow, deny


def _instructions_path(config: Config):
    worktree = config.local_path.parent.parent
    name = str(config.get('project_instructions') or '')
    if not name.strip():
        return None
    candidate = worktree / name
    return candidate if candidate.is_file() else None


def system_instruction(config: Config, mode: str | None = None) -> str:
    parts = []
    system_prompt = config.get('system_prompt')
    if system_prompt:
        parts.append(str(system_prompt))
    spec, _ = resolve_mode(config, mode)
    if spec.instruction:
        parts.append(spec.instruction)
    return '\n\n'.join(parts).strip()


def instructions_file_section(config: Config, max_chars: int = 20000) -> str:
    path = _instructions_path(config)
    if path is None:
        return ''
    try:
        content = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    if max_chars > 0 and len(content) > max_chars:
        content = content[:max_chars].rsplit('\n', 1)[0] + '\n... (truncated)'
    return f'Project instructions ({path.name}):\n\n{content}'