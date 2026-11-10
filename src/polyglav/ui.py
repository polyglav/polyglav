import os
import re
import select
import sys
import threading
import time

from .config import verbosity_level


SPINNER_FRAMES = ('⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏')
SPINNER_INTERVAL = 0.08

ASCII_GLYPHS = {
    'read': '<',
    'write': '>',
    'search': '%',
    'exec': '$',
    'ask': '?',
    'todo': '-',
    'call': '>',
    'delegate': '>',
    'enter': '>',
    'return': '<',
    'warning': '!',
    'question': '?',
    'default': '*',
    'spinner': '|/-\\',
}

DIM = '\033[90m'
RED = '\033[91m'
CYAN = '\033[96m'
MAGENTA = '\033[95m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
ITALIC_GRAY = '\033[3;90m'
RESET = '\033[0m'


def format_tokens(value) -> str:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        number = 0
    if number >= 1_000_000:
        text = f'{number / 1_000_000:.1f}M'
        return text.replace('.0M', 'M')
    if number >= 1_000:
        text = f'{number / 1_000:.1f}k'
        return text.replace('.0k', 'k')
    return str(number)


def colors_enabled() -> bool:
    if os.environ.get('NO_COLOR'):
        return False
    return str(os.environ.get('TERM', '') or '').lower() != 'dumb'


def supports_256() -> bool:
    term = str(os.environ.get('TERM', '') or '').lower()
    colorterm = str(os.environ.get('COLORTERM', '') or '').lower()
    return '256color' in term or colorterm in ('truecolor', '24bit')


ORANGE = '\033[38;5;208m' if supports_256() else '\033[33m'
TEAL = '\033[38;5;38m' if supports_256() else '\033[36m'
BRIGHT_BLUE = '\033[94m'


def glyph_map(config) -> dict:
    raw = config.get('glyphs') if config is not None else {}
    if isinstance(raw, str):
        return dict(ASCII_GLYPHS) if raw.strip().lower() == 'ascii' else {}
    return dict(raw) if isinstance(raw, dict) else {}


def glyph(config, key: str, default: str) -> str:
    return str(glyph_map(config).get(key, default))

_ANSI_RE = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
_VERDICT_RE = re.compile(r'^\s*(?:[-*]\s+)?(?:\*\*)?VERDICT\s*:', re.I)


def is_internal_verdict_line(line: str) -> bool:
    return bool(_VERDICT_RE.match(str(line or '')))


class TeeStream:
    def __init__(self, stream, path, ansi=False):
        self._stream = stream
        self._file = open(path, 'a', encoding='utf-8', errors='replace')
        self._ansi = ansi

    def write(self, text):
        self._stream.write(text)
        if text and ('\r' not in text or '\n' in text):
            if self._ansi:
                self._file.write(text)
            else:
                clean = text.replace('\001', '').replace('\002', '')
                self._file.write(_ANSI_RE.sub('', clean))
        return len(text)

    def flush(self):
        self._stream.flush()
        self._file.flush()

    def close(self):
        try:
            self._file.flush()
            self._file.close()
        except OSError:
            pass

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _open_tty():
    try:
        return open('/dev/tty', 'r')
    except OSError:
        return None


def _read_key(fd: int, timeout: float) -> str | None:
    if timeout and timeout > 0:
        try:
            ready, _, _ = select.select([fd], [], [], timeout)
        except (OSError, ValueError, TypeError):
            return None
        if not ready:
            return None
    try:
        data = os.read(fd, 1)
    except OSError:
        raise EOFError()
    if not data:
        raise EOFError()
    return data.decode('utf-8', 'ignore')


def _stdin_ready(timeout: float) -> bool:
    if not (timeout and timeout > 0):
        return True
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
    except (OSError, ValueError, TypeError):
        return True
    return bool(ready)


def _timed_input(prompt: str, timeout: float, hidden: bool = False) -> str | None:
    if hidden:
        return _hidden_input(prompt, timeout)
    if not _stdin_ready(timeout):
        return None
    return input(prompt)


def _key_input(prompt: str, timeout: float, choices: tuple, default: str = 'y',
               echo: bool = True) -> str | None:
    tty_file = _open_tty()
    if tty_file is None:
        if not _stdin_ready(timeout):
            return None
        answer = input(prompt).strip().lower()
        if not answer:
            return ''
        return answer
    return _key_input_fd(prompt, timeout, choices, default, echo, tty_file)


