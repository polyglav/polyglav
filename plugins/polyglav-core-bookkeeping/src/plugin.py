import sys
from pathlib import Path

from polyglav.ui import DIM, RED, RESET

SRC = Path(__file__).resolve().parent
_added = False
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
    _added = True
try:
    import plan as _plan
    import todo as _todo
finally:
    if _added:
        sys.path.remove(str(SRC))


def register_services(services):
    from types import SimpleNamespace
    services['bookkeeping'] = SimpleNamespace(
        plan_context=_plan.plan_context,
        todo_context=_todo.todo_context)


def register_tools(registry):
    engine = getattr(registry, 'engine', None)
    if engine is not None:
        _plan.register_plan_tool(registry, engine)
        _todo.register_todo_tool(registry, engine)


def _run_todo(chat, args):
    chat._init_tooling()
    if not chat._tool_registry:
        return 'Error: tool calling is disabled'
    return chat._tool_registry.execute('todo', args)


def register_commands(commands):
    chat = commands.chat_loop

    @commands.register(
        'plan',
        description='Show, attach, or detach the internal plan for this session',
        subcommands=[
            ('use', 'Attach a plan file to this session'),
            ('off', 'Detach the plan from this session'),
        ])
    def plan_cmd(arg=''):
        display_path, plan_path, resolve_plan = (
            _plan.display_path, _plan.plan_path, _plan.resolve_plan)
        arg = arg.strip()
        session = chat.current_session
        if arg in ('off', 'detach'):
            session.plan = ''
            chat.session_auto_save()
            print(f'{DIM}@ Plan detached{RESET}')
            return
        if arg.startswith('use '):
            target = arg[4:].strip()
            path = resolve_plan(chat.config, target)
            if path is None:
                print(f'{RED}✗ Plan not found: {target}{RESET}')
                return
            session.plan = display_path(chat.config, path)
            chat.session_auto_save()
            print(f'{DIM}@ Plan attached: {session.plan}{RESET}')
            return
        if arg:
            print(f'{DIM}Usage: /plan [use <path>|off]{RESET}')
            return
        path = plan_path(chat.config, session, create=False)
        if path is None:
            print(f'{DIM}No plan for this session{RESET}')
            return
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            print(f'{RED}✗ Plan not readable: {display_path(chat.config, path)}{RESET}')
            return
        print(f'{DIM}@ {display_path(chat.config, path)}{RESET}')
        print(text.rstrip())

    @commands.register('plans', description='List stored plans, or show one')
    def plans_cmd(arg=''):
        display_path, list_plans, resolve_plan = (
            _plan.display_path, _plan.list_plans, _plan.resolve_plan)
        arg = arg.strip()
        if arg:
            path = resolve_plan(chat.config, arg)
            if path is None:
                print(f'{RED}✗ Plan not found: {arg}{RESET}')
                return
            print(f'{DIM}@ {display_path(chat.config, path)}{RESET}')
            print(path.read_text(encoding='utf-8', errors='replace').rstrip())
            return
        paths = list_plans(chat.config)
        if not paths:
            print(f'{DIM}No stored plans{RESET}')
            return
        current = str(chat.current_session.plan or '')
        current_stem = Path(current).stem
        for path in paths:
            label = f'  {path.stem}'
            if current_stem and path.stem == current_stem:
                label += '  <-- attached'
            print(label)

    @commands.register(
        'todo',
        description='Show or edit the internal todo for this session',
        subcommands=[
            ('add', 'Add a todo item'),
            ('block', 'Mark a todo item blocked'),
            ('done', 'Mark a todo item done'),
            ('list', 'Show the current todo'),
            ('remove', 'Remove a todo item'),
            ('start', 'Mark a todo item doing'),
        ])
    def todo_cmd(arg=''):
        todo_context = _todo.todo_context
        arg = arg.strip()
        if not arg:
            text = todo_context(chat.config, chat.current_session)
            print(text or f'{DIM}No todo for this session{RESET}')
            return
        action, _, rest = arg.partition(' ')
        rest = rest.strip()
        if action in ('list', 'show'):
            text = todo_context(chat.config, chat.current_session)
            print(text or f'{DIM}No todo for this session{RESET}')
            return
        if action == 'add':
            if not rest:
                print(f'{DIM}Usage: /todo add <title>{RESET}')
                return
            print(_run_todo(chat, {'action': 'add', 'title': rest}))
            return
        if action in ('start', 'done', 'block', 'remove'):
            parts = rest.split(maxsplit=1)
            if not parts or not parts[0].isdigit():
                print(f'{DIM}Usage: /todo {action} <id> [note]{RESET}')
                return
            args = {'action': action, 'id': int(parts[0])}
            if action == 'block' and len(parts) > 1:
                args['note'] = parts[1]
            print(_run_todo(chat, args))
            return
        print(f'{DIM}Usage: /todo [add <title>|start|done|block|remove <id>|list]{RESET}')

    @commands.register('todos', description='List stored todos, or show one')
    def todos_cmd(arg=''):
        list_todos, render_todo, resolve_todo = (
            _todo.list_todos, _todo.render_todo, _todo.resolve_todo)
        arg = arg.strip()
        if arg:
            path = resolve_todo(chat.config, arg)
            if path is None:
                print(f'{RED}✗ Todo not found: {arg}{RESET}')
                return
            print(render_todo(chat.config, path))
            return
        paths = list_todos(chat.config)
        if not paths:
            print(f'{DIM}No stored todos{RESET}')
            return
        current = chat.current_session.session_name
        for path in paths:
            label = f'  {path.stem}'
            if path.stem == current:
                label += '  <-- current'
            print(label)
