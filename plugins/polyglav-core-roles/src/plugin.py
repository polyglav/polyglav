import importlib.util
import json
from pathlib import Path

from polyglav.role_model import Role

_spec = importlib.util.spec_from_file_location(
    'polyglav_core_roles_registry', Path(__file__).with_name('registry.py'))
_registry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_registry)
RoleRegistry = _registry.RoleRegistry
_catalog_spec = importlib.util.spec_from_file_location(
    'polyglav_core_roles_catalog', Path(__file__).with_name('catalog.py'))
_catalog = importlib.util.module_from_spec(_catalog_spec)
_catalog_spec.loader.exec_module(_catalog)
from polyglav.tools.call import register_call_tool


def register_services(services):
    services['role_registry'] = RoleRegistry


def register_catalog(catalog):
    catalog.register('role', _catalog)


def register_tools(registry):
    engine = getattr(registry, 'engine', None)
    if engine is not None:
        register_call_tool(registry, engine)


def register_commands(commands):
    chat = commands.chat_loop

    @commands.register(
        'roles', description='Manage roles', subcommands=[
            ('list', 'List roles (list <tag> filters by tag)'),
            ('show', 'Show a role definition'),
            ('new', 'Create or override a role (local)'),
            ('remove', 'Remove a role'),
        ])
    def roles_cmd(arg=''):
        tr = chat.roles
        parts = arg.strip().split(maxsplit=1)
        action = parts[0] if parts else ''
        if not action or action == 'list':
            tag = ''
            if action == 'list' and len(parts) > 1:
                tag = parts[1].strip()
            roles = tr.all()
            if tag:
                roles = [t for t in roles if tag in t.tags]
            if not roles:
                if tag:
                    print(f'  (no roles tagged "{tag}")')
                    known = ', '.join(sorted({t for t in tr.all()
                                              for t in t.tags}))
                    if known:
                        print(f'  known tags: {known}')
                else:
                    print('  (no roles configured)')
                    print('  Create one with /roles new <name>, or edit '
                          f'{tr.local_path}')
                return
            label = f' tagged "{tag}"' if tag else ''
            print(f'{len(roles)} roles{label}:')
            for t in roles:
                model = f' [{t.model}]' if t.model else ''
                tags = f' tags={",".join(t.tags)}' if t.tags else ''
                origin = f' ({tr.origin(t.name)})'
                print(f'  - {t.name}{model}{tags}{origin}')
            return
        if action == 'show':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /roles show <name>')
                return
            t = tr.find(name)
            if t is None:
                print(f'Role not found: {name}')
                return
            print(f'{t.name} ({tr.origin(t.name)})')
            if t.description:
                print(f'  description: {t.description}')
            print(f'  system_prompt: {t.system_prompt or "(empty)"}')
            if t.instructions:
                print(f'  instructions: {t.instructions}')
            if t.tags:
                print(f'  tags: {", ".join(t.tags)}')
            if t.model:
                print(f'  model: {t.model}')
            if t.skills:
                print(f'  skills: {", ".join(t.skills)}')
            if t.tool_permission:
                print('  tool_permission: '
                      + json.dumps(t.tool_permission))
            return
        if action == 'new':
            rest = parts[1].strip() if len(parts) > 1 else ''
            if not rest:
                print('Usage: /roles new <name> [system prompt]')
                return
            name = rest.split(maxsplit=1)[0]
            prompt = rest[len(name):].strip()
            existing = tr.find(name)
            prev_origin = tr.origin(name)
            tr.put(Role(name=name, system_prompt=prompt), scope='local')
            target = (tr.local_path.parent / 'roles' / f'{name}.md'
                      if prompt else tr.local_path)
            if existing is not None:
                print(f'Overrode role: {name} (was {prev_origin}) - '
                      f'edit {target}')
            else:
                print(f'Created role: {name} (local) - edit {target}')
            return
        if action == 'remove':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /roles remove <name>')
                return
            if tr.remove(name):
                print(f'Removed role: {name} (local)')
            else:
                print(f'No local role to remove: {name}')
            return
        print('Usage: /roles [list|show <name>|new <name> [prompt]|remove <name>]')

    @commands.register('role', description='Show the current role')
    def current_role_cmd(arg=''):
        engine = chat.active() if hasattr(chat, 'active') else chat
        role = str(getattr(engine, 'role', '') or '')
        session = getattr(engine.current_session, 'session_name', '')
        if role:
            print(f'Role: {role} ({session})')
        else:
            print(f'Role: root ({session})')
