from typing import Callable


_NO_ANSWER = ('[cancelled] No answer given - decide autonomously or return the '
              'question as an open item')
_NO_ONE = ('Error: ask has no one to answer (no interactive terminal) - '
           'decide autonomously or return the question as an open item')
_CLARITY_ERROR = ('Error: the ask question is too short to answer without '
                  'context. Ask a self-contained question, and include context '
                  'or options when the answerer needs them.')

_PERMISSION_OPTIONS = ['Approve once', 'Approve always', 'Deny']


def _permission_scope(answer: str) -> str:
    text = str(answer or '').strip().lower()
    if not text:
        return 'none'
    if 'always' in text:
        return 'always'
    if text.startswith(('y', 'yes', 'approve', 'grant', 'allow', 'ok')):
        return 'once'
    if text.startswith(('n', 'no', 'deny', 'decline', 'reject')):
        return 'deny'
    if text == '1':
        return 'once'
    if text == '2':
        return 'always'
    if text == '3':
        return 'deny'
    return 'none'


def _park(engine, question: str, context: str, options: list,
          kind: str, permission: str) -> str:
    store = getattr(engine, 'asks', None)
    if store is None:
        return _NO_ONE
    try:
        ask = store.add(question, engine.current_session.session_name,
                        context=context, options=options,
                        kind=kind, permission=permission)
    except Exception:
        return _NO_ONE
    return (f'[parked] Ask #{ask.id} parked for the user '
            f'(session {ask.origin}); continue or return the question '
            'as an open item')


def _permission_key(engine, permission: str) -> str:
    if permission in engine.permission_categories():
        return permission
    registry = getattr(engine, '_tool_registry', None)
    if registry is not None and registry.is_registered(permission):
        return registry.permission_for(permission)
    return permission


def _switch_write(engine) -> None:
    ui = getattr(engine, '_ask_ui', None)
    root = getattr(ui, '_loop', None) or engine
    engine.current_session.mode = 'write'
    root.current_session.mode = 'write'
    for target in {id(engine): engine, id(root): root}.values():
        try:
            target._init_tooling()
        except Exception:
            pass
    try:
        root.session_auto_save()
    except Exception:
        pass


def _prompt_permission(engine, question: str, context: str,
                       permission: str, key: str) -> str | None:
    ui = getattr(engine, '_ask_ui', None)
    if ui is None:
        return None
    answer = ui.ask(question, context=context or '',
                    options=list(_PERMISSION_OPTIONS),
                    origin=engine.role or engine.current_session.session_name)
    if not answer:
        return _NO_ANSWER
    scope = _permission_scope(answer)
    if scope in ('once', 'always'):
        engine.grant_permission(permission, key, scope=scope, origin='user')
        return f'[granted] Permission "{permission}" approved ({scope}).'
    if scope == 'deny':
        return f'[denied] Permission "{permission}" declined by the user.'
    return _NO_ANSWER


def _ask_permission(engine, question: str, context: str, options: list,
                    permission: str) -> str:
    key = _permission_key(engine, permission)
    mode = engine._mode() if hasattr(engine, '_mode') else 'write'
    from ..modes import is_write_key
    registry = getattr(engine, '_tool_registry', None)
    write_gated = registry is not None and key in registry.write_action_keys()
    if mode != 'write' and (is_write_key(engine.config, key) or write_gated):
        prompt = (f'Allow "{permission}"? This run needs write mode. {question}')
        ui = getattr(engine, '_ask_ui', None)
        if ui is not None:
            answer = ui.ask(prompt, context=context or '',
                            options=['Approve (switch to write)', 'Deny'],
                            origin=engine.role or engine.current_session.session_name)
            if answer and _permission_scope(answer) in ('once', 'always'):
                _switch_write(engine)
                return (f'[granted] Write mode enabled for this session - '
                        f'retry "{permission}".')
            return (f'[denied] Permission "{permission}" needs write mode, '
                    'which the user declined.')
        if engine._is_unattended():
            return _park(engine, prompt, context or '',
                         ['Approve (switch to write)', 'Deny'],
                         'permission', permission)
        return (f'[denied] Permission "{permission}" needs write mode. '
                "Request it with ask(kind='direction') to switch this session "
                'to write mode.')
    cap = engine._grant().get(key, 'deny')
    if cap == 'deny':
        return (f'[denied] Permission "{permission}" cannot be granted '
                '(above the delegation ceiling).')
    ask_policy = engine.config.get('ask_policy') or {}
    if str(ask_policy.get('permission', 'auto')) == 'deny':
        return f'[denied] Permission "{permission}" grants are disabled.'
    result = _prompt_permission(engine, question, context, permission, key)
    if result is not None:
        return result
    if engine._is_unattended():
        return _park(engine, question, context or '', options or [],
                     'permission', permission)
    return _NO_ONE


def _clarity_guard(engine, question: str, context: str,
                   options: list) -> str | None:
    limit = int(engine.config.get('ask_min_question_chars', 0) or 0)
    if limit <= 0:
        return None
    text = str(question or '').strip()
    if len(text) >= limit or context or options:
        return None
    return _CLARITY_ERROR


def _prompt_direction(engine, question: str, context: str,
                      options: list) -> str | None:
    ui = getattr(engine, '_ask_ui', None)
    if ui is None:
        return None
    answer = ui.ask(question, context=context or '', options=options or [],
                    origin=engine.role or engine.current_session.session_name)
    return answer or _NO_ANSWER


def _ask_direction(engine, question: str, context: str, options: list) -> str:
    if engine._is_unattended():
        return _park(engine, question, context or '', options or [],
                     'direction', '')
    result = _prompt_direction(engine, question, context, options)
    return result if result is not None else _NO_ONE


def register_ask_tool(registry, engine) -> Callable:
    @registry.register(
        name='ask',
        description=(
            "Ask the user a question and pause until it is answered, to get a "
            "decision or permission mid-run instead of leaving it open. For a "
            "permission request set kind='permission' and name the tool or "
            "category in permission; an approved request grants one use (or the "
            "rest of the run when the user grants it). Use it when a choice "
            "cannot be resolved from the task alone, then continue from the "
            "answer."
        ),
        parameters={
            'type': 'object',
            'properties': {
                'question': {
                    'type': 'string',
                    'description': 'The decision or permission request. Frame it so '
                                   'the answerer can resolve it from the question and '
                                   'context alone.',
                },
                'context': {
                    'type': 'string',
                    'description': 'Brief context the answerer needs that is not obvious '
                                   'from the question alone (current state, what was '
                                   'tried, the options under consideration).',
                },
                'options': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Suggested answers. The answerer picks one or gives '
                                   'their own.',
                },
                'kind': {
                    'type': 'string',
                    'enum': ['permission', 'direction'],
                    'description': "'direction' (default) asks for a decision or "
                                   "scope change. 'permission' requests a tool or "
                                   "category the run is not allowed to use.",
                },
                'permission': {
                    'type': 'string',
                    'description': "For kind='permission': the tool name or "
                                   "permission category to request.",
                },
            },
            'required': ['question'],
        },
        category='ask',
        permission='ask',
        key_arg='question',
        short='Ask the user for a decision',
        confirm=False,
        silent=True,
    )
    def ask(question: str, context: str = '', options: list | None = None,
            kind: str = 'direction', permission: str = '',
            _config=None) -> str:
        if kind == 'permission' and permission:
            return _ask_permission(engine, question, context or '',
                                   options or [], permission)
        guard = _clarity_guard(engine, question, context or '', options or [])
        if guard is not None:
            return guard
        return _ask_direction(engine, question, context or '', options or [])
    return ask
