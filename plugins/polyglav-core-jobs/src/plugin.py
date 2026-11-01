import importlib.util
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

SRC = Path(__file__).resolve().parent
_added = False
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
    _added = True
try:
    import cli as _cli
    import jobs as _jobs
    import scheduler as _scheduler
finally:
    if _added:
        sys.path.remove(str(SRC))


def register_services(services):
    services['job_registry'] = _jobs.JobRegistry
    services['job_scheduler'] = _scheduler.JobScheduler
    services['job_service'] = _cli


def _defaults(action: str, name: str = '') -> SimpleNamespace:
    return SimpleNamespace(
        action=action, name=name, prompt='', file=None, cron=None,
        interval=None, at=None, session='', mode='', provider='', model='',
        role='', team='', system_prompt='', tools_deny=[],
        tool_permission=[], retries=3, backoff=60.0, timeout=0,
        require_approval=False, approve_model=False, approval='manual',
        no_retry=False, verbose=False, quiet=False, tick=15.0)


def _parse_add(tokens: list[str]) -> SimpleNamespace:
    args = _defaults('add', tokens[0] if tokens else '')
    i = 1
    while i < len(tokens):
        token = tokens[i]
        value = tokens[i + 1] if i + 1 < len(tokens) else ''
        if token in ('--cron', '--interval', '--at', '--prompt', '--file',
                     '--session', '--mode', '--provider', '--model', '--role',
                     '--team', '--system-prompt', '--retries', '--backoff',
                     '--timeout', '--approval'):
            setattr(args, token[2:].replace('-', '_'), value)
            i += 2
        elif token in ('--tools-deny', '--tool-permission'):
            getattr(args, token[2:].replace('-', '_')).append(value)
            i += 2
        elif token == '--require-approval':
            args.require_approval = True
            i += 1
        elif token == '--approve-model':
            args.approve_model = True
            i += 1
        else:
            i += 1
    if args.interval not in (None, ''):
        try:
            args.interval = int(args.interval)
        except (TypeError, ValueError):
            args.interval = None
    if args.retries not in (None, ''):
        try:
            args.retries = int(args.retries)
        except (TypeError, ValueError):
            args.retries = 3
    if args.backoff not in (None, ''):
        try:
            args.backoff = float(args.backoff)
        except (TypeError, ValueError):
            args.backoff = 60.0
    if args.timeout not in (None, ''):
        try:
            args.timeout = int(args.timeout)
        except (TypeError, ValueError):
            args.timeout = 0
    return args


def register_commands(commands):
    chat = commands.chat_loop

    @commands.register(
        'jobs', description='Manage scheduled and durable jobs', subcommands=[
            ('list', 'List configured jobs'),
            ('status', 'Runtime summary per job (fired count, last error, uptime)'),
            ('show', 'Show a job and its run history'),
            ('add', 'Add a job (starts proposed, approve to activate)'),
            ('approve', 'Approve a job so it runs on schedule'),
            ('reject', 'Reject a proposed job'),
            ('enable', 'Enable a disabled job'),
            ('disable', 'Disable a job'),
            ('edit', 'Open the job task file in $EDITOR (creates the template first)'),
            ('remove', 'Remove a job definition'),
            ('run', 'Run a job now'),
        ])
    def jobs_cmd(arg=''):
        tokens = shlex.split(arg)
        action = tokens[0] if tokens else 'list'
        if action == 'add':
            if len(tokens) < 2:
                print('Usage: /jobs add <name> --cron "0 2 * * *" '
                      '[--prompt "text"|--file path] '
                      '[--interval N|--at ISO] [--approval auto]')
                return
            _cli.cmd_jobs(_parse_add(tokens[1:]), config=chat.config)
            return
        if action not in ('list', 'status', 'show', 'remove', 'approve',
                          'reject', 'enable', 'disable', 'edit', 'run'):
            print('Usage: /jobs [list|status|show <name>|add <name> ...|'
                  'approve <name>|reject <name>|enable <name>|disable <name>|'
                  'edit <name>|remove <name>|run <name>]')
            return
        name = tokens[1] if len(tokens) > 1 else ''
        if action not in ('list', 'status') and not name:
            print(f'Usage: /jobs {action} <name>')
            return
        _cli.cmd_jobs(_defaults(action, name), config=chat.config)


