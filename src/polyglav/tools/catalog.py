from typing import Callable

_CATALOG_WRITE_ACTIONS = ('save', 'remove', 'reload')

_PERMISSION_KEY_LIST = ('ask, bash, call, catalog, delegate, edit, list, '
                        'mcp, read, vcs, web')


def _catalog_action(engine, args: dict) -> str | None:
    action = str((args or {}).get('action') or '')
    if action in _CATALOG_WRITE_ACTIONS and engine._mode() != 'write':
        return 'deny'
    return None


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
            "and web, and any other unknown key is rejected. A team declares "
            "its type. A sequential team runs its stages in order and the caller "
            "is the manager. A hierarchical team names a manager and members, and "
            "the manager allocates tasks, validates outcomes, and returns the "
            "final answer. A stage's `role` names the role to run and its "
            "`skills` extend it for the stage. `loop` is a sequential generate, "
            "check, correct loop with from, until, max_iterations, and verdict."
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
                'callable': {
                    'type': 'string',
                    'enum': ['allow', 'ask', 'deny'],
                    'description': 'Role: whether other roles may call it. '
                                   'Default allow. This is separate from '
                                   'tool_permission.call, which controls whether '
                                   'the role may call others.',
                },
                'content': {
                    'type': 'string',
                    'description': 'Skill: the markdown instructions.',
                },
                'description': {
                    'type': 'string',
                    'description': 'Team or skill: a short description.',
                },
                'team_type': {
                    'type': 'string',
                    'enum': ['sequential', 'hierarchical'],
                    'description': 'Team: sequential stages with the caller as '
                                   'manager, or a hierarchical manager with '
                                   'members. Default sequential.',
                },
                'manager': {
                    'type': 'string',
                    'description': 'Team: the manager role for a hierarchical '
                                   'team.',
                },
                'members': {
                    'type': 'array',
                    'description': 'Team: roles the hierarchical manager may '
                                   'call. Not used by a sequential team.',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'role': {'type': 'string'},
                            'mode': {'type': 'string'},
                            'task_hint': {'type': 'string'},
                            'skills': {'type': 'array',
                                       'items': {'type': 'string'}},
                        },
                        'required': ['role'],
                    },
                },
                'stages': {
                    'type': 'array',
                    'description': 'Team: ordered stages for a sequential team. '
                                   'The caller is the manager. Not used by a '
                                   'hierarchical team.',
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
                    'description': 'Team: sequential generate > check > correct '
                                   'loop. Properties: from (stage role), until '
                                   '(stage role), max_iterations, verdict '
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
        param_aliases={'type': 'team_type', 'shape': 'team_type'},
    )
    def catalog(action: str, kind: str = '', name: str = '',
                system_prompt: str | None = None, model: str | None = None,
                skills: list | None = None, tags: list | None = None,
                tool_permission: dict | None = None,
                grant_permission: dict | None = None,
                ask_policy: dict | None = None, content: str | None = None,
                callable: str = '',
                description: str | None = None,
                stages: list | None = None,
                loop: dict | None = None,
                team_type: str = '', manager: str = '',
                members: list | None = None) -> str:
        if action == 'reload':
            reloaded = engine.touch_catalogs()
            return f'Reloaded catalogs: {", ".join(reloaded) or "(none loaded)"}'
        if action not in ('list', 'show', 'save', 'validate', 'remove'):
            return 'Error: action must be list, show, save, validate, remove, or reload'
        if kind == 'type':
            kind = 'role'
        adapter = engine.catalog.get(kind)
        if adapter is None:
            return 'Error: kind must be role, team, or skill'
        values = {'system_prompt': system_prompt, 'model': model,
                  'skills': skills, 'tags': tags,
                  'tool_permission': tool_permission,
                  'grant_permission': grant_permission,
                  'ask_policy': ask_policy, 'content': content,
                  'callable': callable,
                  'description': description, 'stages': stages,
                  'loop': loop, 'type': team_type, 'manager': manager,
                  'members': members}
        if action == 'validate':
            return adapter.validate(engine, name, values)
        if action == 'list':
            return adapter.list_entries(engine)
        if not name:
            return f'Error: name is required to {action} a {kind}'
        if action == 'show':
            return adapter.show(engine, name)
        if action == 'remove':
            return adapter.remove(engine, name)
        result = adapter.save(engine, name, values)
        engine.touch_catalogs()
        return result
    return catalog
