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
ORANGE = '\033[38;5;208m'
MAGENTA = '\033[95m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
ITALIC_GRAY = '\033[3;90m'
RESET = '\033[0m'


def glyph_map(config) -> dict:
    raw = config.get('glyphs') if config is not None else {}
    if isinstance(raw, str):
        return dict(ASCII_GLYPHS) if raw.strip().lower() == 'ascii' else {}
    return dict(raw) if isinstance(raw, dict) else {}


def glyph(config, key: str, default: str) -> str:
    return str(glyph_map(config).get(key, default))

_ANSI_RE = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


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


def _hidden_input(prompt: str, timeout: float) -> str | None:
    tty_file = _open_tty()
    if tty_file is None:
        return _hidden_input_stdin(prompt, timeout)
    return _hidden_input_fd(prompt, timeout, tty_file)


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
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        tty.setcbreak(fd)
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


def _hidden_input_fd(prompt: str, timeout: float, tty_file) -> str | None:
    import termios
    import tty
    fd = tty_file.fileno()
    try:
        attrs = termios.tcgetattr(fd)
    except (termios.error, OSError, ValueError):
        tty_file.close()
        return _hidden_input_stdin(prompt, timeout)
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        tty.setcbreak(fd)
        chars = []
        while True:
            key = _read_key(fd, timeout)
            if key is None:
                if not chars:
                    return None
                continue
            if key in ('\r', '\n'):
                return ''.join(chars)
            chars.append(key)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        tty_file.close()
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


