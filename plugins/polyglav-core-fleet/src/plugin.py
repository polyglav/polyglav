def _run(args):
    from polyglav.cli import cmd_fleet
    return cmd_fleet(args)


def register_cli(cli):
    import argparse
    p = cli.add_parser(
        'fleet',
        help='Supervise a fleet of scoped polyglav serve agents '
             '(ports, health checks, restart policy, config generation)')
    p.add_argument('--path', default=argparse.SUPPRESS,
                   help='Fleet root (default: current directory)')
    g = p.add_subparsers(dest='action', required=True)
    g.add_parser('init', help='Scan subdirectories holding .polyglav/config.json '
                 'into the fleet manifest')
    ga = g.add_parser('add', help='Add an agent to the manifest')
    ga.add_argument('name')
    ga.add_argument('--dir', help='Agent directory (default: <root>/<name>)')
    ga.add_argument('--port', type=int, default=0,
                    help='Preferred port (0 = auto-allocate)')
    ga.add_argument('--max-restarts', type=int, default=10,
                    help='Restart budget before the supervisor pauses the agent '
                         '(0 = unlimited)')
    grm = g.add_parser('remove', help='Remove an agent from the manifest (stops it)')
    grm.add_argument('name')
    gu = g.add_parser('up', help='Start agents (Ctrl-C = graceful down)')
    gu.add_argument('--detach', action='store_true',
                    help='Run the supervisor as a background daemon')
    gu.add_argument('--daemon', dest='daemon_', action='store_true',
                    help=argparse.SUPPRESS)
    g.add_parser('down', help='Stop the supervised agents and the daemon if running')
    g.add_parser('status', help='Live status table of the fleet')
    gr = g.add_parser('restart', help='Stop and relaunch agents, resetting backoff')
    gr.add_argument('name', nargs='?', help='Agent name (default: all)')
    gl = g.add_parser('logs', help='Show an agent log (tail)')
    gl.add_argument('name')
    gl.add_argument('n', nargs='?', type=int, default=50,
                    help='Last N lines (default: 50)')
    gl.add_argument('--follow', '-f', action='store_true',
                    help='Keep watching appended output (Ctrl-C to stop)')
    gc = g.add_parser('config', help='Write selected keys into <agent>/.polyglav/config.json')
    gc.add_argument('name')
    gc.add_argument('--provider', help='Provider override')
    gc.add_argument('--model', help='Model override')
    gc.add_argument('--role', help='Inline a role prompt, model, and permissions')
    gc.add_argument('--system-prompt', help='System prompt override')
    gc.add_argument('--mode', help='Agent mode override (read or write)')
    gc.add_argument('--tools-deny', action='append', default=[],
                    help='Tool name to deny (repeatable)')
    gc.add_argument('--tool-permission', action='append', default=[],
                    help='category=action override (repeatable), e.g. bash=allow')
    gc.add_argument('--approve-model', action='store_true',
                    help='Approve the model referenced by --role or --model '
                         'in the global models registry')
    p.set_defaults(func=_run)
