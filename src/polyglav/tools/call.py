from typing import Callable


_WRITE_PREFIXES = ('Created ', 'Overwritten ', 'Appended ')
_RANK = {'deny': 0, 'ask': 1, 'allow': 2}


def _callable_action(entry) -> str:
    if entry is None:
        return 'deny'
    action = getattr(entry, 'callable', 'allow') or 'allow'
    return action if action in _RANK else 'allow'


def _role_action(engine, role_name: str) -> str:
    entry = engine.roles.find(role_name)
    return _callable_action(entry)


def _team_action(engine, team) -> str:
    if getattr(team, 'type', 'sequential') == 'hierarchical':
        manager = engine.roles.find(team.manager)
        if manager is None:
            return 'deny'
        target = _callable_action(manager)
        if target == 'deny':
            return 'deny'
        action = (manager.tool_permission or {}).get('call', 'allow')
        if action not in _RANK:
            action = 'allow'
        if action == 'deny':
            return 'deny'
        if action == 'ask' or target == 'ask':
            action = 'ask'
        for member in team.members:
            entry = engine.roles.find(member.role)
            if _callable_action(entry) == 'deny':
                return 'deny'
        return action
    action = 'allow'
    for stage in team.stages:
        entry = engine.roles.find(stage.role)
        target = _callable_action(entry)
        if target == 'deny':
            return 'deny'
        if target == 'ask':
            action = 'ask'
    return action


def _resolve_target(engine, target: str, kind: str = 'auto') -> tuple[str | None, str]:
    text = str(target or '').strip()
    kind = str(kind or 'auto').strip().lower()
    if kind == 'team' or text.startswith('team:'):
        name = text.split(':', 1)[1].strip() if text.startswith('team:') else text
        return ('team', name) if engine.teams.find(name) is not None else (None, name)
    if kind == 'role' or text.startswith('role:'):
        name = text.split(':', 1)[1].strip() if text.startswith('role:') else text
        return ('role', name) if engine.roles.find(name) is not None else (None, name)
    if engine.roles.find(text) is not None:
        return 'role', text
    if engine.teams.find(text) is not None:
        return 'team', text
    return None, text


def _target_action(engine, args: dict) -> str:
    args = args or {}
    target = args.get('target') or args.get('role') or args.get('name') or ''
    kind, name = _resolve_target(engine, target, args.get('kind', 'auto'))
    if kind == 'role':
        return _role_action(engine, name)
    if kind == 'team':
        team = engine.teams.find(name)
        return _team_action(engine, team) if team is not None else 'deny'
    return 'deny'


def _summarize_session(engine, result) -> str:
    session = engine.sessions.read(result.session) if result.session else None
    if session is None:
        return ''
    tool_parts = [p for t in session.turns for p in t.get('parts') or []
                  if p.get('type') == 'tool']
    files: list[str] = []
    last_command = ''
    for part in tool_parts:
        text = (part.get('output') or '').strip()
        if not text:
            continue
        name = part.get('name')
        if name in ('file_write', 'write_file', 'write'):
            head = text.splitlines()[0]
            for prefix in _WRITE_PREFIXES:
                if head.startswith(prefix):
                    files.append(head[len(prefix):].split(' (')[0])
                    break
        elif name in ('bash', 'run_command', 'exec'):
            last_command = text.splitlines()[0][:80]
    parts = []
    if tool_parts:
        parts.append(f'{len(tool_parts)} tool calls')
    if files:
        shown = ', '.join(files[:5])
        more = f' (+{len(files) - 5} more)' if len(files) > 5 else ''
        parts.append(f'wrote: {shown}{more}')
    if not parts:
        parts.append('no tool activity recorded')
    summary = '; '.join(parts)
    if last_command:
        summary += f'; last bash: {last_command}'
    if len(summary) > 320:
        summary = summary[:320].rsplit(',', 1)[0] + '...'
    return summary


