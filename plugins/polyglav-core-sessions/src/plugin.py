import importlib.util
import json
import sys
from pathlib import Path

from polyglav.config import Config

_render_path = Path(__file__).with_name('render.py')
_spec = importlib.util.spec_from_file_location(
    'polyglav_core_sessions_render', _render_path)
_render = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_render)
render_session = _render.render_session
render_session_tree = _render.render_session_tree
render_turn = _render.render_turn
session_to_json = _render.session_to_json
session_tree_to_json = _render.session_tree_to_json
turn_summary = _render.turn_summary
export_document = _render.export_document


def _live_session_for_run(chat, run_id):
    current = getattr(chat, 'current_run', None)
    if current is not None and current.id == run_id:
        return chat.current_session
    return None


def _target_session(chat, target):
    target = (target or '').strip()
    if not target:
        return None, 'Target not found: (empty)'
    if target.lower().startswith('session:'):
        name = target.split(':', 1)[1].strip()
        session = chat.sessions.read(name)
        return (session, '') if session is not None else _target_error(target)
    explicit = target.startswith('#')
    token = target[1:] if explicit else target
    run = chat.runs.get(int(token)) if token.isdigit() else None
    if run is None and explicit:
        run = chat.runs.find_by_session_id(token)
    if run is not None:
        session = _live_session_for_run(chat, run.id) or \
            chat.sessions.read(run.session)
        return (session, '') if session is not None else _target_error(target)
    if explicit:
        session = chat.sessions.find_by_session_id(token)
        return (session, '') if session is not None else _target_error(target)
    for run in chat.runs.runs():
        if run.role != target and run.session != target:
            continue
        session = chat.sessions.read(run.session)
        return (session, '') if session is not None else _target_error(target)
    session = chat.sessions.read(target)
    return (session, '') if session is not None else _target_error(target)


def _target_error(target):
    return None, f'Target not found: {target}'


HISTORY_DEFAULT_LIMIT = 10
HISTORY_USAGE = ('Usage: /history [N|N-O|-O|N-|all] '
                 '[session:<name> ...] [--thoughts [all]] [--tree]')


def _parse_history(arg):
    import shlex
    thoughts: bool | str = False
    session_target = ''
    tree = False
    positional: list[str] = []
    tokens = shlex.split(arg)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == '--thoughts':
            thoughts = True
            if i + 1 < len(tokens) and tokens[i + 1] == 'all':
                thoughts = 'all'
                i += 2
                continue
            i += 1
        elif tok == '--tree':
            tree = True
            i += 1
        else:
            positional.append(tok)
            i += 1
    if len(positional) > 2:
        return '', '', None, False, HISTORY_USAGE
    if positional and positional[0].startswith('session:'):
        session_target = positional[0].split(':', 1)[1].strip()
        if not session_target:
            return '', '', None, False, HISTORY_USAGE
        spec = positional[1] if len(positional) > 1 else ''
    else:
        spec = positional[0] if positional else ''
        if len(positional) > 1:
            return '', '', None, False, HISTORY_USAGE
    return spec, session_target, thoughts, tree, ''


PRINT_USAGE = ('Usage: /print [N|N-O|-O|N-|N.M] '
               '[session:<name> [N|N-O|-O|N-]] [--full] [--tree]')


def _parse_print(arg):
    import shlex
    spec = ''
    session_target = ''
    full = False
    tree = False
    positional: list[str] = []
    tokens = shlex.split(arg)
    for tok in tokens:
        if tok == '--full':
            full = True
        elif tok == '--tree':
            tree = True
        else:
            positional.append(tok)
    if len(positional) > 2:
        return None, None, None, False, PRINT_USAGE
    if positional and positional[0].startswith('session:'):
        session_target = positional[0].split(':', 1)[1].strip()
        if not session_target:
            return None, None, None, False, PRINT_USAGE
        spec = positional[1] if len(positional) > 1 else ''
    elif positional:
        spec = positional[0]
        if len(positional) > 1:
            return None, None, None, False, PRINT_USAGE
    if not spec and not tree:
        return None, None, None, False, PRINT_USAGE
    return spec, full, session_target, tree, ''