def _run(args):
    return _cli.cmd_jobs(args)


def register_cli(cli):
    import argparse
    p = cli.add_parser(
        'jobs',
        help='Scheduled and durable jobs (cron-style, retries, approvals)')
    p.add_argument('--path', default=argparse.SUPPRESS,
                   help='Project path (default: current directory)')
    g = p.add_subparsers(dest='action', required=True)
    g.add_parser('list', help='List configured jobs')
    g.add_parser('status', help='Runtime summary per job (fired count, last error, uptime)')
    gs = g.add_parser('show', help='Show a job definition and its run history')
    gs.add_argument('name')
    ga = g.add_parser('add', help='Add a job (starts as proposed, needs approval)')
    ga.add_argument('name')
    ga.add_argument('--prompt', default='',
                    help='Optional short per-run prompt (required unless --file is given)')
    ga.add_argument('--file', help='Markdown task file describing the job '
                   '(default .polyglav/jobs/<name>.md, created as a template if missing). '
                   'Linked - edits apply on the next run')
    sched = ga.add_mutually_exclusive_group(required=True)
    sched.add_argument('--cron', help='5-field cron expression (minute hour dom month dow)')
    sched.add_argument('--interval', type=int, help='Seconds between runs (min 60)')
    sched.add_argument('--at', help='One-shot run at an ISO datetime (e.g. 2026-08-27T02:00:00Z)')
    ga.add_argument('--session', help='Stable session name (default: a fresh '
                   'job_<ts>_<code> file per run)')
    ga.add_argument('--mode', help='Agent mode for the job (read or write, default write)')
    ga.add_argument('--provider', help='Provider override')
    ga.add_argument('--model', help='Model override')
    ga.add_argument('--role', help='Role whose prompt, model, and permissions apply')
    ga.add_argument('--team', help='Team to run for each scheduled run')
    ga.add_argument('--system-prompt', help='System prompt override')
    ga.add_argument('--tools-deny', action='append', default=[],
                    help='Tool name to deny (repeatable)')
    ga.add_argument('--tool-permission', action='append', default=[],
                    help='category=action override (repeatable), e.g. bash=allow')
    ga.add_argument('--retries', type=int, default=3, help='Retries after a failed run')
    ga.add_argument('--backoff', type=float, default=60.0,
                    help='Base backoff seconds, doubled per retry')
    ga.add_argument('--timeout', type=int, default=0,
                    help='Max seconds for a run (0 = no cap)')
    ga.add_argument('--require-approval', action='store_true',
                    help='Arm only one run per approve - each run parks in waiting_approval '
                         'until a user approves it')
    ga.add_argument('--approve-model', action='store_true',
                    help='Approve the model referenced by --role (or --model) '
                         'without prompting')
    ga.add_argument('--approval', choices=['manual', 'auto'], default='manual',
                    help='manual starts proposed and waits for approve (default); '
                         'auto starts approved')
    for name, help_text in (
            ('approve', 'Approve a job so it runs on schedule'),
            ('reject', 'Reject a proposed job'),
            ('enable', 'Enable a disabled job'),
            ('disable', 'Disable a job'),
            ('edit', 'Open the job task file in $EDITOR (creates the template first)'),
            ('remove', 'Remove a job definition')):
        cmd = g.add_parser(name, help=help_text)
        cmd.add_argument('name')
    gr = g.add_parser('run', help='Run a job now (waits, applies retries)')
    gr.add_argument('name')
    gr.add_argument('--no-retry', action='store_true',
                    help='Single attempt, no retries or backoff')
    gr.add_argument('--verbose', action='store_true',
                    help='Stream the run live (tokens, tool activity) before the summary')
    gd = g.add_parser('daemon', help='Run the scheduler loop until interrupted')
    gd.add_argument('--tick', type=float, default=15.0,
                    help='Schedule check interval in seconds (default: 15)')
    gd.add_argument('--quiet', action='store_true', help='Suppress scheduler output')
    p.set_defaults(func=_run)