def _team_result_role(engine, name: str) -> str:
    team = engine.teams.find(name)
    if team is None:
        return ''
    if getattr(team, 'type', 'sequential') == 'hierarchical':
        return team.manager
    if team.stages:
        return team.stages[-1].role
    return ''


def _format_result(engine, kind: str, name: str, res) -> str:
    label = name or 'target'
    if res.status == 'error':
        msgs = '; '.join(
            e.get('message', '') for e in (res.errors or [])
            if isinstance(e, dict) and e.get('message'))
        if kind == 'team':
            return f'Error: team "{label}" failed: {msgs or "unknown error"}'
        return f'Error: call to "{label}" failed: {msgs or "unknown error"}'
    content = (res.content or '').strip()
    if content:
        return f'[call {label}] {content}'
    if kind == 'role':
        summary = _summarize_session(engine, res)
        if summary:
            return f'[call {label}] (no final text; {summary})'
    return f'[call {label}] (no content)'


def register_call_tool(registry, engine) -> Callable:
    @registry.register(
        name='call',
        description=(
            "Call a named role or a named team and return its final answer. "
            "`target` names a role or a team. A role or team is write-class, "
            "and its own permissions bound it. Use `kind` to disambiguate a "
            "name that is both a role and a team. For anonymous read-only "
            "help use delegate."
        ),
        parameters={
            'type': 'object',
            'properties': {
                'target': {
                    'type': 'string',
                    'description': 'Role name or team name.',
                },
                'kind': {
                    'type': 'string',
                    'enum': ['auto', 'role', 'team'],
                    'description': 'How to read the target. Auto prefers a role, '
                                   'then a team.',
                },
                'task': {
                    'type': 'string',
                    'description': 'Task for the target to complete',
                },
                'skills': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Skill names to add for this run, layered over '
                                   'the target\'s own skills.',
                },
                'resume': {
                    'type': 'string',
                    'description': 'Resume an existing run or session so the '
                                   'target keeps its prior context: a run id '
                                   '(#3), a session id (#ab12cd), a session name, '
                                   'or session:<name>.',
                },
                'context': {
                    'type': 'string',
                    'enum': ['continue', 'compact', 'new'],
                    'description': 'How to treat a resumed context when resume '
                                   'is set: continue (append, default), compact '
                                   '(summarize first), or new (start fresh).',
                },
            },
            'required': ['target', 'task'],
        },
        category='call',
        permission='call',
        key_arg='target',
        param_aliases={'role': 'target', 'name': 'target'},
        short='Call a role, team, or sibling',
        glyph='↳',
        verb='Call',
        loop=True,
        permission_fn=lambda args: _target_action(engine, args),
    )
    def call(target: str, task: str, skills: list | None = None,
             resume: str = '', context: str = 'continue', kind: str = 'auto',
             _config=None, _echo: bool = True) -> str:
        resolved, name = _resolve_target(engine, target, kind)
        if resolved is None:
            return f'Error: unknown call target "{target}"'
        try:
            if resolved == 'role':
                res = engine.run_subagent(name, task, skills=skills,
                                          resume=resume, context=context)
            elif resolved == 'team':
                team = engine.teams.find(name)
                if team is None:
                    return f'Error: unknown team "{name}"'
                if getattr(team, 'type', 'sequential') == 'hierarchical':
                    if not team.manager:
                        return f'Error: team "{name}" has no manager'
                    if not team.members:
                        return f'Error: team "{name}" has no members'
                elif not team.stages:
                    return f'Error: team "{name}" has no stages'
                res = engine.run_team(team, task, skills=skills,
                                      resume=resume, context=context)
            else:
                return f'Error: unknown call target "{target}"'
        except ValueError as e:
            return f'Error: {e}'
        result = _format_result(engine, resolved, name, res)
        if (_echo and not result.startswith('Error')
                and not getattr(res, 'streamed', False)):
            role = name if resolved == 'role' else _team_result_role(engine, name)
            if engine.ui.output_visible(role):
                engine.ui.sub_result(result, role=role)
        return result
    return call