class ReplUI:
    def __init__(self, loop):
        self._loop = loop
        self.content_newline = True
        self.md_state = {'code_block': False, 'inline_code': False, 'bold': False}
        self._spinner_thread: threading.Thread | None = None
        self._spinner_stop = threading.Event()
        self._spinner_lock = threading.Lock()
        self._spinner_frame = 0
        self._spinner_label = 'Thinking'
        self._prompting = threading.Event()
        self._word_buffer = ''
        self._thinking_streamed = False
        self._status_name = ''
        self._hints_shown: set[str] = set()

    def _write(self, text, ansi=''):
        if ansi:
            sys.stdout.write(f'\001{ansi}\002{text}\001\033[0m\002')
        else:
            sys.stdout.write(text)
        sys.stdout.flush()

    def _emit(self, text, ansi='', newline=True):
        self._write(text, ansi)
        if newline:
            sys.stdout.write('\n')
            sys.stdout.flush()

    def _ensure_newline(self):
        if not self.content_newline:
            sys.stdout.write('\n')
            sys.stdout.flush()
        self.content_newline = True

    def token(self, text):
        if self._loop.config.get('word_streaming', True):
            self._word_buffer += text
            self._flush_words()
        else:
            self._render(text)

    def _render(self, text):
        if self._loop.config.get('markdown_streaming'):
            for seg, ansi in render_markdown(text, self.md_state):
                self._write(seg, ansi)
        else:
            self._write(text)
        self.content_newline = text.endswith('\n')

    def _flush_words(self):
        last = -1
        for i, ch in enumerate(self._word_buffer):
            if ch.isspace():
                last = i
        if last == -1:
            return
        self._render(self._word_buffer[:last + 1])
        self._word_buffer = self._word_buffer[last + 1:]

    def flush(self):
        if self._word_buffer:
            self._render(self._word_buffer)
            self._word_buffer = ''

    def thinking_begin(self):
        self.flush()
        self._ensure_newline()
        if verbosity_level(self._loop.config, 'thinking') == 'off':
            return
        self._thinking_streamed = False
        self._start_spinner('Thinking')

    def status_begin(self, label: str, name: str = ''):
        self.flush()
        self._ensure_newline()
        if verbosity_level(self._loop.config, 'subruns') == 'off':
            return
        text = str(label or 'Working').rstrip('.').strip()
        self._status_name = (name or text).rstrip('.').strip()
        mark = glyph(self._loop.config, 'enter', '↳')
        self._emit(f'{mark} {text}', DIM)
        self._start_spinner(text)

    def status_end(self, note: str = '', ok: bool = True):
        if verbosity_level(self._loop.config, 'subruns') == 'off':
            return
        self._stop_spinner()
        self.worked(self._status_name, note, ok=ok)

    def worked(self, name: str, note: str = '', ok: bool = True):
        self.flush()
        self._ensure_newline()
        key = 'done' if ok else 'error'
        mark = glyph(self._loop.config, key, '✓' if ok else '✗')
        body = f'{mark} Worked: {name}' if ok else f'{mark} {name}'
        if note:
            body += f' {note}'
        self._emit(body, DIM if ok else RED)

    def _spinner_frames(self):
        raw = glyph_map(self._loop.config).get('spinner')
        if isinstance(raw, str) and raw:
            return tuple(raw)
        return SPINNER_FRAMES

    def _spinner_run(self):
        while not self._spinner_stop.is_set():
            if self._prompting.is_set():
                time.sleep(SPINNER_INTERVAL)
                continue
            frames = self._spinner_frames()
            frame = frames[self._spinner_frame % len(frames)]
            self._spinner_frame += 1
            with self._spinner_lock:
                if self._spinner_stop.is_set():
                    break
                sys.stdout.write(f'\r\033[K{frame} {self._spinner_label}')
                sys.stdout.flush()
            time.sleep(SPINNER_INTERVAL)

    def _clear_spinner_line(self):
        if self._spinner_thread is not None and self._spinner_thread.is_alive():
            with self._spinner_lock:
                sys.stdout.write('\r\033[K')
                sys.stdout.flush()

    def _start_spinner(self, label: str | None = None):
        if self._spinner_thread is not None and self._spinner_thread.is_alive():
            if label:
                self._spinner_label = label
            return
        if label:
            self._spinner_label = label
        self._spinner_stop.clear()
        self._spinner_frame = 0
        self._spinner_thread = threading.Thread(
            target=self._spinner_run, name='polyglav-spinner', daemon=True)
        self._spinner_thread.start()

    def _stop_spinner(self):
        if self._spinner_thread is None or not self._spinner_thread.is_alive():
            self._spinner_thread = None
            return
        self._spinner_stop.set()
        self._spinner_thread.join(timeout=0.5)
        self._spinner_thread = None
        with self._spinner_lock:
            sys.stdout.write('\r\033[K')
            sys.stdout.flush()

    def thinking(self, text):
        self.flush()
        if verbosity_level(self._loop.config, 'thinking') != 'full':
            return
        if not self._thinking_streamed:
            self._stop_spinner()
            self._thinking_streamed = True
        self._write(text, DIM)
        self.content_newline = text.endswith('\n')

    def thinking_end(self, duration):
        self.flush()
        self._stop_spinner()
        self._ensure_newline()
        if verbosity_level(self._loop.config, 'thinking') != 'off':
            mark = glyph(self._loop.config, 'done', '✓')
            self._emit(f'{mark} Thought {duration:.1f}s', DIM)
        self.content_newline = True

    def warning(self, msg):
        self.flush()
        self._ensure_newline()
        mark = glyph(self._loop.config, 'warning', '!')
        self._emit(f'{mark} {msg}', YELLOW)

    def error(self, code, msg):
        self.flush()
        self._ensure_newline()
        mark = glyph(self._loop.config, 'error', '✗')
        text = f'{mark} [{code}] {msg}' if code else f'{mark} {msg}'
        self._emit(text, RED)

    def tool_status(self, name, value, body):
        level = verbosity_level(self._loop.config, 'tools')
        if level == 'off':
            return
        self.flush()
        self._ensure_newline()
        mark = glyph(self._loop.config, 'default', '*')
        self._emit(f'{mark} {name} {value}', DIM)
        if level == 'full':
            for line in body:
                self._emit(line, DIM)
        elif body:
            self._tool_output_hint()

    def activity(self, glyph, verb, label, body):
        level = verbosity_level(self._loop.config, 'tools')
        if level == 'off':
            return
        self.flush()
        self._ensure_newline()
        color = GREEN if glyph == '$' else DIM
        self._emit(f'{glyph} {verb} {label}', color)
        if level == 'full':
            for line in body:
                self._emit(line, DIM)
        elif body:
            self._tool_output_hint()

    def tool_error(self, msg):
        self.flush()
        self._ensure_newline()
        mark = glyph(self._loop.config, 'error', '✗')
        self._emit(f'{mark} {msg.split(chr(10), 1)[0]}', RED)

    def tool_error_result(self, output):
        self.flush()
        self._ensure_newline()
        lines = output.splitlines()
        if not lines:
            return
        mark = glyph(self._loop.config, 'error', '✗')
        self._emit(f'{mark} {lines[0]}', RED)
        for line in lines[1:]:
            self._emit(f'  {line}', DIM)

    def tool_note(self, output):
        if verbosity_level(self._loop.config, 'tools') == 'off':
            return
        self.flush()
        self._ensure_newline()
        lines = [l for l in output.splitlines() if l]
        self._emit(lines[-1], DIM)

    def tool_result(self, output):
        level = verbosity_level(self._loop.config, 'tools')
        if level == 'off':
            return
        self.flush()
        self._ensure_newline()
        if level == 'summary':
            self._tool_output_hint()
            return
        for line in output.splitlines():
            self._emit(line, DIM)

    def sub_result(self, text):
        level = verbosity_level(self._loop.config, 'subruns')
        if level == 'off':
            return
        self.flush()
        self._ensure_newline()
        mark = glyph(self._loop.config, 'return', '↲')
        lines = str(text or '').splitlines() or ['']
        first = re.sub(r'^\[(?:call|delegate)[^\]]*\]\s*', '', lines[0])
        self._emit(f'{mark} {first}', DIM)
        if level == 'summary':
            if len(lines) > 1:
                self._emit('  ...', DIM)
            return
        for line in lines[1:]:
            self._emit(f'  {line}', DIM)

    def _tool_output_hint(self):
        session = getattr(self._loop, 'current_session', None)
        name = str(getattr(session, 'session_name', '') or '')
        key = f'tool_output:{name}'
        if key in self._hints_shown:
            return
        self._hints_shown.add(key)
        turns = getattr(session, 'turns', None) or []
        target = f' {len(turns)}' if turns else ''
        self._emit(f'/print{target} to see the full output', ITALIC_GRAY)

    def tool_refine(self, old, new):
        self.flush()
        self._ensure_newline()
        self._emit(f'  Refine query to: {new}', DIM)

    def _footer_tokens(self, counts):
        parts = []
        for key in self._loop.config.get('footer_tokens', ['context']):
            n = counts.get(key)
            if n is None:
                continue
            if key == 'context':
                parts.append(f'{n:,} tokens')
            else:
                parts.append(f'{n}t')
        return '/'.join(parts)

    def footer(self, duration, counts, note=''):
        level = verbosity_level(self._loop.config, 'footer')
        if level == 'off':
            return
        self.flush()
        self._ensure_newline()
        mark = glyph(self._loop.config, 'done', '✓')
        if level == 'full':
            seg = self._footer_tokens(counts)
            body = f'{mark} Done {duration:.1f}s ({seg})' if seg else f'{mark} Done {duration:.1f}s'
        else:
            body = f'{mark} Done {duration:.1f}s'
            parts = self._loop.config.get('footer_tokens', ['context'])
            if 'context' in parts and counts.get('context') is not None:
                body += f' ({counts["context"]:,} tokens)'
        if note:
            body += f'  {note}'
        self._emit(body, DIM)
        self.content_newline = True

    def info(self, msg):
        self.flush()
        self._ensure_newline()
        self._emit(msg, DIM)

    def confirm(self, name, label):
        self.flush()
        self._ensure_newline()
        timeout = self._confirm_timeout()
        hidden = bool(self._loop.config.get('hide_confirm_input', False))
        mark = glyph(self._loop.config, 'question', '?')
        done = glyph(self._loop.config, 'done', '✓')
        prompt = f'\001{DIM}\002{mark} {label} - approve? [Y/n] \001{RESET}\002'
        self._prompting.set()
        self._clear_spinner_line()
        try:
            while True:
                try:
                    answer = _timed_input(prompt, timeout, hidden=hidden)
                except EOFError:
                    sys.stdout.write('\n')
                    return False
                except KeyboardInterrupt:
                    sys.stdout.write('\n')
                    raise
                if answer is None:
                    self._emit(
                        f'{mark} {label} - no answer in {timeout:g}s, denied',
                        YELLOW)
                    return False
                normalized = answer.strip().lower()
                if normalized in ('', 'y', 'yes'):
                    self._emit(f'{done} approved', DIM)
                    return True
                if normalized in ('n', 'no'):
                    self._emit(f'{done} declined', DIM)
                    return False
                self._emit(f'{mark} please answer y or n', YELLOW)
        finally:
            self._prompting.clear()

    def _confirm_timeout(self) -> float:
        loop = getattr(self, '_loop', None)
        config = getattr(loop, 'config', None) if loop is not None else None
        if config is None:
            return 0.0
        return max(0.0, float(config.get('confirm_timeout', 0) or 0))

    def ask(self, question, context='', options=None, origin=''):
        self.flush()
        self._prompting.set()
        self._clear_spinner_line()
        self._ensure_newline()
        timeout = self._confirm_timeout()
        prefix = ''
        if origin and origin != self._loop.current_session.session_name:
            prefix = f'[{origin}] '
        options = list(options or [])
        mark = glyph(self._loop.config, 'question', '?')
        self._emit(f'{mark} {prefix}{question}', DIM)
        if context:
            self._emit(f'  {context}', DIM)
        for i, opt in enumerate(options, 1):
            self._emit(f'  {i}) {opt}', DIM)
        from .modes import mode_color, resolve_mode
        spec, _ = resolve_mode(self._loop.config, self._loop._mode())
        color = mode_color(spec)
        prompt = f'\001{color}\002>\001{RESET}\002 '
        try:
            answer = _timed_input(prompt, timeout)
        except EOFError:
            sys.stdout.write('\n')
            return None
        except KeyboardInterrupt:
            sys.stdout.write('\n')
            raise
        finally:
            self._prompting.clear()
        if answer is None:
            self._emit(f'{mark} no answer given', YELLOW)
            return None
        text = answer.strip()
        if not text:
            return None
        selected = _select_option(text, options)
        if selected is not None:
            return selected
        return text


