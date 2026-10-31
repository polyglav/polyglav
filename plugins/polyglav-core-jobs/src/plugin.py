import os
import shlex
import subprocess


def register_commands(commands):
    registry = commands
    chat = commands.chat_loop

    @registry.register('jobs', description='Manage scheduled and durable jobs', subcommands=[
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
        from polyglav.jobs import (Job, JobRegistry, publish, read_memory,
                            render_list, render_show, render_status,
                            validate_schedule)
        import shlex
        registry = JobRegistry(chat.config.local_path.parent / 'jobs.json')
        tokens = shlex.split(arg)
        action = tokens[0] if tokens else 'list'
        if action in ('list', 'status'):
            (render_status if action == 'status' else render_list)(registry)
            return
        if action == 'show':
            name = tokens[1] if len(tokens) > 1 else ''
            if not name:
                print('Usage: /jobs show <name>')
                return
            render_show(registry, name)
            return
        if action == 'remove':
            name = tokens[1] if len(tokens) > 1 else ''
            if not name:
                print('Usage: /jobs remove <name>')
                return
            if registry.remove(name):
                print(f'Removed job: {name}')
            else:
                print(f'Job not found: {name}')
            return
        if action in ('approve', 'reject', 'enable', 'disable'):
            name = tokens[1] if len(tokens) > 1 else ''
            job = registry.find(name) if name else None
            if job is None:
                print(f'Usage: /jobs {action} <name>')
                return
            if action == 'approve':
                job.status = 'approved'
                job.enabled = True
                if job.require_approval:
                    job.approval_pending = True
            elif action == 'reject':
                job.status = 'proposed'
                job.enabled = False
                job.approval_pending = False
            elif action == 'enable':
                job.enabled = True
            else:
                job.enabled = False
            registry.save()
            print(f'Job {name}: status={job.status}, '
                  f'{"enabled" if job.enabled else "disabled"}')
            return
        if action == 'run':
            from polyglav.scheduler import JobScheduler
            name = tokens[1] if len(tokens) > 1 else ''
            job = registry.find(name) if name else None
            if job is None:
                print('Usage: /jobs run <name>')
                return
            run = JobScheduler(chat.config, verbose=False).run_job(job)
            print(f'Run {job.name}: {run.status} ({run.duration}s)')
            if run.content:
                print(run.content)
            if run.reason:
                print(f'  reason: {run.reason}')
            if run.session:
                print(f'  session: {run.session}')
            memory = read_memory(chat.config.local_path.parent.parent, job)
            if memory:
                print(f'  summary: {" ".join(memory.split())[:200]}')
            return
        if action == 'add':
            if len(tokens) < 2:
                print('Usage: /jobs add <name> --cron "0 2 * * *" '
                      '[--prompt "text"|--file path] '
                      '[--interval N|--at ISO] [--approval auto]')
                return
            name = tokens[1]
            opts, after = {}, []
            i = 2
            while i < len(tokens):
                tok = tokens[i]
                if tok in ('--cron', '--interval', '--at', '--prompt', '--file',
                           '--session', '--mode', '--provider', '--model', '--role', '--team'):
                    opts[tok] = tokens[i + 1] if i + 1 < len(tokens) else ''
                    i += 2
                elif tok == '--approval':
                    opts[tok] = tokens[i + 1].lower() if i + 1 < len(tokens) else 'manual'
                    i += 2
                else:
                    after.append(tok)
                    i += 1
            prompt = opts.get('--prompt', '') or ''
            file_arg = opts.get('--file', '') or ''
            if not prompt and not file_arg:
                print('Usage: /jobs add <name> --prompt "text" --file path '
                      '(one of them required)')
                return
            schedule: dict = {}
            if opts.get('--cron'):
                schedule['cron'] = opts['--cron']
            elif opts.get('--interval'):
                try:
                    schedule['interval'] = int(opts['--interval'])
                except ValueError:
                    print('Invalid --interval value')
                    return
            elif opts.get('--at'):
                schedule['at'] = opts['--at']
            else:
                print('One of --cron, --interval, or --at is required')
                return
            try:
                validate_schedule(schedule)
            except ValueError as e:
                print(f'Error: {e}')
                return
            existing = registry.find(name)
            if existing is not None:
                print(f'Job already exists: {name}')
                return
            from ..cli import _store_task_file
            from polyglav.jobs import ensure_task_file
            worktree = chat.config.local_path.parent.parent
            task_file = _store_task_file(worktree, file_arg)
            auto = opts.get('--approval') == 'auto'
            job = Job(
                name=name,
                schedule=schedule,
                prompt=prompt,
                session=opts.get('--session', '') or '',
                mode=opts.get('--mode', '') or '',
                provider=opts.get('--provider', '') or '',
                model=opts.get('--model', '') or '',
                role=opts.get('--role', '') or '',
                team=opts.get('--team', '') or '',
                task_file=task_file,
                enabled=auto,
                status='approved' if auto else 'proposed',
            )
            if job.task_file:
                ensure_task_file(worktree, job)
            publish(registry, job)
            return
        if action == 'edit':
            name = tokens[1] if len(tokens) > 1 else ''
            job = registry.find(name) if name else None
            if job is None:
                print('Usage: /jobs edit <name>')
                return
            from polyglav.jobs import ensure_task_file
            path = ensure_task_file(chat.config.local_path.parent.parent, job)
            editor = os.environ.get('EDITOR') or os.environ.get('VISUAL') or 'vi'
            import shlex
            import subprocess
            subprocess.call(shlex.split(editor) + [str(path)])
            return
        print('Usage: /jobs [list|status|show <name>|add <name> ...|approve <name>|'
              'reject <name>|enable <name>|disable <name>|'
              'edit <name>|remove <name>|run <name>]')




def _run(args):
    from polyglav.cli import cmd_jobs
    return cmd_jobs(args)


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
