from typing import Callable


_ASK_SYSTEM = (
    'You are the lead agent coordinating delegated agents. A sub-agent asks you '
    'for a decision or permission. Answer concisely with just the decision, and '
    'add a one-line reason only if it helps. Do not ask questions back; commit '
    'to the decision the sub-agent needs.'
)

_PERMISSION_SYSTEM = (
    'You are the lead agent coordinating delegated agents. A sub-agent asks for '
    'permission to use a tool. Decide whether to grant one use. Answer with '
    '"yes" or "no" as the first word, and add a one-line reason only if it '
    'helps. Do not ask questions back; commit to the decision.'
)

_NO_ANSWER = ('[cancelled] No answer given - decide autonomously or return the '
              'question as an open item')
_NO_ONE = ('Error: ask has no one to answer (no lead agent and no interactive '
           'terminal) - decide autonomously or return the question as an open item')


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
    return (f'[parked] Ask #{ask.id} parked for the operator '
            f'(session {ask.origin}); continue or return the question '
            'as an open item')


def _task_preview(engine) -> str:
    for turn in engine.current_session.turns:
        for part in turn.get('parts') or []:
            if part.get('type') == 'user' and part.get('text'):
                text = str(part['text']).strip().replace('\n', ' ')
                return text[:500]
    return ''


def _lead_answer(engine, question: str, context: str, options,
                 system: str = _ASK_SYSTEM) -> str | None:
    lead = getattr(engine, '_lead', None)
    if lead is None:
        return None
    parts = [f'Question: {question}']
    if context:
        parts.append(f'Context: {context}')
    if options:
        parts.append('Options: ' + ' / '.join(options))
    task = _task_preview(engine)
    if task:
        parts.append(f'Delegated task: {task}')
    try:
        result = lead.provider.chat_nonstreaming(
            [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': '\n'.join(parts)},
            ],
            tools=None,
        )
    except Exception:
        return None
    content = result.get('content') if isinstance(result, dict) else None
    if not isinstance(content, str):
        return None
    content = content.strip()
    return content or None


def _permission_key(engine, permission: str) -> str:
    registry = getattr(engine, '_tool_registry', None)
    if registry is not None and registry.is_registered(permission):
        return registry.permission_for(permission)
    return permission


def _ceiling_for(engine) -> dict:
    lead = getattr(engine, '_lead', None)
    if lead is not None and hasattr(lead, '_grant'):
        return lead._grant()
    return engine._grant()


def _ask_permission(engine, question: str, context: str, options: list,
                    permission: str) -> str:
    key = _permission_key(engine, permission)
    cap = _ceiling_for(engine).get(key, 'deny')
    if cap == 'deny':
        return (f'[denied] Permission "{permission}" cannot be granted '
                '(above the delegation ceiling).')
    ask_policy = engine.config.get('ask_policy') or {}
    route = str(ask_policy.get('permission', 'auto'))
    if cap == 'ask':
        route = 'human'
    if route == 'deny':
        return f'[denied] Permission "{permission}" grants are disabled.'
    if route == 'human':
        ui = getattr(engine, '_ask_ui', None)
        if ui is not None:
            answer = ui.ask(question, context=context or '',
                            options=options or [],
                            origin=engine.current_session.session_name)
            if not answer:
                return _NO_ANSWER
            if answer.strip().lower().startswith('y'):
                scope = 'always' if 'always' in answer.lower() else 'once'
                engine.grant_permission(permission, key, scope=scope,
                                        origin='human')
                return f'[granted] Permission "{permission}" approved ({scope}).'
            return (f'[denied] Permission "{permission}" declined by the '
                    'operator.')
        if engine._is_unattended():
            return _park(engine, question, context or '', options or [],
                         'permission', permission)
    lead = getattr(engine, '_lead', None)
    if lead is not None:
        answer = _lead_answer(engine, question, context, options,
                              system=_PERMISSION_SYSTEM)
        if answer is None:
            return _NO_ONE
        if answer.strip().lower().startswith('y'):
            engine.grant_permission(permission, key, scope='once',
                                    origin='supervisor')
            return (f'[granted] Permission "{permission}" approved for one '
                    'use.')
        return f'[denied] Permission "{permission}" not approved by the lead.'
    return _NO_ONE


def register_ask_tool(registry, engine) -> Callable:
    @registry.register(
        name='ask',
        description=(
            "Ask a question and pause until it is answered, to get a decision or "
            "permission mid-run instead of leaving it open. With target='human' "
            "the operator answers at the terminal. With target='lead' the agent "
            "type or engine that delegated this run decides. For a permission "
            "request set kind='permission' and name the tool or category in "
            "permission; an approved request grants one use (or the rest of the "
            "run when the operator grants it). Use it when a choice cannot be "
            "resolved from the task alone, then continue from the answer."
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
                'target': {
                    'type': 'string',
                    'enum': ['human', 'lead'],
                    'description': "'human' asks the operator at the terminal (or the "
                                   "lead agent when headless). 'lead' asks the agent "
                                   "type or engine that delegated this run to decide.",
                },
                'kind': {
                    'type': 'string',
                    'enum': ['permission', 'direction'],
                    'description': "'direction' (default) asks for a decision or "
                                   "scope change. 'permission' requests a tool or "
                                   "category the sub-agent is not allowed to use.",
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
        short='Ask the human or the lead agent for a decision',
        confirm=False,
    )
    def ask(question: str, context: str = '', options: list | None = None,
            target: str = 'human', kind: str = 'direction',
            permission: str = '', _config=None) -> str:
        if kind == 'permission' and permission:
            return _ask_permission(engine, question, context or '',
                                   options or [], permission)
        ui = getattr(engine, '_ask_ui', None)
        lead = getattr(engine, '_lead', None)
        if target == 'lead':
            if lead is not None:
                answer = _lead_answer(engine, question, context or '', options or [])
                if answer is not None:
                    return answer
            if engine._is_unattended():
                return _park(engine, question, context or '', options or [],
                             'direction', '')
            if ui is not None:
                answer = ui.ask(question, context=context or '',
                                options=options or [],
                                origin=engine.current_session.session_name)
                return answer or _NO_ANSWER
            return _NO_ONE
        if engine._is_unattended():
            return _park(engine, question, context or '', options or [],
                         'direction', '')
        if ui is not None:
            answer = ui.ask(question, context=context or '',
                            options=options or [],
                            origin=engine.current_session.session_name)
            return answer or _NO_ANSWER
        if lead is not None:
            answer = _lead_answer(engine, question, context or '', options or [])
            if answer is not None:
                return answer
        return _NO_ONE
    return ask