def _turn_indices(spec, total):
    if not spec:
        return [], ''
    text = spec[1:] if spec.startswith('#') else spec
    if text == 'all':
        return list(range(1, total + 1)), ''
    if '.' in text and not text.startswith('-') and not text.endswith('-'):
        n, _, rest = text.partition('.')
        if n.isdigit() and rest.isdigit():
            return [int(n)], ''
        return [], f'Invalid turn: {spec}'
    if text.startswith('-') and text[1:].isdigit():
        count = int(text[1:])
        if count <= 0:
            return [], f'Invalid range: {spec}'
        start = max(1, total - count + 1)
        return list(range(start, total + 1)), ''
    if text.endswith('-') and text[:-1].isdigit():
        start = int(text[:-1])
        if start <= 0 or start > total:
            return [], f'Turn out of range: {spec}'
        return list(range(start, total + 1)), ''
    if '-' in text:
        left, _, right = text.partition('-')
        if left.isdigit() and right.isdigit():
            start, end = int(left), int(right)
            if start <= 0 or end < start or start > total:
                return [], f'Turn out of range: {spec}'
            return list(range(start, min(end, total) + 1)), ''
        return [], f'Invalid range: {spec}'
    if text.isdigit():
        n = int(text)
        if n <= 0 or n > total:
            return [], f'Turn out of range: {spec}'
        return [n], ''
    return [], f'Invalid turn: {spec}'


def _parse_turn_ref(spec):
    token = spec[1:] if spec.startswith('#') else spec
    pieces = token.split('.', 1)
    n_str = pieces[0]
    m_str = pieces[1] if len(pieces) > 1 else ''
    if not n_str.isdigit() or int(n_str) <= 0:
        return None, None, f'Invalid turn: {spec}'
    m = None
    if m_str:
        if not m_str.isdigit() or int(m_str) <= 0:
            return None, None, f'Invalid part: {spec}'
        m = int(m_str)
    return int(n_str), m, ''


