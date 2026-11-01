import importlib.util
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
_added = False
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
    _added = True
try:
    import teams as _teams
    _spec = importlib.util.spec_from_file_location(
        'polyglav_core_teams_runner', SRC / 'runner.py')
    _runner = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_runner)
    _catalog_spec = importlib.util.spec_from_file_location(
        'polyglav_core_teams_catalog', SRC / 'catalog.py')
    _catalog = importlib.util.module_from_spec(_catalog_spec)
    _catalog_spec.loader.exec_module(_catalog)
finally:
    if _added:
        sys.path.remove(str(SRC))

Team = _teams.Team


def register_services(services):
    services['team_registry'] = _teams.TeamRegistry
    services['team_runner'] = _runner


def register_catalog(catalog):
    catalog.register('team', _catalog)


def register_commands(commands):
    chat = commands.chat_loop

    @commands.register(
        'teams', description='Manage teams', subcommands=[
            ('list', 'List teams (list <tag> filters by tag)'),
            ('show', 'Show a team definition'),
            ('new', 'Create or override a team (local)'),
            ('remove', 'Remove a team'),
            ('run', 'Run a team (run <name> <task>)'),
        ])
    def team_cmd(arg=''):
        tr = chat.teams
        parts = arg.strip().split(maxsplit=1)
        action = parts[0] if parts else ''
        if not action or action == 'list':
            tag = ''
            if action == 'list' and len(parts) > 1:
                tag = parts[1].strip()
            teams = tr.all()
            if tag:
                teams = [t for t in teams if tag in t.tags]
            if not teams:
                if tag:
                    print(f'  (no teams tagged "{tag}")')
                    known = ', '.join(sorted({t for t in tr.all()
                                              for t in t.tags}))
                    if known:
                        print(f'  known tags: {known}')
                else:
                    print('  (no teams configured)')
                    print('  Create one with /teams new <name>, or edit '
                          f'{tr.local_path}')
                return
            label = f' tagged "{tag}"' if tag else ''
            print(f'{len(teams)} teams{label}:')
            for t in teams:
                if getattr(t, 'type', 'sequential') == 'hierarchical':
                    chain = f'{t.manager or "(no manager)"} > ' + ' > '.join(
                        m.role for m in t.members)
                    kind = ' [hierarchical]'
                else:
                    chain = ' > '.join(s.role for s in t.stages)
                    kind = ''
                tags = f' tags={",".join(t.tags)}' if t.tags else ''
                origin = f' ({tr.origin(t.name)})'
                print(f'  - {t.name}{kind}{tags}{origin}')
                if chain:
                    print(f'      {chain}')
            return
        if action == 'show':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /teams show <name>')
                return
            t = tr.find(name)
            if t is None:
                print(f'Team not found: {name}')
                return
            print(f'{t.name} ({tr.origin(t.name)})')
            print(f'  type: {getattr(t, "type", "sequential")}')
            if t.description:
                print(f'  description: {t.description}')
            if t.tags:
                print(f'  tags: {", ".join(t.tags)}')
            if getattr(t, 'type', 'sequential') == 'hierarchical':
                print(f'  manager: {t.manager or "(none)"}')
                if not t.members:
                    print('  members: (none)')
                    return
                print('  members:')
                for i, m in enumerate(t.members, 1):
                    print(f'    {i}. {m.role}'
                          + (f' [mode={m.mode}]' if m.mode else ''))
                    if m.task_hint:
                        print(f'       task_hint: {m.task_hint}')
                return
            if not t.stages:
                print('  stages: (none)')
                return
            print('  stages:')
            for i, s in enumerate(t.stages, 1):
                print(f'    {i}. {s.role}'
                      + (f' [mode={s.mode}]' if s.mode else ''))
                if s.task_hint:
                    print(f'       task_hint: {s.task_hint}')
                if s.handoff_note:
                    print(f'       handoff_note: {s.handoff_note}')
            return
        if action == 'new':
            rest = parts[1].strip() if len(parts) > 1 else ''
            if not rest:
                print('Usage: /teams new <name> [description]')
                return
            name = rest.split(maxsplit=1)[0]
            description = rest[len(name):].strip()
            existing = tr.find(name)
            prev_origin = tr.origin(name)
            tr.put(Team(name=name, description=description), scope='local')
            if existing is not None:
                print(f'Overrode team: {name} (was {prev_origin}) - '
                      f'edit {tr.local_path} for stages')
            else:
                print(f'Created team: {name} (local) - edit {tr.local_path} '
                      'to add stages')
            return
        if action == 'remove':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /teams remove <name>')
                return
            if tr.remove(name):
                print(f'Removed team: {name} (local)')
            else:
                print(f'No local team to remove: {name}')
            return
        if action == 'run':
            rest = parts[1].strip() if len(parts) > 1 else ''
            name = rest.split(maxsplit=1)[0] if rest else ''
            task = rest[len(name):].strip() if name else ''
            if not name or not task:
                print('Usage: /teams run <name> <task>')
                return
            t = tr.find(name)
            if t is None:
                print(f'Team not found: {name}')
                return
            print(f'Running team {name} ({len(t.stages)} stages)')
            result = chat.run_team(t, task)
            for i, res in enumerate(result.stages, 1):
                dur = f' {res.duration:.1f}s' if res.duration else ''
                print(f'  {i}. {t.stages[i - 1].role:<16} {res.status}{dur}')
            if result.errors:
                msgs = [e.get('message', '') for e in result.errors
                        if isinstance(e, dict) and e.get('message')]
                if msgs:
                    print('  errors: ' + '; '.join(msgs))
            if result.content:
                print('--- final result ---')
                print(result.content)
            if result.memory:
                print(f'  team memory: {result.memory}')
            return
        print('Usage: /teams [list|show <name>|new <name> [description]|remove <name>|run <name> <task>]')
