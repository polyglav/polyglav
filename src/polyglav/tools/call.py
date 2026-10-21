from typing import Callable

from ..config import verbosity_level

_WRITE_PREFIXES = ('Created ', 'Overwritten ', 'Appended ')


def _call_action(engine, args: dict) -> str:
    role_name = (args or {}).get('role', '')
    entry = engine.roles.find(role_name)
    if entry is None:
        return 'deny'
    action = (entry.tool_permission or {}).get('call', 'allow')
    return action if action in ('allow', 'ask', 'deny') else 'allow'


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
        return f'Error: call to "{role_name}" failed: {msgs or "unknown error"}'
    content = (res.content or '').strip()
    if content:
        return f'[call {role_name}] {content}'
    summary = _summarize_session(engine, res)
    if summary:
        return f'[call {role_name}] (no final text; {summary})'
    return f'[call {role_name}] (no content)'


def register_call_tool(registry, engine) -> Callable:
    @registry.register(
        name='call',
        description=(
            "Bring in a named role as a sub-agent and return its final answer. "
            "A named role is write-class, so it is only available in write mode "
            "and the role's own permissions bound it. Use it for specialized work "
            "(research, writing, review), then continue from the returned result. "
            "For an anonymous read-only helper, use offload. To run a whole "
            "pipeline, use delegate."
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
        category='call',
        permission='call',
        key_arg='role',
        short='Run a task with a named role',
        glyph='↳',
        verb='Call',
        loop=True,
        permission_fn=lambda args: _call_action(engine, args),
    )
    def call(role: str, task: str, skills: list | None = None,
             resume: str = '', context: str = 'continue',
             _config=None, _echo: bool = True) -> str:
        try:
            res = engine.run_subagent(role, task, skills=skills,
                                      resume=resume, context=context)
        except ValueError as e:
            return f'Error: {e}'
        result = _format_result(engine, role, res)
        if (_echo and _config is not None
                and verbosity_level(_config, 'subruns') != 'off'
                and not result.startswith('Error')):
            engine.ui.sub_result(result)
        return result
    return call