def _select_option(text: str, options: list) -> str | None:
    if not options:
        return None
    value = text.strip()
    if not value:
        return None
    if value.isdigit():
        index = int(value) - 1
        if 0 <= index < len(options):
            return options[index]
        return None
    if len(value) == 1 and value.isalpha():
        index = ord(value.lower()) - ord('a')
        if 0 <= index < len(options):
            return options[index]
    return None


def _key_input_fd(prompt: str, timeout: float, choices: tuple, default: str,
                  echo: bool, tty_file) -> str | None:
    import termios
    import tty
    fd = tty_file.fileno()
    try:
        attrs = termios.tcgetattr(fd)
    except (termios.error, OSError, ValueError):
        tty_file.close()
        if not _stdin_ready(timeout):
            return None
        return input(prompt)
    decided = False
    try:
        tty.setcbreak(fd)
        sys.stdout.write(prompt)
        sys.stdout.flush()
        while True:
            key = _read_key(fd, timeout)
            if key is None:
                return None
            if key in ('\r', '\n'):
                decided = True
                return ''
            if key == '\x03':
                raise KeyboardInterrupt
            normalized = key.lower()
            if normalized in choices:
                if echo:
                    sys.stdout.write(key)
                decided = True
                return normalized
            if echo:
                sys.stdout.write(key)
            return key
    finally:
        termios.tcsetattr(fd, termios.TCSAFLUSH, attrs)
        tty_file.close()
        if decided:
            sys.stdout.write('\n')
        sys.stdout.flush()


def _hidden_input(prompt: str, timeout: float, mask: bool = False) -> str | None:
    tty_file = _open_tty()
    if tty_file is None:
        return _hidden_input_stdin(prompt, timeout)
    return _hidden_input_fd(prompt, timeout, tty_file, mask=mask)


def _hidden_input_stdin(prompt: str, timeout: float) -> str | None:
    import termios
    import tty
    try:
        fd = sys.stdin.fileno()
    except (AttributeError, ValueError, OSError):
        if not _stdin_ready(timeout):
            return None
        return input(prompt)
    try:
        attrs = termios.tcgetattr(fd)
    except (termios.error, OSError, ValueError):
        if not _stdin_ready(timeout):
            return None
        return input(prompt)
    try:
        tty.setcbreak(fd)
        sys.stdout.write(prompt)
        sys.stdout.flush()
        if not _stdin_ready(timeout):
            return None
        line = sys.stdin.readline()
        if not line:
            raise EOFError()
        return line.rstrip('\n')
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        sys.stdout.write('\n')
        sys.stdout.flush()


def _hidden_input_fd(prompt: str, timeout: float, tty_file,
                     mask: bool = False) -> str | None:
    import termios
    import tty
    fd = tty_file.fileno()
    try:
        attrs = termios.tcgetattr(fd)
    except (termios.error, OSError, ValueError):
        tty_file.close()
        return _hidden_input_stdin(prompt, timeout)
    prompted = False
    try:
        tty.setcbreak(fd)
        sys.stdout.write(prompt)
        sys.stdout.flush()
        prompted = True
        chars = []
        while True:
            key = _read_key(fd, timeout)
            if key is None:
                if not chars:
                    return None
                continue
            if key in ('\r', '\n'):
                return ''.join(chars)
            if key == '\x03':
                raise KeyboardInterrupt
            if key == '\x04':
                if not chars:
                    raise EOFError()
                continue
            if key in ('\x7f', '\b'):
                if chars:
                    chars.pop()
                    if mask:
                        sys.stdout.write('\b \b')
                        sys.stdout.flush()
                continue
            if key == '\x15':
                if chars:
                    chars.clear()
                    if mask:
                        sys.stdout.write('\r\033[K' + prompt)
                        sys.stdout.flush()
                continue
            if not key.isprintable():
                continue
            chars.append(key)
            if mask:
                sys.stdout.write('*')
                sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        tty_file.close()
        if prompted:
            sys.stdout.write('\n')
        sys.stdout.flush()


