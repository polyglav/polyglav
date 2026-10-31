import json
import sys
from pathlib import Path

from polyglav.sessions.render import (
    render_session, render_session_tree, session_to_json, session_tree_to_json,
)


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
            roots = chat.tool_output_roots() if hasattr(chat, 'tool_output_roots') else []
            if chat.sessions.delete(name, extra_dirs=roots):
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



def _run_export(args):
    from polyglav.cli import cmd_export
    return cmd_export(args)


def _run_import(args):
    from polyglav.cli import cmd_import
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
