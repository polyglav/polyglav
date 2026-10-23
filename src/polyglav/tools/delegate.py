from typing import Callable

from ..config import verbosity_level


def _format_result(res) -> str:
    if res.status == 'error':
        msgs = '; '.join(e.get('message', '') for e in (res.errors or [])
                         if isinstance(e, dict) and e.get('message'))
        return f'Error: delegate failed: {msgs or "unknown error"}'
    content = (res.content or '').strip()
    if content:
        return f'[delegate] {content}'
    return '[delegate] (no content)'


def register_delegate_tool(registry, engine) -> Callable:
    @registry.register(
        name='delegate',
        description=(
            "Delegate a self-contained sub-task to an anonymous, role-less "
            "sibling agent and get its result back, to keep this run's context "
            "clean. The sibling inherits this run's mode and permission cap and "
            "cannot exceed the caller. Use it for reading, searching, or "
            "summarizing a self-contained piece of work. For a named specialist "
            "or a team use call."
        ),
        parameters={
            'type': 'object',
            'properties': {
                'task': {
                    'type': 'string',
                    'description': 'A self-contained task for the sibling to '
                                   'complete on its own.',
                },
                'skills': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Skill names to layer over the sibling for '
                                   'this run.',
                },
                'resume': {
                    'type': 'string',
                    'description': 'Resume an existing run or session so the '
                                   'sibling keeps its prior context: a run id '
                                   '(#3), a session id (#ab12cd), a session '
                                   'name, or session:<name>.',
                },
                'context': {
                    'type': 'string',
                    'enum': ['continue', 'compact', 'new'],
                    'description': 'How to treat a resumed context when resume '
                                   'is set: continue (append, default), compact '
                                   '(summarize first), or new (start fresh).',
                },
            },
            'required': ['task'],
        },
        category='delegate',
        permission='delegate',
        key_arg='task',
        short='Delegate a read-only sub-task to a sibling',
        glyph='↳',
        verb='Delegate',
        loop=True,
    )
    def delegate(task: str, skills: list | None = None, resume: str = '',
                 context: str = 'continue',
                 _config=None, _echo: bool = True) -> str:
        try:
            res = engine.run_subagent('', task, skills=skills, resume=resume,
                                      context=context)
        except ValueError as e:
            return f'Error: {e}'
        result = _format_result(res)
        if (_echo and _config is not None
                and verbosity_level(_config, 'subruns') != 'off'
                and not result.startswith('Error')):
            engine.ui.sub_result(result)
        return result
    return delegate
