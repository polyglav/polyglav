import subprocess
from pathlib import Path

MAX_TIMEOUT = 600
DEFAULT_TIMEOUT = 30


def _clamp_timeout(timeout) -> int:
    try:
        return max(1, min(int(timeout), MAX_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def _cap(config=None) -> int:
    if config is None:
        return 0
    try:
        return max(0, int(config.get('tool_max_result_chars', 0)))
    except (TypeError, ValueError):
        return 0


def _truncate(text: str, max_chars: int = 0) -> str:
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rsplit('\n', 1)[0] + '\n... (truncated)'
    return text


def _run(argv: list[str], cwd: str | None, config) -> str:
    if cwd and not Path(cwd).is_dir():
        return f'Error: cwd not found: {cwd}'
    timeout = DEFAULT_TIMEOUT
    try:
        proc = subprocess.run(
            ['git'] + argv, capture_output=True, text=True,
            cwd=cwd, timeout=timeout,
        )
    except FileNotFoundError:
        return 'Error: git is not installed or not on PATH'
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ''
        return f'Error: git command timed out after {timeout}s' + (
            f'\n{_truncate(out, _cap(config))}' if out else '')
    except OSError as e:
        return f'Error running git: {e}'
    stdout = proc.stdout or ''
    stderr = proc.stderr or ''
    body = stdout if not stderr or stderr == stdout else f'{stdout}\n{stderr}'
    lines = [f'$ git {" ".join(argv)}']
    if cwd:
        lines.append(f'[cwd: {cwd}]')
    lines.append(f'exit {proc.returncode}')
    if body:
        lines.append(_truncate(body, _cap(config)))
    return '\n'.join(lines)


def _read_args(operation: str, path: str, limit: int, staged: bool,
               rev: str) -> list[str]:
    if operation == 'status':
        args = ['status', '--short', '--branch']
        if path:
            args += ['--', path]
        return args
    if operation == 'diff':
        args = ['diff']
        if staged:
            args.append('--cached')
        if path:
            args += ['--', path]
        return args
    if operation == 'log':
        n = max(1, min(int(limit), 100))
        args = ['log', '--oneline', f'-{n}']
        if path:
            args += ['--', path]
        return args
    if operation == 'branch':
        return ['branch', '-a']
    if operation == 'show':
        args = ['show', '--stat']
        if rev:
            args.append(rev)
        return args
    if operation == 'rev_parse':
        return ['rev-parse', rev or 'HEAD']
    return ['status', '--short', '--branch']


def _write_action(args: dict) -> str | None:
    if (args or {}).get('all'):
        return 'ask'
    return None


def register_tools(registry):
    @registry.register(
        name='git',
        description='Run a read-only git operation: status, diff, log, branch, show, or rev_parse. Use to inspect the repository state before changing files. Never modifies the repo; use git_commit to stage or commit changes.',
        parameters={
            'type': 'object',
            'properties': {
                'operation': {
                    'type': 'string',
                    'enum': ['status', 'diff', 'log', 'branch', 'show', 'rev_parse'],
                    'description': 'Which git operation to run (default status)',
                },
                'path': {
                    'type': 'string',
                    'description': 'Limit the operation to a path (status/diff/log)',
                },
                'limit': {
                    'type': 'integer',
                    'description': 'How many log entries to show (default 20, max 100)',
                },
                'staged': {
                    'type': 'boolean',
                    'description': 'diff only staged changes (git diff --cached)',
                },
                'rev': {
                    'type': 'string',
                    'description': 'Revision for show/rev_parse (default HEAD)',
                },
                'cwd': {
                    'type': 'string',
                    'description': 'Working directory for git (defaults to the current one)',
                },
            },
            'required': [],
        },
        category='read',
        permission='read',
        path_arg='cwd',
        key_arg='operation',
        short='Run a read-only git command',
        echo=True,
        glyph='⎇',
        verb='Git',
        aliases=['git_status', 'git_diff', 'git_log', 'git_branch', 'git_show'],
    )
    def git(operation: str = 'status', path: str = '', limit: int = 20,
            staged: bool = False, rev: str = '', cwd: str | None = None,
            _config=None) -> str:
        return _run(_read_args(operation, path, limit, staged, rev),
                    cwd, _config)

    @registry.register(
        name='git_commit',
        description='Stage or commit changes with git: add stages a path (or everything with all=true), commit creates a commit with the given message. This is a state-changing operation gated by the vcs permission category: a role whose vcs carve is allow commits without prompting, every other role confirms, and staging everything with all=true always asks. Does not push, merge, checkout, or rewrite history.',
        parameters={
            'type': 'object',
            'properties': {
                'operation': {
                    'type': 'string',
                    'enum': ['add', 'commit'],
                    'description': 'add stages changes; commit creates a commit',
                },
                'message': {
                    'type': 'string',
                    'description': 'Commit message (required for commit)',
                },
                'path': {
                    'type': 'string',
                    'description': 'Path to stage for add',
                },
                'all': {
                    'type': 'boolean',
                    'description': 'Stage all changes with git add -A (for add, or before commit)',
                },
                'cwd': {
                    'type': 'string',
                    'description': 'Working directory for git (defaults to the current one)',
                },
            },
            'required': [],
        },
        category='write',
        permission='vcs',
        path_arg='cwd',
        key_arg='operation',
        short='Stage or commit git changes',
        glyph='⎇',
        verb='Git',
        permission_fn=_write_action,
        aliases=['commit'],
        param_aliases={'msg': 'message', 'message_text': 'message'},
    )
    def git_commit(operation: str = 'commit', message: str = '',
                   path: str = '', all: bool = False,
                   cwd: str | None = None, _config=None) -> str:
        if operation == 'add':
            if not path and not all:
                return 'Error: add requires a path or all=true'
            argv = ['add', '-A'] if all else ['add', path]
            return _run(argv, cwd, _config)
        if not message:
            return 'Error: commit requires a message'
        parts = []
        if all:
            parts.append(_run(['add', '-A'], cwd, _config))
        parts.append(_run(['commit', '-m', message], cwd, _config))
        return '\n'.join(parts)