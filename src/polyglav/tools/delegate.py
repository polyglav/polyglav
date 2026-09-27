from typing import Callable

_WRITE_PREFIXES = ('Created ', 'Overwritten ', 'Appended ')

_FOCUS_MODES = ('off', 'ask', 'on')


def _delegate_action(engine, args: dict) -> str:
    role_name = (args or {}).get('role', '')
    entry = engine.roles.find(role_name)
    if entry is None:
        return 'deny'
    action = (entry.tool_permission or {}).get('delegate', 'allow')
    return action if action in ('allow', 'ask', 'deny') else 'allow'


def _focus_manager(engine):
    return getattr(engine, '_focus', None) or getattr(engine, 'focus', None)


def _focus_mode(config) -> str:
    value = str((config.get('focus_on_delegate') if config else 'off') or 'off')
    value = value.strip().lower()
    return value if value in _FOCUS_MODES else 'off'


def _offer_focus(engine, run_id, config) -> str:
    if run_id is None:
        return ''
    mode = _focus_mode(config)
    if mode == 'off':
        return ''
    focus = _focus_manager(engine)
    if focus is None:
        return ''
    run = engine.runs.get(run_id)
    role = (run.role if run is not None else '') or 'agent'
    label = f'{role} #{run_id}'
    if mode == 'ask':
        if engine._is_unattended():
            return ''
        if not engine.ui.confirm('focus_on_delegate', f'Focus on {label}'):
            return ''
    focus.root._pending_focus = {'run': run_id}
    return f' [focus follows: {label}]'


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


def _format_result(engine, role_name: str, res) -> str:
    if res.status == 'error':
        msgs = '; '.join(e.get('message', '') for e in (res.errors or []) if e.get('message'))
        return f'Error: delegated task failed: {msgs or "unknown error"}'
    content = (res.content or '').strip()
    if content:
        return f'[delegate {role_name}] {content}'
    summary = _summarize_session(engine, res)
    if summary:
        return f'[delegate {role_name}] (no final text; {summary})'
    return f'[delegate {role_name}] (no content)'


def _sub_footer(engine, res):
    counts = {}
    usage = res.usage if isinstance(res.usage, dict) else None
    comp = usage.get('completion_tokens') if usage else None
    if isinstance(comp, int) and comp > 0:
        counts['out'] = comp
    note = ' '.join(p for p in (getattr(res, 'status', ''), res.session) if p)
    engine.ui.footer(res.duration, counts, note=note)


def register_delegate_tool(registry, engine) -> Callable:
    @registry.register(
        name='delegate',
        description=(
            "Run a task with a role as a sub-agent and return its final answer. "
            "The sub-agent runs in its own session under the role's system prompt "
            "and permissions. Use it for specialized work (research, writing, review), "
            "then continue from the returned result."
        ),
        parameters={
            'type': 'object',
            'properties': {
                'role': {
                    'type': 'string',
                    'description': 'Name of the role to delegate to',
                },
                'task': {
                    'type': 'string',
                    'description': 'Task for the sub-agent to complete',
                },
                'skills': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Skill names to add to the role for '
                                   'this run, layered over the role\'s own '
                                   'skills. Use it to extend a reusable agent '
                                   'with task, technology, stack, or framework '
                                   'instructions.',
                },
                'resume': {
                    'type': 'string',
                    'description': 'Resume an existing run or session so the '
                                   'agent keeps its prior context: a run id '
                                   '(#3), a session id (#ab12cd), a session name, '
                                   'or session:<name>. Omit for a fresh one-off '
                                   'session.',
                },
                'context': {
                    'type': 'string',
                    'enum': ['continue', 'compact', 'new'],
                    'description': 'How to treat a resumed context when resume '
                                   'is set: continue (append, default), compact '
                                   '(summarize first), or new (ignore resume and '
                                   'start fresh).',
                },
            },
            'required': ['role', 'task'],
        },
        category='delegate',
        permission='delegate',
        key_arg='role',
        short='Run a task with a role',
        glyph='↳',
        verb='Delegate',
        loop=True,
        permission_fn=lambda args: _delegate_action(engine, args),
    )
    def delegate(role: str, task: str, skills: list | None = None,
                 resume: str = '', context: str = 'continue',
                 _config=None, _echo: bool = True) -> str:
        try:
            res = engine.run_subagent(role, task, skills=skills,
                                      resume=resume, context=context)
        except ValueError as e:
            return f'Error: {e}'
        result = _format_result(engine, role, res)
        if not result.startswith('Error'):
            result += _offer_focus(engine, res.run_id, _config)
        if (_echo and _config is not None and _config.get('delegate_echo', True)
                and not result.startswith('Error')):
            engine.ui.tool_result(result)
            _sub_footer(engine, res)
        return result
    return delegate