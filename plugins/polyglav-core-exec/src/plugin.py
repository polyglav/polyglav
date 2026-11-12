import re
import shlex
import subprocess
from pathlib import Path

from polyglav.tools.output import cap_from_config as _cap
from polyglav.tools.output import truncate as _truncate

MAX_TIMEOUT = 600
DEFAULT_TIMEOUT = 30

_CHAIN_SPLIT = re.compile(r'(&&|\|\||;|\||&)')
_BLOCKED_MARKERS = ('`', '$(', '${', '>', '<', '\r', '\n')


def _clamp_timeout(timeout) -> int:
    try:
        return max(1, min(int(timeout), MAX_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def _chain_segments(command: str) -> list[str]:
    parts = re.split(_CHAIN_SPLIT, command)
    return [p.strip() for p in parts if p.strip() and p.strip() not in ('&&', '||', ';', '|', '&')]


def _tokens(text: str) -> list[str] | None:
    try:
        return shlex.split(text)
    except ValueError:
        return None


def _prefix_tokens(prefix: str) -> list[str]:
    return _tokens(str(prefix).strip()) or []


def _matches_prefix(tokens: list[str], wanted: list[str]) -> bool:
    return bool(wanted) and tokens[:len(wanted)] == wanted


def _command_allowed(command: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return True
    if any(marker in command for marker in _BLOCKED_MARKERS):
        return False
    prefixes = [_prefix_tokens(prefix) for prefix in allowlist if prefix]
    for seg in _chain_segments(command):
        tokens = _tokens(seg)
        if not tokens:
            return False
        if not any(_matches_prefix(tokens, wanted) for wanted in prefixes):
            return False
    return True


def _run_command_permission(args: dict, _config=None, _permissions=None) -> str | None:
    allowlist = list((_config.get('exec_allow') if _config is not None else []) or [])
    if not allowlist:
        return None
    command = str((args or {}).get('command') or '')
    if _command_allowed(command, allowlist):
        return None
    return 'deny'


def _is_failure(result: str) -> bool:
    for line in result.splitlines():
        if line.startswith('exit '):
            try:
                return int(line[5:].strip()) != 0
            except ValueError:
                return False
    return False


def register_tools(registry):
    @registry.register(
        name='run_command',
        description='Run a shell command in the project environment. Captures stdout/stderr and the exit code. Use for builds, tests, git operations, and any terminal task.',
        parameters={
            'type': 'object',
            'properties': {
                'command': {
                    'type': 'string',
                    'description': 'The shell command to execute',
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
            'required': ['command'],
        },
        category='exec',
        permission='bash',
        key_arg='command',
        path_arg='cwd',
        short='Run a shell command',
        echo=True,
        aliases=['bash', 'exec'],
        param_aliases={'cmd': 'command'},
        permission_fn=_run_command_permission,
        error=_is_failure,
    )
    def run_command(command: str, cwd: str | None = None,
                    timeout: int = 30, _config=None) -> str:
        max_chars = _cap(_config)
        if cwd and not Path(cwd).is_dir():
            return f'Error: cwd not found: {cwd}'
        timeout = _clamp_timeout(timeout)
        try:
            proc = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                cwd=cwd, timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            out = e.stdout or ''
            return f'Error: command timed out after {timeout}s' + (f'\n{_truncate(out, max_chars)}' if out else '')
        except OSError as e:
            return f'Error running command: {e}'
        stdout = proc.stdout or ''
        stderr = proc.stderr or ''
        body = stdout if not stderr or stderr == stdout else f'{stdout}\n{stderr}'
        lines = [f'$ {command}']
        if cwd:
            lines.append(f'[cwd: {cwd}]')
        lines.append(f'exit {proc.returncode}')
        if body:
            lines.append(_truncate(body, max_chars))
        return '\n'.join(lines)
