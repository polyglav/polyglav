def list_entries(engine) -> str:
    if engine.skills is None:
        return 'Error: skills plugin is not loaded'
    return '\n'.join(_skill_line(engine, skill) for skill in engine.skills.all())


def _skill_line(engine, skill) -> str:
    desc = (skill.description or '').strip().splitlines()
    suffix = f': {desc[0][:80]}' if desc else ''
    return f'- {skill.name} ({engine.skills.origin(skill.name)}){suffix}'


def show(engine, name: str) -> str:
    if engine.skills is None:
        return 'Error: skills plugin is not loaded'
    skill = engine.skills.find(name)
    if skill is None:
        return f'Error: unknown skill "{name}"'
    return f'{skill.name} ({engine.skills.origin(name)})\n{skill.content}'


def save(engine, name: str, values: dict) -> str:
    if engine.skills is None:
        return 'Error: skills plugin is not loaded'
    engine.skills.put(engine.skills.make(name, values), scope='local')
    return f'Saved skill: {name} (local)'


def remove(engine, name: str) -> str:
    if engine.skills is None:
        return 'Error: skills plugin is not loaded'
    if engine.skills.remove(name):
        return f'Removed skill: {name} (local)'
    if engine.skills.find(name) is not None:
        return (f'Error: skill "{name}" is not local - override it with save '
                'instead of remove')
    return f'Error: no local skill to remove: {name}'


def validate(engine, name: str, values: dict) -> str:
    errors: list[str] = []
    if not name:
        errors.append('name is required')
    if not values.get('content'):
        errors.append('content is required')
    if errors:
        return 'Invalid skill: ' + '. '.join(errors)
    return f'Skill "{name}" is valid.'