def register_commands(commands):
    registry = commands
    chat = commands.chat_loop

    @registry.register('sessions', description='List or manage saved sessions', subcommands=[
        ('list', 'List saved sessions'),
        ('preview', 'Show a structural preview of a session'),
        ('delete', 'Delete a session'),
        ('export', 'Export a session to Markdown or JSON'),
        ('import', 'Import a session from a JSON export'),
    ])
    def sessions_cmd(arg=''):
        parts = arg.strip().split(maxsplit=2)
        action = parts[0] if parts else ''

        if not action or action == 'list':
            sessions = [s for s in chat.sessions.list()
                        if not s.startswith('sub_')]
            if sessions:
                current = chat.sessions.current.session_name if chat.sessions.current else ''
                for s in sessions:
                    marker = '  <-- current' if s == current else ''
                    print(f'  {s}{marker}')
            else:
                print('  No sessions found')
            return
        if action == 'preview':
            name = parts[1] if len(parts) > 1 else ''
            if not name:
                print('Usage: /sessions preview <name>')
                return
            s = chat.preview_session(name)
            if s is None:
                print(f'Session not found: {name}')
        elif action == 'delete':
            name = parts[1] if len(parts) > 1 else ''
            if not name:
                print('Usage: /sessions delete <name>')
                return
            if chat.sessions.delete(name):
                print(f'Deleted session: {name}')
            else:
                print(f'Session not found: {name}')
        elif action == 'export':
            tree = '--tree' in arg.split()
            tokens = [t for t in arg.strip().split()[1:]
                      if t not in ('--json', '--tree')]
            as_json = '--json' in arg.split()
            name = tokens[0] if tokens else ''
            out = tokens[1] if len(tokens) > 1 else ''
            if not name:
                print('Usage: /sessions export <name> [out] [--json] [--tree]')
                return
            s = chat.sessions.read(name)
            if s is None:
                print(f'Session not found: {name}')
                return
            ext = '.json' if as_json else '.md'
            if tree:
                nodes = chat.sessions.tree(name)
                content = (session_tree_to_json(nodes) if as_json
                           else render_session_tree(nodes))
                default = f'{name}_tree{ext}'
            else:
                content = session_to_json(s) if as_json else render_session(s)
                default = f'{name}{ext}'
            if out == '-':
                sys.stdout.write(content)
                return
            if out:
                path = Path(out)
            else:
                path = (chat.sessions.sessions_dir.parent / 'exports'
                        / default)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            print(f'Exported session: {name} -> {path}')
        elif action == 'import':
            tokens = [t for t in arg.strip().split()[1:] if t != '--force']
            force = '--force' in arg.split()
            file = tokens[0] if tokens else ''
            name = tokens[1] if len(tokens) > 1 else ''
            if not file:
                print('Usage: /sessions import <file> [name] [--force]')
                return
            try:
                data = json.loads(Path(file).read_text())
            except (OSError, json.JSONDecodeError) as e:
                print(f'Cannot read session file: {e}')
                return
            try:
                s = chat.sessions.import_document(data, name=name,
                                                  force=force)
            except ValueError as e:
                print(str(e))
                return
            print(f'Imported session: {s.session_name}')
        else:
            print('Usage: /sessions [list|preview|delete|export|import]')

    @registry.register('history',
                       description='List the session turns as a numbered index '
                                   '(/history [N|N-O|-O|N-|all] '
                                   '[session:<name> ...] [--thoughts [all]] '
                                   '[--tree])')
    def history_cmd(arg=''):
        spec, session_target, thoughts, tree, error = _parse_history(arg)
        if error:
            print(error)
            return
        session = chat.current_session
        if session_target:
            session, error = _target_session(chat, session_target)
            if session is None:
                print(error)
                return

        def shown_turns(turns):
            if not spec:
                return turns[-HISTORY_DEFAULT_LIMIT:] if len(turns) > HISTORY_DEFAULT_LIMIT else turns
            indices, err = _turn_indices(spec, len(turns))
            if err:
                return err
            wanted = set(indices)
            return [t for t in turns if t.get('index') in wanted]

        if tree:
            for depth, item in chat.sessions.tree(session.session_name):
                role = f' [{item.role}]' if item.role else ''
                print(f'{"  " * depth}{item.session_name} - '
                      f'{len(item.turns)} turns{role}')
                shown = shown_turns(item.turns)
                if isinstance(shown, str):
                    print(shown)
                    continue
                for turn in shown:
                    print(f'{"  " * (depth + 1)}'
                          f'{turn_summary(turn, thoughts=thoughts)}')
            return
        turns = session.turns or []
        shown = shown_turns(turns)
        if isinstance(shown, str):
            print(shown)
            return
        role = f' [{session.role}]' if session.role else ''
        session_id = f' [{session.session_id}]' if session.session_id else ''
        print(f'{session.session_name} - {len(turns)} turns{role}{session_id}')
        for turn in shown:
            print(turn_summary(turn, thoughts=thoughts))
        print('/print <n> reprints a turn')

    @registry.register('print',
                       description='Reprint turns - /print [N|N-O|-O|N-|N.M] '
                                   '[session:<name> ...] [--full] [--tree]')
    def print_cmd(arg=''):
        spec, full, session_target, tree, error = _parse_print(arg)
        if error:
            print(error)
            return
        session = chat.current_session
        if session_target:
            session, error = _target_session(chat, session_target)
            if session is None:
                print(error)
                return
        cap = 4000
        resolve = getattr(chat, 'resolve_tool_ref', None)
        if tree:
            for depth, item in chat.sessions.tree(session.session_name):
                print(f'\n# Session: {item.session_name} '
                      f'({item.role or "root"})')
                for turn in item.turns:
                    print(render_turn(turn, full=full, cap=cap,
                                      resolve=resolve))
                    print()
            return
        turns_list = session.turns or []
        if '.' in spec and not spec.startswith('-') and not spec.endswith('-'):
            n, m, error = _parse_turn_ref(spec)
            if error:
                print(error)
                return
            turn = next((t for t in turns_list if t.get('index') == n), None)
            if turn is None:
                print(f'Turn not found: {n}')
                return
            parts = turn.get('parts') or []
            if m is not None and m > len(parts):
                print(f'Turn {n} has no part {m} (1-{len(parts)})')
                return
            print(render_turn(turn, part=m, full=full, cap=cap,
                              resolve=resolve))
            return
        indices, error = _turn_indices(spec, len(turns_list))
        if error:
            print(error)
            return
        for n in indices:
            turn = next((t for t in turns_list if t.get('index') == n), None)
            if turn is None:
                print(f'Turn not found: {n}')
                continue
            print(render_turn(turn, full=full, cap=cap, resolve=resolve))
            print()


