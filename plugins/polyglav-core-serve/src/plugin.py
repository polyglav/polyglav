def _run(args):
    from polyglav.cli import cmd_serve
    return cmd_serve(args)


def register_cli(cli):
    import argparse
    p = cli.add_parser('serve', help='HTTP JSON API server (stdlib http.server)')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8787)
    p.add_argument('--path', default=argparse.SUPPRESS,
                   help='Project path (default: current directory)')
    p.add_argument('--mode', help='Agent mode override (read or write, default read)')
    p.set_defaults(func=_run)
