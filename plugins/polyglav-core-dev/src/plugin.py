import shlex
import subprocess
import sys
from pathlib import Path

MAX_TIMEOUT = 600
DEFAULT_TIMEOUT = 300

DEFAULTS = {
    'test': 'python -m unittest discover',
    'lint': 'ruff check .',
    'format': 'ruff format .',
}


def _resolve_interpreter(argv: list[str]) -> list[str]:
    if argv and argv[0] in ('python', 'python3'):
        return [sys.executable] + argv[1:]
    return argv


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


def _is_failure(result: str) -> bool:
    for line in result.splitlines():
        if line.startswith('exit '):
            try:
                return int(line[5:].strip()) != 0
            except ValueError:
                return False
    return False


def _cmd(config, key: str, default: str) -> list[str]:
    raw = ''
    if config is not None:
        raw = str(config.get(key) or '')
    if not raw.strip():
        raw = default
    try:
        argv = shlex.split(raw)
    except ValueError:
        argv = raw.split()
    argv = argv or [default]
    return _resolve_interpreter(argv)


def _is_discover(argv: list[str]) -> bool:
    return (len(argv) >= 4 and argv[1] == '-m' and argv[2] == 'unittest'
            and argv[3] == 'discover')


def _test_argv(config, target: str) -> list[str]:
    argv = _cmd(config, 'dev.test_cmd', DEFAULTS['test'])
    if not target:
        return argv
    if _is_discover(argv):
        return [argv[0], '-m', 'unittest', target]
    return argv + [target]


def _run(argv: list[str], cwd: str | None, config,
         timeout: int, target: str = '') -> str:
    if cwd and not Path(cwd).is_dir():
        return f'Error: cwd not found: {cwd}'
    timeout = _clamp_timeout(timeout)
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, cwd=cwd, timeout=timeout,
        )
    except FileNotFoundError:
        return f'Error: command not found: {argv[0]}'
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ''
        return f'Error: command timed out after {timeout}s' + (
            f'\n{_truncate(out, _cap(config))}' if out else '')
    except OSError as e:
        return f'Error running command: {e}'
    stdout = proc.stdout or ''
    stderr = proc.stderr or ''
    body = stdout if not stderr or stderr == stdout else f'{stdout}\n{stderr}'
    lines = [f'$ {" ".join(argv)}']
    if cwd:
        lines.append(f'[cwd: {cwd}]')
    lines.append(f'exit {proc.returncode}')
    no_tests = ('NO TESTS RAN' in body or 'Ran 0 tests' in body
                or proc.returncode == 5)
    if target and no_tests:
        lines.append(
            f'Error: no tests matched "{target}" '
            f'(unittest exit {proc.returncode})')
    if body:
        lines.append(_truncate(body, _cap(config)))
    return '\n'.join(lines)


def register_tools(registry):
    @registry.register(
        name='code_test',
        description='Run the project test suite. Uses the dev.test_cmd config key (default "python -m unittest discover"); pass target to run a specific test module or path. Reports the exit code and output. Use to verify code changes.',
        parameters={
            'type': 'object',
            'properties': {
                'target': {
                    'type': 'string',
                    'description': 'Optional test module, class, or path to run instead of the whole suite',
                },
                'cwd': {
                    'type': 'string',
                    'description': 'Working directory for the command (defaults to the current one)',
                },
                'timeout': {
                    'type': 'integer',
                    'description': 'Timeout in seconds before the command is killed (capped at 600)',
                },
            },
            'required': [],
        },
        category='exec',
        permission='bash',
        path_arg='cwd',
        key_arg='target',
        short='Run the project test suite',
        echo=True,
        glyph='$',
        verb='Test',
        error=_is_failure,
        aliases=['run_tests', 'test_suite'],
        param_aliases={'test': 'target', 'path': 'target', 'tests': 'target'},
    )
    def code_test(target: str = '', cwd: str | None = None,
                  timeout: int = DEFAULT_TIMEOUT, _config=None) -> str:
        argv = _test_argv(_config, target)
        return _run(argv, cwd, _config, timeout, target=target)

    @registry.register(
        name='code_lint',
        description='Run the project linter. Uses the dev.lint_cmd config key (default "ruff check ."); pass target to lint a specific path. Reports the exit code and findings. Use to check code style before finishing.',
        parameters={
            'type': 'object',
            'properties': {
                'target': {
                    'type': 'string',
                    'description': 'Optional path to lint instead of the whole project',
                },
                'cwd': {
                    'type': 'string',
                    'description': 'Working directory for the command (defaults to the current one)',
                },
                'timeout': {
                    'type': 'integer',
                    'description': 'Timeout in seconds before the command is killed (capped at 600)',
                },
            },
            'required': [],
        },
        category='exec',
        permission='bash',
        path_arg='cwd',
        key_arg='target',
        short='Run the project linter',
        echo=True,
        glyph='$',
        verb='Lint',
        error=_is_failure,
        aliases=['run_lint', 'lint_check'],
        param_aliases={'path': 'target'},
    )
    def code_lint(target: str = '', cwd: str | None = None,
                  timeout: int = DEFAULT_TIMEOUT, _config=None) -> str:
        argv = _cmd(_config, 'dev.lint_cmd', DEFAULTS['lint'])
        if target:
            argv = argv + [target]
        return _run(argv, cwd, _config, timeout)

    @registry.register(
        name='code_format',
        description='Run the project formatter. Uses the dev.format_cmd config key (default "ruff format ."); pass target to format a specific path. Reports the exit code and output. Use to format code before finishing.',
        parameters={
            'type': 'object',
            'properties': {
                'target': {
                    'type': 'string',
                    'description': 'Optional path to format instead of the whole project',
                },
                'cwd': {
                    'type': 'string',
                    'description': 'Working directory for the command (defaults to the current one)',
                },
                'timeout': {
                    'type': 'integer',
                    'description': 'Timeout in seconds before the command is killed (capped at 600)',
                },
            },
            'required': [],
        },
        category='exec',
        permission='bash',
        path_arg='cwd',
        key_arg='target',
        short='Run the project formatter',
        echo=True,
        glyph='$',
        verb='Format',
        error=_is_failure,
        aliases=['run_format', 'format_code'],
        param_aliases={'path': 'target'},
    )
    def code_format(target: str = '', cwd: str | None = None,
                    timeout: int = DEFAULT_TIMEOUT, _config=None) -> str:
        argv = _cmd(_config, 'dev.format_cmd', DEFAULTS['format'])
        if target:
            argv = argv + [target]
        return _run(argv, cwd, _config, timeout)