import json
from typing import Callable

from ..skills import Skill
from ..teams import Team
from ..roles import Role

_ROLE_FIELDS = ('system_prompt', 'description', 'model', 'skills', 'tags',
                'tool_permission', 'grant_permission', 'ask_policy',
                'instructions')

_CATALOG_WRITE_ACTIONS = ('save', 'remove', 'reload')

_PERMISSION_ALIASES = {
    'write': 'edit',
    'exec': 'bash',
    'shell': 'bash',
    'cmd': 'bash',
    'search': 'web',
}

_PERMISSION_KEY_LIST = ('bash, edit, read, list, web, catalog, ask, handoff, '
                        'offload, call, delegate, mcp, vcs')


def _normalize_permission_map(engine, value, field: str) -> tuple[dict | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict):
        return None, f'Error: {field} must be an object of category: action pairs'
    valid = engine.permission_keys()
    out: dict = {}
    unknown: list[str] = []
    for key, action in value.items():
        name = str(key)
        canonical = _PERMISSION_ALIASES.get(name.strip().lower(), name)
        if canonical not in valid:
            unknown.append(name)
            continue
        out[canonical] = action
    if unknown:
        listed = ', '.join(sorted(valid))
        return None, (f'Error: unknown permission key(s) in {field}: '
                      f'{", ".join(sorted(unknown))}. Valid keys: {listed}')
    return out, None


def _catalog_action(engine, args: dict) -> str | None:
    action = str((args or {}).get('action') or '')
    if action in _CATALOG_WRITE_ACTIONS and engine._mode() != 'write':
        return 'deny'
    return None


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


def _team_line(engine, team) -> str:
    chain = ' > '.join(stage.role for stage in team.stages) or '(no stages)'
    tags = f' tags={",".join(team.tags)}' if team.tags else ''
    return (f'- {team.name}{tags} ({engine.teams.origin(team.name)}): {chain}')


def _skill_line(engine, skill) -> str:
    desc = (skill.description or '').strip().splitlines()
    suffix = f': {desc[0][:80]}' if desc else ''
    return f'- {skill.name} ({engine.skills.origin(skill.name)}){suffix}'


def _show_role(engine, name: str) -> str:
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
    return '\n'.join(lines)


def _show_team(engine, name: str) -> str:
    team = engine.teams.find(name)
    if team is None:
        return f'Error: unknown team "{name}"'
    lines = [f'{team.name} ({engine.teams.origin(name)})']
    if team.description:
        lines.append(f'description: {team.description}')
    if team.tags:
        lines.append(f'tags: {", ".join(team.tags)}')
    if not team.stages:
        lines.append('stages: (none)')
    for i, stage in enumerate(team.stages, 1):
        parts = [f'{i}. {stage.role}']
        if stage.mode:
            parts.append(f'mode={stage.mode}')
        lines.append(' '.join(parts))
        if stage.skills:
            lines.append(f'   skills: {", ".join(stage.skills)}')
        if stage.task_hint:
            lines.append(f'   task_hint: {stage.task_hint}')
        if stage.handoff_note:
            lines.append(f'   handoff_note: {stage.handoff_note}')
    return '\n'.join(lines)


def _show_skill(engine, name: str) -> str:
    skill = engine.skills.find(name)
    if skill is None:
        return f'Error: unknown skill "{name}"'
    return f'{skill.name} ({engine.skills.origin(name)})\n{skill.content}'


def _save_role(engine, name: str, values: dict) -> str:
    for field in ('tool_permission', 'grant_permission'):
        normalized, error = _normalize_permission_map(engine, values.get(field), field)
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


def _save_team(engine, name: str, values: dict) -> str:
    data = {'name': name}
    for field in ('description', 'tags', 'stages', 'loop'):
        if values.get(field) is not None:
            data[field] = values[field]
    engine.teams.put(Team.from_dict(data), scope='local')
    return f'Saved team: {name} (local)'