def cmd_export(args) -> int:
    from polyglav.sessions.manager import SessionManager
    config = Config(path=getattr(args, 'path', None))
    sessions = SessionManager(config.local_path.parent / 'sessions')
    session = sessions.read(args.name)
    if session is None:
        print(f'Session not found: {args.name}', file=sys.stderr)
        return 1
    ext = '.json' if getattr(args, 'json', False) else '.md'
    if getattr(args, 'tree', False):
        nodes = sessions.tree(args.name)
        content = (session_tree_to_json(nodes)
                   if getattr(args, 'json', False)
                   else render_session_tree(nodes))
        default = f'{args.name}_tree{ext}'
    else:
        content = (session_to_json(session)
                   if getattr(args, 'json', False)
                   else render_session(session))
        default = f'{args.name}{ext}'
    out = getattr(args, 'out', None)
    if out == '-':
        sys.stdout.write(content)
        return 0
    if out:
        path = Path(out)
    else:
        path = sessions.sessions_dir.parent / 'exports' / default
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f'Exported session: {args.name} -> {path}')
    return 0


def cmd_import(args) -> int:
    from polyglav.sessions.manager import SessionManager
    config = Config(path=getattr(args, 'path', None))
    sessions = SessionManager(config.local_path.parent / 'sessions')
    path = Path(args.file)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f'Cannot read session file: {e}', file=sys.stderr)
        return 1
    try:
        session = sessions.import_document(
            data, name=getattr(args, 'name', '') or '',
            force=getattr(args, 'force', False))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f'Imported session: {path} -> {session.session_name}')
    return 0


def _run_export(args):
    return cmd_export(args)


def _run_import(args):
    return cmd_import(args)


def register_cli(cli):
    import argparse
    p = cli.add_parser('export', help='Export a saved session to Markdown or JSON')
    p.add_argument('name', help='Session name to export')
    p.add_argument('--out', help='Output file (default: .polyglav/exports/<name>.md, - for stdout)')
    p.add_argument('--json', action='store_true',
                   help='Export as JSON (default: .polyglav/exports/<name>.json)')
    p.add_argument('--tree', action='store_true',
                   help='Include sub-runs in the export')
    p.add_argument('--path', default=argparse.SUPPRESS,
                   help='Project path (default: current directory)')
    p.set_defaults(func=_run_export)
    p = cli.add_parser('import', help='Import a session from a JSON export')
    p.add_argument('file', help='JSON export to import')
    p.add_argument('--name',
                   help="Session name to import as (default: the file's session name, or a fresh ses_ name)")
    p.add_argument('--force', action='store_true',
                   help='Overwrite an existing session with that name')
    p.add_argument('--path', default=argparse.SUPPRESS,
                   help='Project path (default: current directory)')
    p.set_defaults(func=_run_import)
