import sys
import argparse

from .config import Config
from .chat import ChatLoop
from .plugins.manager import CLIRegistry, FrontendRegistry, PluginManager
from . import get_version


def _add_run_parser(sub):
    p = sub.add_parser('run', help='One-shot headless chat (JSON or text output)')
    p.add_argument('--prompt', '-p', required=True, help='The prompt to send')
    p.add_argument('--provider', help='Provider override (e.g. ollama, openai, groq)')
    p.add_argument('--model', help='Model override')
    p.add_argument('--base-url', help='Base URL override')
    p.add_argument('--mode', help='Agent mode override (read or write, default read)')
    p.add_argument('--output', choices=['text', 'json'], default='json',
                   help='Output format (default: json)')
    p.add_argument('--verbose', action='store_true',
                   help='Print tool status and diagnostics to stderr')
    g = p.add_mutually_exclusive_group()
    g.add_argument('--yes', dest='approve', action='store_true',
                   help='Auto-approve tools that require confirmation')
    g.add_argument('--no', dest='approve', action='store_false',
                   help='Auto-deny tools that require confirmation (default)')
    p.set_defaults(approve=None)
    p.add_argument('--approve-model', action='store_true',
                   help='Approve the configured/agent-type model without prompting')
    p.add_argument('--path', default=argparse.SUPPRESS,
                   help='Project path (default: current directory)')


def _add_mcp_parser(sub):
    p = sub.add_parser('mcp', help='Run polyglav as an MCP server over stdio')
    p.add_argument('--path', default=argparse.SUPPRESS,
                   help='Project path (default: current directory)')


def _add_config_parser(sub):
    p = sub.add_parser('config',
                       help='Show, set, or unset config values (global or project-local scope)')
    p.add_argument('--path', default=argparse.SUPPRESS,
                   help='Project path (default: current directory)')
    g = p.add_subparsers(dest='action', required=True)
    gg = g.add_parser('get', help='Show effective values (one or more keys, default: all)')
    gg.add_argument('key', nargs='*')
    gg.add_argument('--show-origin', action='store_true',
                    help='Also print where each value comes from (default/global/local)')
    gs = g.add_parser('set', help='Set a config value')
    gs.add_argument('key')
    gs.add_argument('value', nargs='?')
    gu = g.add_parser('unset', help='Remove a config value from the selected scope')
    gu.add_argument('key')
    g.add_parser('reload', help='Re-read the config files from disk')
    for sub in (gg, gs, gu):
        sub.add_argument('--global', dest='global_', action='store_true',
                         help='Use the global config file (~/.config/polyglav/config.json)')
        sub.add_argument('--local', dest='local_', action='store_true',
                         help='Use the project-local config file (default)')


def _add_plugins_parser(sub):
    p = sub.add_parser('plugins', help='Manage plugins (list, install, update, uninstall)')
    p.add_argument('--path', default=argparse.SUPPRESS,
                   help='Project path (default: current directory)')
    g = p.add_subparsers(dest='action', required=True)
    g.add_parser('list', help='List installed plugins')
    ge = g.add_parser('enable', help='Enable a plugin (add to the plugins list, applies on next start)')
    ge.add_argument('name')
    gd = g.add_parser('disable', help='Disable a plugin (remove from the plugins list, applies on next start)')
    gd.add_argument('name')
    pi = g.add_parser('install', help='Install a plugin from a git URL or local path')
    pi.add_argument('source', help='Git URL or local path of the plugin')
    pi.add_argument('--global', dest='global_', action='store_true',
                    help='Install into the global plugins dir')
    pi.add_argument('--deps', action='store_true',
                    help='pip install the plugin\'s declared dependencies')
    pu = g.add_parser('update', help='Update an installed plugin')
    pu.add_argument('name', help='Plugin name')
    pun = g.add_parser('uninstall', help='Remove an installed plugin')
    pun.add_argument('name', help='Plugin name')
    pt = g.add_parser('test', help='Run a plugin\'s bundled test suite')
    pt.add_argument('name', nargs='?', help='Plugin name (default: all plugins with tests)')
    pt.add_argument('--verbose', action='store_true', help='Verbose unittest output')


def _version():
    return get_version()


def _preparse_path(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--path', default=None)
    known, _ = parser.parse_known_args(argv)
    return known.path


def _load_plugins(argv):
    config = Config(path=_preparse_path(argv))
    pm = PluginManager(config)
    pm.load()
    return config, pm


def _build_parser(config, pm):
    parser = argparse.ArgumentParser(
        description='Polyglav - a terminal-based agentic REPL with headless CLI and API modes',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--path', '-p', help='Project path (default: current directory)')
    parser.add_argument('--frontend', default='repl',
                        help='Front-end to start when no subcommand is given (default: repl)')
    parser.add_argument('--version', '-v', action='version',
                        help='Print version and exit', version=_version())
    sub = parser.add_subparsers(dest='command')
    _add_run_parser(sub)
    _add_mcp_parser(sub)
    _add_config_parser(sub)
    _add_plugins_parser(sub)
    cli = CLIRegistry(sub, config, pm)
    core = list(cli.names())
    pm.register_cli(cli)
    plugins = [name for name in cli.names() if name not in core]
    parser.epilog = ('Core commands: ' + ', '.join(core) + '\n'
                     'Plugin commands: ' + (', '.join(plugins) or '(none)'))
    return parser


def _repl_frontend(config, plugin_manager):
    return ChatLoop(config, plugin_manager=plugin_manager)


def _frontends(pm):
    registry = FrontendRegistry()
    pm.register_frontends(registry)
    if registry.get('repl') is None:
        registry.register('repl', _repl_frontend, 'Terminal REPL')
    return registry


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    config, pm = _load_plugins(argv)
    parser = _build_parser(config, pm)
    args = parser.parse_args(argv)

    handler = getattr(args, 'func', None)
    if handler is not None:
        return handler(args)

    if args.command == 'run':
        from .cli import cmd_run
        return cmd_run(args)
    if args.command == 'mcp':
        from .cli import cmd_mcp
        return cmd_mcp(args)
    if args.command == 'plugins':
        from .cli import cmd_plugins
        return cmd_plugins(args)
    if args.command == 'config':
        from .cli import cmd_config
        return cmd_config(args)

    frontend = _frontends(pm).get(args.frontend or 'repl')
    if frontend is None:
        print(f'Unknown front-end: {args.frontend}', file=sys.stderr)
        return 1
    chat = frontend.factory(config, pm)

    try:
        chat.run()
    except SystemExit:
        pass
    except KeyboardInterrupt:
        print()
    except Exception as e:
        print(f'\nUnexpected error: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