def render_markdown(token: str, state: dict) -> list[tuple[str, str]]:
    segments = []
    while token:
        if state['code_block']:
            idx = token.find('```')
            if idx != -1:
                before = token[:idx]
                if before:
                    segments.append((before, '\033[36m'))
                state['code_block'] = False
                token = token[idx + 3:]
            else:
                segments.append((token, '\033[36m'))
                token = ''
        elif state['inline_code']:
            idx = token.find('`')
            if idx != -1:
                before = token[:idx]
                if before:
                    segments.append((before, '\033[32m'))
                state['inline_code'] = False
                token = token[idx + 1:]
            else:
                segments.append((token, '\033[32m'))
                token = ''
        elif state['bold']:
            idx = token.find('**')
            if idx != -1:
                before = token[:idx]
                if before:
                    segments.append((before, '\033[1m'))
                state['bold'] = False
                token = token[idx + 2:]
            else:
                segments.append((token, '\033[1m'))
                token = ''
        else:
            idx = -1
            marker = ''
            for m in ('```', '**', '`'):
                pos = token.find(m)
                if pos != -1 and (idx == -1 or pos < idx):
                    idx = pos
                    marker = m
            if idx != -1:
                before = token[:idx]
                if before:
                    segments.append((before, ''))
                if marker == '```':
                    state['code_block'] = True
                elif marker == '**':
                    state['bold'] = True
                elif marker == '`':
                    state['inline_code'] = True
                token = token[idx + len(marker):]
            else:
                segments.append((token, ''))
                token = ''
    return segments


def reasoning_visible(config, role: str = '', sub_run: bool = False) -> bool:
    scope = verbosity_level(config, 'thinking')
    if scope in ('off', 'summary'):
        return False
    if scope == 'all':
        return True
    if scope == 'assistant':
        return not sub_run and not role
    if scope == 'agent':
        return not sub_run or bool(role)
    return False


def thought_marker_visible(config) -> bool:
    return verbosity_level(config, 'thinking') != 'off'


class StatusMetrics:
    def __init__(self):
        self.started = time.monotonic()
        self.chars = 0

    def add(self, text) -> None:
        if text:
            self.chars += len(str(text))

    def elapsed(self) -> float:
        return max(0.0, time.monotonic() - self.started)

    def tokens(self) -> int:
        return int(self.chars / 4)

    def label(self, base: str) -> str:
        return (f'{base} {self.elapsed():.1f}s '
                f'(~{self.tokens():,} tokens)')


class NullUI:
    def token(self, text):
        pass

    def thinking(self, text):
        pass

    def thinking_begin(self):
        pass

    def thinking_end(self, duration):
        pass

    def status_begin(self, label, name='', metrics=None):
        pass

    def status_end(self, note='', ok=True):
        pass

    def worked(self, name, note='', ok=True):
        pass

    def output_visible(self, role=''):
        return False

    def sub_result(self, text, role=''):
        pass

    def warning(self, msg):
        pass

    def error(self, code, msg):
        pass

    def tool_call_progress(self, name, chars):
        pass

    def tool_status(self, name, value, body):
        pass

    def activity(self, glyph, verb, label, body):
        pass

    def tool_error(self, msg):
        pass

    def tool_error_result(self, output):
        pass

    def tool_note(self, output):
        pass

    def tool_result(self, output):
        pass

    def tool_refine(self, old, new):
        pass

    def footer(self, duration, counts, note=''):
        pass

    def info(self, msg):
        pass

    def confirm(self, name, label):
        return False

    def confirm_text(self, prompt, default='y'):
        return False

    def secret(self, prompt):
        return ''

    def ask(self, question, context='', options=None, origin=''):
        return None