def _save_skill(engine, name: str, values: dict) -> str:
    skill = Skill(name=name,
                  content=str(values.get('content') or ''),
                  description=str(values.get('description') or ''),
                  tags=list(values.get('tags') or []))
    engine.skills.put(skill, scope='local')
    return f'Saved skill: {name} (local)'


def _validate(engine, kind: str, name: str, tool_permission,
              grant_permission, content, stages) -> str:
    errors: list[str] = []
    if not name:
        errors.append('name is required')
    if kind == 'role':
        saved = engine.roles.find(name) if name else None
        for field, value in (('tool_permission', tool_permission),
                             ('grant_permission', grant_permission)):
            if value is None and saved is not None:
                value = getattr(saved, field)
            _, error = _normalize_permission_map(engine, value, field)
            if error:
                errors.append(error)
    elif kind == 'team':
        stage_list = stages or []
        if not stage_list:
            errors.append('at least one stage is required')
        for i, stage in enumerate(stage_list, 1):
            role = str((stage or {}).get('role') or '')
            if not role:
                errors.append(f'stage {i} is missing a role')
            elif engine.roles.find(role) is None:
                errors.append(f'stage {i} role "{role}" is not in the catalog')
    elif kind == 'skill':
        if not content:
            errors.append('content is required')
    if errors:
        return f'Invalid {kind}: ' + '. '.join(errors)
    return f'{kind.capitalize()} "{name}" is valid.'