class NullUI:
    def token(self, text):
        pass

    def thinking(self, text):
        pass

    def thinking_begin(self):
        pass

    def thinking_end(self, duration):
        pass

    def status_begin(self, label, name=''):
        pass

    def status_end(self, note='', ok=True):
        pass

    def worked(self, name, note='', ok=True):
        pass

    def sub_result(self, text):
        pass

    def warning(self, msg):
        pass

    def error(self, code, msg):
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

    def ask(self, question, context='', options=None, origin=''):
        return None


class HeadlessUI:
    def __init__(self, auto: str = 'deny', verbose: bool = False, stream: bool = True,
                 show_thinking: bool | None = None,
                 show_thought_duration: bool | None = None,
                 footer_tokens: list | None = None,
                 thinking_level: str | None = None,
                 footer_level: str | None = None):
        self.auto = auto
        self.verbose = verbose
        self.stream = stream
        if thinking_level is None:
            if show_thinking is True:
                thinking_level = 'full'
            elif show_thought_duration is False:
                thinking_level = 'off'
            else:
                thinking_level = 'summary'
        self.thinking_level = thinking_level
        self.footer_level = footer_level or 'summary'
        self.show_thinking = thinking_level == 'full'
        self.show_thought_duration = thinking_level != 'off'
        self.footer_tokens = footer_tokens or ['context']

    def token(self, text):
        if self.stream:
            sys.stdout.write(text)
            sys.stdout.flush()

    def thinking(self, text):
        if self.verbose and self.stream and self.thinking_level == 'full':
            sys.stderr.write(text)
            sys.stderr.flush()

    def thinking_begin(self):
        pass

    def thinking_end(self, duration):
        if not (self.verbose and self.stream):
            return
        if self.thinking_level != 'off':
            sys.stderr.write(f'✓ Thought {duration:.1f}s\n')

    def status_begin(self, label, name=''):
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

    def sub_result(self, text):
        if self.verbose:
            lines = str(text or '').splitlines() or ['']
            first = re.sub(r'^\[(?:call|delegate)[^\]]*\]\s*', '', lines[0])
            sys.stderr.write(f'↲ {first}\n')
            for line in lines[1:]:
                sys.stderr.write(f'  {line}\n')

    def warning(self, msg):
        sys.stderr.write(f'[warning] {msg}\n')

    def error(self, code, msg):
        label = f'[Error {code}]' if code else '[Error]'
        sys.stderr.write(f'{label} {msg}\n')

    def tool_status(self, name, value, body):
        if self.verbose:
            sys.stderr.write(f'[{name}: {value}]\n')
            for line in body:
                sys.stderr.write(f'{line}\n')

    def activity(self, glyph, verb, label, body):
        if self.verbose:
            sys.stderr.write(f'{glyph} {verb} {label}\n')
            for line in body:
                sys.stderr.write(f'{line}\n')

    def tool_error(self, msg):
        if self.verbose:
            sys.stderr.write(f'! {msg.split(chr(10), 1)[0]}\n')

    def tool_error_result(self, output):
        if self.verbose:
            sys.stderr.write(output.rstrip('\n') + '\n')

    def tool_note(self, output):
        if self.verbose:
            lines = [l for l in output.splitlines() if l]
            sys.stderr.write(lines[-1] + '\n')

    def tool_result(self, output):
        if self.verbose:
            sys.stderr.write(output.rstrip('\n') + '\n')

    def tool_refine(self, old, new):
        if self.verbose:
            sys.stderr.write(f'[refine: "{old}" → "{new}"]\n')

    def footer(self, duration, counts, note=''):
        if not self.stream or self.footer_level == 'off':
            return
        tail = f'  {note}' if note else ''
        if self.footer_level == 'full':
            parts = []
            for key in self.footer_tokens:
                n = counts.get(key)
                if n is None:
                    continue
                parts.append(f'{n:,} tokens' if key == 'context' else f'{n}t')
            seg = '/'.join(parts)
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

    def ask(self, question, context='', options=None, origin=''):
        return None
