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
        ('stop', 'Stop a job - same as disable'),
        ('edit', 'Open the job task file in $EDITOR (creates the template first)'),
        ('remove', 'Remove a job definition'),
        ('run', 'Run a job now'),
    ])
    def jobs_cmd(arg=''):
        from polyglav.jobs import (Job, JobRegistry, parked_asks_for_run, publish,
                            read_memory, render_list, render_show,
                            render_status, validate_schedule)
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
        if action in ('approve', 'reject', 'enable', 'disable', 'stop'):
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
            parked = parked_asks_for_run(chat.config.local_path.parent,
                                         run.session)
            if parked:
                print('  parked asks: '
                      + ', '.join(f'#{a["id"]}' for a in parked))
            return
        if action == 'add-supervisor':
            if len(tokens) < 2:
                print('Usage: /jobs add-supervisor <name> '
                      '[--at ISO | --interval N | --cron "expr"] '
                      '[--task "text" | --file path]')
                return
            opts = {}
            i = 2
            while i < len(tokens):
                tok = tokens[i]
                if tok in ('--at', '--interval', '--cron', '--task', '--file'):
                    opts[tok] = tokens[i + 1] if i + 1 < len(tokens) else ''
                    i += 2
                else:
                    i += 1
            schedule = {}
            if opts.get('--cron'):
                schedule['cron'] = opts['--cron']
            elif opts.get('--interval'):
                schedule['interval'] = int(opts['--interval'])
            elif opts.get('--at'):
                schedule['at'] = opts['--at']
            else:
                schedule['interval'] = 86400
            from polyglav.jobs import add_supervisor_job, describe_schedule
            try:
                job = add_supervisor_job(
                    registry, tokens[1], chat.config.local_path.parent.parent,
                    schedule, task=opts.get('--task', ''),
                    task_file=opts.get('--file', ''))
            except ValueError as e:
                print(f'Error: {e}')
                return
            print(f'Added supervisor job: {job.name} [{job.status}]')
            print(f'  schedule:  {describe_schedule(job)}')
            print(f'  run now:   /jobs run {job.name}')
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
                           '--session', '--mode', '--provider', '--model', '--role'):
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
              'reject <name>|enable <name>|disable <name>|stop <name>|'
              'edit <name>|remove <name>|run <name>]')