def register_catalog_tool(registry, engine) -> Callable:
    @registry.register(
        name='catalog',
        description=(
            "Manage the agent catalog: roles, teams, and skills. Use it to "
            "compose a team for a task, create the specialist roles and skills it "
            "needs, inspect what exists, validate a definition before saving, or "
            "remove local entries. Saving writes to the project catalog "
            "(.polyglav/) and reloads it, so a new role, team, or skill is usable "
            "in the same run. `tool_permission`/`grant_permission` take permission "
            f"keys ({_PERMISSION_KEY_LIST}), not tool categories; the category "
            "names write, exec, and search are accepted aliases for edit, bash, "
            "and web, and any other unknown key is rejected. A team is either a "
            "sequential pipeline whose stages run in order, or a hierarchical "
            "team whose manager allocates tasks to roles and validates outcomes. "
            "For a hierarchical team, make the manager stage 1 and let it call "
            "the worker roles, or call the manager role directly and let it call "
            "them. A stage's `role` names the role to run and its `skills` extend "
            "it for the stage. `loop` is a generate, check, correct loop with "
            "from, until, max_iterations, and verdict."
        ),
        parameters={
            'type': 'object',
            'properties': {
                'action': {
                    'type': 'string',
                    'enum': ['list', 'show', 'save', 'validate', 'remove',
                             'reload'],
                    'description': "list/show/save/validate/remove a kind, or "
                                   "reload the catalog from disk.",
                },
                'kind': {
                    'type': 'string',
                    'enum': ['role', 'team', 'skill'],
                    'description': 'Which catalog to act on.',
                },
                'name': {
                    'type': 'string',
                    'description': 'Entry name for show/save/remove.',
                },
                'system_prompt': {
                    'type': 'string',
                    'description': "Role: the role's system prompt.",
                },
                'model': {
                    'type': 'string',
                    'description': 'Role: optional model override.',
                },
                'skills': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': "Role: standing skill names. For a team "
                                   "stage use the stage's own skills field.",
                },
                'tags': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Role, team, or skill: grouping tags.',
                },
                'tool_permission': {
                    'type': 'object',
                    'description': 'Role: per-category permission overrides by key '
                                   '(' + _PERMISSION_KEY_LIST + ').',
                },
                'grant_permission': {
                    'type': 'object',
                    'description': 'Role: delegation ceiling for sub-agents, by the '
                                   'same permission keys.',
                },
                'ask_policy': {
                    'type': 'object',
                    'description': 'Role: ask routing by kind.',
                },
                'content': {
                    'type': 'string',
                    'description': 'Skill: the markdown instructions.',
                },
                'description': {
                    'type': 'string',
                    'description': 'Team or skill: a short description.',
                },
                'stages': {
                    'type': 'array',
                    'description': 'Team: ordered stages. A sequential team runs '
                                   'them in order. For a hierarchical team make '
                                   'stage 1 the manager and let it call the rest.',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'role': {'type': 'string'},
                            'mode': {'type': 'string'},
                            'task_hint': {'type': 'string'},
                            'handoff_note': {'type': 'string'},
                            'skills': {'type': 'array',
                                       'items': {'type': 'string'}},
                        },
                        'required': ['role'],
                    },
                },
                'loop': {
                    'type': 'object',
                    'description': 'Team: generate > check > correct loop. '
                                   'Properties: from (stage type), until '
                                   '(stage type), max_iterations, verdict '
                                   '(marker, default "VERDICT:").',
                    'properties': {
                        'from': {'type': 'string'},
                        'until': {'type': 'string'},
                        'max_iterations': {'type': 'integer'},
                        'verdict': {'type': 'string'},
                    },
                },
            },
            'required': ['action'],
        },
        category='catalog',
        permission='catalog',
        key_arg='name',
        short='Manage roles, teams, and skills',
        glyph='+',
        verb='Catalog',
        permission_fn=lambda args: _catalog_action(engine, args),
        write_actions=list(_CATALOG_WRITE_ACTIONS),
    )
    def catalog(action: str, kind: str = '', name: str = '',
                system_prompt: str | None = None, model: str | None = None,
                skills: list | None = None, tags: list | None = None,
                tool_permission: dict | None = None,
                grant_permission: dict | None = None,
                ask_policy: dict | None = None, content: str | None = None,
                description: str | None = None,
                stages: list | None = None,
                loop: dict | None = None) -> str:
        if action == 'reload':
            reloaded = engine.touch_catalogs()
            return f'Reloaded catalogs: {", ".join(reloaded) or "(none loaded)"}'
        if action not in ('list', 'show', 'save', 'validate', 'remove'):
            return 'Error: action must be list, show, save, validate, remove, or reload'
        if kind == 'type':
            kind = 'role'
        if kind not in ('role', 'team', 'skill'):
            return 'Error: kind must be role, team, or skill'
        if action == 'validate':
            return _validate(engine, kind, name, tool_permission,
                             grant_permission, content, stages)
        if action == 'list':
            if kind == 'role':
                return '\n'.join(_role_line(engine, t) for t in engine.roles.all())
            if kind == 'team':
                return '\n'.join(_team_line(engine, t) for t in engine.teams.all())
            return '\n'.join(_skill_line(engine, s) for s in engine.skills.all())
        if not name:
            return f'Error: name is required to {action} a {kind}'
        if action == 'show':
            if kind == 'role':
                return _show_role(engine, name)
            if kind == 'team':
                return _show_team(engine, name)
            return _show_skill(engine, name)
        if action == 'remove':
            if kind == 'role':
                registry = engine.roles
            elif kind == 'team':
                registry = engine.teams
            else:
                registry = engine.skills
            if registry.remove(name):
                engine.touch_catalogs()
                return f'Removed {kind}: {name} (local)'
            if registry.find(name) is not None:
                return (f'Error: {kind} "{name}" is not local - override it with '
                        f'save instead of remove')
            return f'Error: no local {kind} to remove: {name}'
        values = {'system_prompt': system_prompt, 'model': model,
                  'skills': skills, 'tags': tags,
                  'tool_permission': tool_permission,
                  'grant_permission': grant_permission,
                  'ask_policy': ask_policy, 'content': content,
                  'description': description, 'stages': stages,
                  'loop': loop}
        if kind == 'role':
            result = _save_role(engine, name, values)
        elif kind == 'team':
            result = _save_team(engine, name, values)
        else:
            result = _save_skill(engine, name, values)
        engine.touch_catalogs()
        return result
    return catalog
