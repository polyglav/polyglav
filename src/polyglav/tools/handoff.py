from __future__ import annotations

from typing import Callable


_NO_FOCUS = ('Error: handoff is only available in the REPL focus session - '
             'a delegated sub-agent has no one to hand control to')


def _manager(engine):
    return getattr(engine, '_focus', None) or getattr(engine, 'focus', None)


def _target_run(runs, current, target: str):
    low = target.lower()
    if low == 'parent':
        if current is None or current.parent is None:
            return None
        return runs.get(current.parent)
    if low == 'child':
        if current is None:
            return None
        kids = runs.children(current.id)
        return kids[0] if kids else None
    if low == 'sibling':
        if current is None or current.parent is None:
            return None
        sibs = [r for r in runs.children(current.parent) if r.id != current.id]
        return sibs[0] if sibs else None
    explicit = target.startswith('#')
    token = target[1:] if explicit else target
    if token.isdigit():
        return runs.get(int(token))
    if explicit:
        return runs.find_by_session_id(token)
    for run in runs.runs():
        if run.session == target:
            return run
    return None


def register_handoff_tool(registry, engine) -> Callable:
    @registry.register(
        name='handoff',
        description=(
            "Hand control of the session to another run and pause or finish the "
            "current one. Use it when the next step belongs to a different run: "
            "target is 'parent', 'child', 'sibling', 'root', a run id like '#3', "
            "a session id like '#ab12cd', or a session name. Set done=true to "
            "finish this run, otherwise it is left paused so the operator can "
            "resume it. The operator's focus follows the target run."
        ),
        parameters={
            'type': 'object',
            'properties': {
                'target': {
                    'type': 'string',
                    'description': "Where to hand control: 'parent', 'child', "
                                   "'sibling', 'root', a run id ('3' or '#3'), "
                                   "a session id ('#ab12cd'), or a session name.",
                },
                'done': {
                    'type': 'boolean',
                    'description': 'True to finish the current run, false (default) '
                                   'to leave it paused for a later resume.',
                },
            },
            'required': ['target'],
        },
        category='handoff',
        permission='handoff',
        key_arg='target',
        short='Hand control to another run and pause this one',
        glyph='→',
        verb='Handoff',
    )
    def handoff(target: str, done: bool = False, _config=None) -> str:
        focus = _manager(engine)
        if focus is None:
            return _NO_FOCUS
        target = str(target or '').strip()
        if not target:
            return 'Error: handoff needs a target'
        runs = engine.runs
        current = getattr(engine, 'current_run', None)
        if target.lower() == 'root':
            run = focus.root.current_run
        else:
            run = _target_run(runs, current, target)
        if run is None:
            return f'Error: handoff target not found: {target}'
        role = run.role or ''
        label = f'#{run.id} {role or "root"}'
        if current is not None:
            runs.finish(current.id, 'done' if done else 'paused')
        focus.root._pending_handoff = {'run': run.id}
        state = 'finished' if done else 'paused'
        return (f'[handoff] Control handed to {label}. This run is {state}; '
                'the operator is now focused there.')
    return handoff
