import json

from polyglav.role_model import Role

_ROLE_FIELDS = ('system_prompt', 'description', 'model', 'skills', 'tags',
                'tool_permission', 'grant_permission', 'ask_policy',
                'instructions', 'callable')

_PERMISSION_ALIASES = {
    'write': 'edit',
    'exec': 'bash',
    'shell': 'bash',
    'cmd': 'bash',
    'search': 'web',
}

_VALID_ACTIONS = ('allow', 'ask', 'deny')
_ACTION_ALIASES = {'true': 'allow', 'yes': 'allow',
                   'false': 'deny', 'no': 'deny'}


def _normalize_action(value):
    if isinstance(value, bool):
        return 'allow' if value else 'deny'
    text = str(value).strip().lower()
    if text in _VALID_ACTIONS:
        return text
    return _ACTION_ALIASES.get(text)


def _normalize_permission_map(engine, value, field: str):
    if value is None:
        return None, None
    if not isinstance(value, dict):
        return None, f'Error: {field} must be an object of key: action pairs'
    valid = engine.permission_keys()
    out: dict = {}
    unknown: list[str] = []
    invalid: list[str] = []
    for key, action in value.items():
        name = str(key)
        canonical = _PERMISSION_ALIASES.get(name.strip().lower(), name)
        if canonical not in valid:
            unknown.append(name)
            continue
        normalized = _normalize_action(action)
        if normalized is None:
            invalid.append(f'{canonical}={action!r}')
            continue
        out[canonical] = normalized
    if unknown:
        listed = ', '.join(sorted(valid))
        return None, (f'Error: unknown permission key(s) in {field}: '
                      f'{", ".join(sorted(unknown))}. Valid keys: {listed}')
    if invalid:
        return None, (f'Error: invalid action in {field}: {", ".join(invalid)}. '
                      'Use allow, ask, or deny (true/false are accepted)')
    return out, None


def list_entries(engine) -> str:
    if engine.roles is None:
        return 'Error: roles plugin is not loaded'
    return '\n'.join(_role_line(engine, role) for role in engine.roles.all())


def _role_line(engine, agent_role) -> str:
    parts = []
    if agent_role.model:
        parts.append(f'model={agent_role.model}')
    if agent_role.tags:
        parts.append(f'tags={",".join(agent_role.tags)}')
    if agent_role.skills:
        parts.append(f'skills={",".join(agent_role.skills)}')
    detail = ' ' + ' '.join(parts) if parts else ''
    return f'- {agent_role.name}{detail} ({engine.roles.origin(agent_role.name)})'


def show(engine, name: str) -> str:
    if engine.roles is None:
        return 'Error: roles plugin is not loaded'
    agent_role = engine.roles.find(name)
    if agent_role is None:
        return f'Error: unknown role "{name}"'
    lines = [f'{agent_role.name} ({engine.roles.origin(name)})']
    if agent_role.description:
        lines.append(f'description: {agent_role.description}')
    lines.append(f'system_prompt: {agent_role.system_prompt or "(empty)"}')
    if agent_role.instructions:
        lines.append(f'instructions: {agent_role.instructions}')
    if agent_role.model:
        lines.append(f'model: {agent_role.model}')
    if agent_role.skills:
        lines.append(f'skills: {", ".join(agent_role.skills)}')
    if agent_role.tags:
        lines.append(f'tags: {", ".join(agent_role.tags)}')
    if getattr(agent_role, 'callable', 'allow') != 'allow':
        lines.append(f'callable: {agent_role.callable}')
    valid = engine.permission_keys()
    for key in ('tool_permission', 'grant_permission', 'ask_policy'):
        value = getattr(agent_role, key)
        if value:
            lines.append(f'{key}: {json.dumps(value)}')
            if key in ('tool_permission', 'grant_permission'):
                unknown = [k for k in value if k not in valid]
                if unknown:
                    lines.append('  WARNING: unknown permission key(s): '
                                 + ', '.join(sorted(unknown)))
                bad = [k for k, v in value.items()
                       if _normalize_action(v) is None]
                if bad:
                    lines.append('  WARNING: invalid action value(s): '
                                 + ', '.join(sorted(bad)))
    return '\n'.join(lines)


def save(engine, name: str, values: dict) -> str:
    if engine.roles is None:
        return 'Error: roles plugin is not loaded'
    for field in ('tool_permission', 'grant_permission'):
        normalized, error = _normalize_permission_map(
            engine, values.get(field), field)
        if error:
            return error
        if normalized is not None:
            values[field] = normalized
    data = {'name': name}
    for field in _ROLE_FIELDS:
        if values.get(field) is not None:
            data[field] = values[field]
    engine.roles.put(Role.from_dict(data), scope='local')
    return f'Saved role: {name} (local)'


def remove(engine, name: str) -> str:
    if engine.roles is None:
        return 'Error: roles plugin is not loaded'
    if engine.roles.remove(name):
        return f'Removed role: {name} (local)'
    if engine.roles.find(name) is not None:
        return (f'Error: role "{name}" is not local - override it with save '
                'instead of remove')
    return f'Error: no local role to remove: {name}'


def validate(engine, name: str, values: dict) -> str:
    errors: list[str] = []
    if not name:
        errors.append('name is required')
    saved = engine.roles.find(name) if name and engine.roles is not None else None
    for field in ('tool_permission', 'grant_permission'):
        value = values.get(field)
        if value is None and saved is not None:
            value = getattr(saved, field)
        _, error = _normalize_permission_map(engine, value, field)
        if error:
            errors.append(error)
    callable_value = values.get('callable') if values.get('callable') not in ('', None) else (
        getattr(saved, 'callable', 'allow') if saved is not None else 'allow')
    if _normalize_action(callable_value) is None:
        errors.append('callable must be allow, ask, or deny')
    if errors:
        return 'Invalid role: ' + '. '.join(errors)
    return f'Role "{name}" is valid.'