class HeadlessUI:
    def __init__(self, auto: str = 'deny', verbose: bool = False, stream: bool = True,
                 show_thinking: bool | None = None,
                 show_thought_duration: bool | None = None,
                 thinking_level: str | None = None,
                 footer_level: str | None = None):
        self.auto = auto
        self.verbose = verbose
        self.stream = stream
        if thinking_level is None:
            if show_thinking is True:
                thinking_level = 'all'
            elif show_thought_duration is False:
                thinking_level = 'off'
            else:
                thinking_level = 'summary'
        self.thinking_level = thinking_level
        self.footer_level = footer_level or 'summary'
        self.show_thinking = thinking_level not in ('off', 'summary')
        self.show_thought_duration = thinking_level != 'off'

    def token(self, text):
        if self.stream:
            sys.stdout.write(text)
            sys.stdout.flush()

    def thinking(self, text):
        if self.verbose and self.stream and self.show_thinking:
            sys.stderr.write(text)
            sys.stderr.flush()

    def thinking_begin(self):
        pass

    def thinking_end(self, duration):
        if not (self.verbose and self.stream):
            return
        if self.show_thought_duration:
            sys.stderr.write(f'✓ Thought {duration:.1f}s\n')

    def status_begin(self, label, name='', metrics=None):
        pass

    def status_end(self, note='', ok=True):
        if self.verbose and note:
            sys.stderr.write(f'{note}\n')

    def worked(self, name, note='', ok=True):
        if self.verbose:
            mark = '✓' if ok else '✗'
            body = f'{mark} Worked: {name}' if ok else f'{mark} {name}'
            if note:
                body += f' {note}'
            sys.stderr.write(body + '\n')

    def output_visible(self, role=''):
        return bool(self.verbose)

    def sub_result(self, text, role=''):
        if self.verbose:
            lines = []
            first = ''
            for line in str(text or '').splitlines():
                stripped = re.sub(r'^\[(?:call|delegate)[^\]]*\]\s*', '', line)
                if is_internal_verdict_line(stripped):
                    continue
                if not lines:
                    first = stripped
                lines.append(line)
            if not lines:
                return
            sys.stderr.write(f'↲ {first}\n')
            for line in lines[1:]:
                sys.stderr.write(f'  {line}\n')

    def warning(self, msg):
        sys.stderr.write(f'[warning] {msg}\n')

    def error(self, code, msg):
        label = f'[Error {code}]' if code else '[Error]'
        sys.stderr.write(f'{label} {msg}\n')

    def tool_call_progress(self, name, chars):
        pass

    def tool_status(self, name, value, body):
        if self.verbose:
            sys.stderr.write(f'[{name}: {value}]\n')
            for line in body:
                if not is_internal_verdict_line(line):
                    sys.stderr.write(f'{line}\n')

    def activity(self, glyph, verb, label, body):
        if self.verbose:
            sys.stderr.write(f'{glyph} {verb} {label}\n')
            for line in body:
                if not is_internal_verdict_line(line):
                    sys.stderr.write(f'{line}\n')

    def tool_error(self, msg):
        if self.verbose:
            sys.stderr.write(f'! {msg.split(chr(10), 1)[0]}\n')

    def tool_error_result(self, output):
        if self.verbose:
            lines = [line for line in str(output or '').splitlines()
                     if not is_internal_verdict_line(line)]
            if lines:
                sys.stderr.write('\n'.join(lines) + '\n')

    def tool_note(self, output):
        if self.verbose:
            lines = [l for l in output.splitlines() if l]
            sys.stderr.write(lines[-1] + '\n')

    def tool_result(self, output):
        if self.verbose:
            lines = [line for line in str(output or '').splitlines()
                     if not is_internal_verdict_line(line)]
            if lines:
                sys.stderr.write('\n'.join(lines) + '\n')

    def tool_refine(self, old, new):
        if self.verbose:
            sys.stderr.write(f'[refine: "{old}" → "{new}"]\n')

    def footer(self, duration, counts, note=''):
        if not self.stream or self.footer_level == 'off':
            return
        tail = f'  {note}' if note else ''
        if self.footer_level == 'full':
            n = counts.get('context')
            seg = f'{n:,} tokens' if n is not None else ''
            if seg:
                sys.stderr.write(f'✓ Done {duration:.1f}s ({seg}){tail}\n')
            else:
                sys.stderr.write(f'✓ Done {duration:.1f}s{tail}\n')
        else:
            sys.stderr.write(f'✓ Done {duration:.1f}s{tail}\n')

    def info(self, msg):
        if self.verbose:
            sys.stderr.write(msg + '\n')

    def confirm(self, name, label):
        return self.auto == 'allow'

    def confirm_text(self, prompt, default='y'):
        return self.auto == 'allow'

    def secret(self, prompt):
        return ''

    def ask(self, question, context='', options=None, origin=''):
        return None
