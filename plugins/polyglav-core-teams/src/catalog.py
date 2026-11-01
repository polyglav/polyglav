def list_entries(engine) -> str:
    if engine.teams is None:
        return 'Error: teams plugin is not loaded'
    return '\n'.join(_team_line(engine, team) for team in engine.teams.all())


def _team_line(engine, team) -> str:
    if getattr(team, 'type', 'sequential') == 'hierarchical':
        kind = 'hierarchical'
        if team.members:
            chain = f'{team.manager or "(no manager)"} > ' + ' > '.join(
                member.role for member in team.members)
        else:
            chain = f'{team.manager or "(no manager)"} (no members)'
    else:
        kind = 'sequential'
        chain = ' > '.join(stage.role for stage in team.stages) or '(no stages)'
    tags = f' tags={",".join(team.tags)}' if team.tags else ''
    return (f'- {team.name} [{kind}]{tags} ({engine.teams.origin(team.name)}): '
            f'{chain}')


def show(engine, name: str) -> str:
    if engine.teams is None:
        return 'Error: teams plugin is not loaded'
    team = engine.teams.find(name)
    if team is None:
        return f'Error: unknown team "{name}"'
    lines = [f'{team.name} ({engine.teams.origin(name)})',
             f'type: {getattr(team, "type", "sequential")}']
    if team.description:
        lines.append(f'description: {team.description}')
    if team.tags:
        lines.append(f'tags: {", ".join(team.tags)}')
    if getattr(team, 'type', 'sequential') == 'hierarchical':
        lines.append(f'manager: {team.manager or "(none)"}')
        if not team.members:
            lines.append('members: (none)')
        for i, member in enumerate(team.members, 1):
            parts = [f'{i}. {member.role}']
            if member.mode:
                parts.append(f'mode={member.mode}')
            lines.append(' '.join(parts))
            if member.skills:
                lines.append(f'   skills: {", ".join(member.skills)}')
            if member.task_hint:
                lines.append(f'   task_hint: {member.task_hint}')
        return '\n'.join(lines)
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


def save(engine, name: str, values: dict) -> str:
    if engine.teams is None:
        return 'Error: teams plugin is not loaded'
    data = {'name': name, 'type': values.get('type') or 'sequential'}
    for field in ('description', 'tags', 'stages', 'loop', 'manager',
                  'members'):
        if values.get(field) is not None:
            data[field] = values[field]
    engine.teams.put(engine.teams.make(data), scope='local')
    return f'Saved team: {name} (local)'


def remove(engine, name: str) -> str:
    if engine.teams is None:
        return 'Error: teams plugin is not loaded'
    if engine.teams.remove(name):
        return f'Removed team: {name} (local)'
    if engine.teams.find(name) is not None:
        return (f'Error: team "{name}" is not local - override it with save '
                'instead of remove')
    return f'Error: no local team to remove: {name}'


def validate(engine, name: str, values: dict) -> str:
    errors: list[str] = []
    if not name:
        errors.append('name is required')
    shape = str(values.get('type') or 'sequential').strip().lower()
    if shape not in ('sequential', 'hierarchical'):
        errors.append('type must be sequential or hierarchical')
    stages = values.get('stages') or []
    manager = values.get('manager') or ''
    members = values.get('members') or []
    if shape == 'hierarchical':
        if not manager:
            errors.append('a hierarchical team needs a manager')
        elif engine.roles is None or engine.roles.find(manager) is None:
            errors.append(f'manager role "{manager}" is not in the catalog')
        if not members:
            errors.append('a hierarchical team needs at least one member')
        for i, member in enumerate(members, 1):
            role = str((member or {}).get('role') or '')
            if not role:
                errors.append(f'member {i} is missing a role')
            elif engine.roles is None or engine.roles.find(role) is None:
                errors.append(f'member {i} role "{role}" is not in the catalog')
        if stages:
            errors.append('a hierarchical team uses members, not stages')
    else:
        if not stages:
            errors.append('at least one stage is required')
        for i, stage in enumerate(stages, 1):
            role = str((stage or {}).get('role') or '')
            if not role:
                errors.append(f'stage {i} is missing a role')
            elif engine.roles is None or engine.roles.find(role) is None:
                errors.append(f'stage {i} role "{role}" is not in the catalog')
        if manager or members:
            errors.append('a sequential team uses stages, not manager or members')
    if errors:
        return 'Invalid team: ' + '. '.join(errors)
    return f'Team "{name}" is valid.'
