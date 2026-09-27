import os
import select
import sys
import threading
import time


SPINNER_FRAMES = ('⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏')
SPINNER_INTERVAL = 0.08

DIM = '\033[90m'
RED = '\033[91m'
BLUE = '\033[94m'
ORANGE = '\033[38;5;208m'
RESET = '\033[0m'


class TeeStream:
    def __init__(self, stream, path):
        self._stream = stream
        self._file = open(path, 'a', encoding='utf-8', errors='replace')

    def write(self, text):
        self._stream.write(text)
        if text and ('\r' not in text or '\n' in text):
            clean = text.replace('\001', '').replace('\002', '')
            self._file.write(clean)
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


def _timed_input(prompt: str, timeout: float, hidden: bool = False) -> str | None:
    if hidden:
        return _hidden_input(prompt, timeout)
    if timeout and timeout > 0:
        try:
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
        except (OSError, ValueError, TypeError):
            return input(prompt)
        if not ready:
            return None
    return input(prompt)


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
        return input(prompt)
    try:
        attrs = termios.tcgetattr(fd)
    except (termios.error, OSError, ValueError):
        return input(prompt)
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        tty.setcbreak(fd)
        if timeout and timeout > 0:
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
            if not ready:
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
        self.first_content = True
        self.content_newline = True
        self.md_state = {'code_block': False, 'inline_code': False, 'bold': False}
        self._spinner_thread: threading.Thread | None = None
        self._spinner_stop = threading.Event()
        self._spinner_lock = threading.Lock()
        self._spinner_frame = 0
        self._spinner_label = 'Thinking'
        self._word_buffer = ''

    def _prefix(self):
        if self.first_content:
            sys.stdout.write('\001\033[33m\002<<< \001\033[0m\002')
            sys.stdout.flush()
            self.first_content = False

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
        self._prefix()
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
        if not self._loop.config.get('show_thinking', True):
            self._start_spinner('Thinking')
            return
        self._emit('- Thinking', BLUE)
        self.content_newline = True

    def status_begin(self, label: str):
        self.flush()
        self._ensure_newline()
        if not self._loop.config.get('status_spinner', True):
            return
        self._start_spinner(str(label or 'Working'))

    def status_end(self, note: str = ''):
        if not self._loop.config.get('status_spinner', True):
            if note:
                self._emit(note, DIM)
            return
        label = self._spinner_label.rstrip('.').strip()
        self._stop_spinner()
        body = f'✓ {label}' if label else '✓ done'
        if note:
            body += f' {note}'
        self._emit(body, DIM)

    def _spinner_run(self):
        while not self._spinner_stop.is_set():
            frame = SPINNER_FRAMES[self._spinner_frame % len(SPINNER_FRAMES)]
            self._spinner_frame += 1
            with self._spinner_lock:
                if self._spinner_stop.is_set():
                    break
                sys.stdout.write(f'\r\033[K{frame} {self._spinner_label}')
                sys.stdout.flush()
            time.sleep(SPINNER_INTERVAL)

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
        if not self._loop.config.get('show_thinking', True):
            return
        self._write(text, DIM)
        self.content_newline = text.endswith('\n')

    def thinking_end(self, duration):
        self.flush()
        self._stop_spinner()
        self._ensure_newline()
        if self._loop.config.get('show_thinking', True):
            if self._loop.config.get('show_thought_duration', True):
                self._emit(f'(Thought {duration:.1f}s)', DIM)
        else:
            self._emit(f'+ Thought {duration:.1f}s', BLUE)
        self.content_newline = True

    def warning(self, msg):
        self.flush()
        self._ensure_newline()
        self._emit(f'[warning] {msg}', '\033[93m')

    def error(self, code, msg):
        self.flush()
        self._ensure_newline()
        label = f'[Error {code}]' if code else '[Error]'
        self._emit(f'{label} {msg}', RED)

    def tool_status(self, name, value, body):
        self.flush()
        self._ensure_newline()
        self._emit(f'[{name}: {value}]', ORANGE)
        for line in body:
            self._emit(line, DIM)

    def activity(self, glyph, verb, label, body):
        self.flush()
        self._ensure_newline()
        self._emit(f'{glyph} {verb} {label}', ORANGE)
        for line in body:
            self._emit(line, DIM)

    def tool_error(self, msg):
        self.flush()
        self._ensure_newline()
        self._emit(f'! {msg.split(chr(10), 1)[0]}', RED)

    def tool_error_result(self, output):
        self.flush()
        self._ensure_newline()
        for line in output.splitlines():
            self._emit(line, RED)

    def tool_note(self, output):
        self.flush()
        self._ensure_newline()
        lines = [l for l in output.splitlines() if l]
        self._emit(lines[-1], DIM)

    def tool_result(self, output):
        self.flush()
        self._ensure_newline()
        for line in output.splitlines():
            self._emit(line, DIM)

    def tool_refine(self, old, new):
        self.flush()
        self._ensure_newline()
        self._emit(f'[refine: "{old}" → "{new}"]', DIM)

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
        self.flush()
        self._ensure_newline()
        if self._loop.config.get('show_context_size', True):
            seg = self._footer_tokens(counts)
            body = f'({duration:.1f}s, {seg})' if seg else f'({duration:.1f}s)'
        else:
            body = f'({duration:.1f}s)'
        if note:
            body += f'  {note}'
        self._emit(body, DIM)
        self.content_newline = True

    def info(self, msg):
        self.flush()
        self._ensure_newline()
        self._emit(msg)

    def confirm(self, name, label):
        self.flush()
        self._ensure_newline()
        timeout = self._confirm_timeout()
        hidden = bool(self._loop.config.get('hide_confirm_input', False))
        prompt = f'\001{ORANGE}\002? {label} - approve? [Y/n] \001{RESET}\002'
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
                sys.stdout.write(
                    f'? {label} - no answer in {timeout:g}s, denied\n')
                return False
            normalized = answer.strip().lower()
            if normalized in ('', 'y', 'yes'):
                return True
            if normalized in ('n', 'no'):
                return False
            sys.stdout.write('? please answer y or n\n')

    def _confirm_timeout(self) -> float:
        loop = getattr(self, '_loop', None)
        config = getattr(loop, 'config', None) if loop is not None else None
        if config is None:
            return 0.0
        return max(0.0, float(config.get('confirm_timeout', 0) or 0))

    def ask(self, question, context='', options=None, origin=''):
        self.flush()
        self._ensure_newline()
        timeout = self._confirm_timeout()
        prefix = ''
        if origin and origin != self._loop.current_session.session_name:
            prefix = f'[{origin}] '
        self._emit(f'{prefix}Ask: {question}', ORANGE)
        if context:
            self._emit(context, DIM)
        options = list(options or [])
        for i, opt in enumerate(options, 1):
            self._emit(f'  {i}. {opt}', DIM)
        if options:
            self._emit('  (pick a number, or type your own)', DIM)
        prompt = f'\001{ORANGE}\002? Answer: \001{RESET}\002'
        try:
            answer = _timed_input(prompt, timeout)
        except EOFError:
            sys.stdout.write('\n')
            return None
        except KeyboardInterrupt:
            sys.stdout.write('\n')
            raise
        if answer is None:
            sys.stdout.write('? no answer given\n')
            return None
        text = answer.strip()
        if not text:
            return None
        if options and text.isdigit():
            index = int(text) - 1
            if 0 <= index < len(options):
                return options[index]
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

    def status_begin(self, label):
        pass

    def status_end(self, note=''):
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


class BufferUI:
    def __init__(self, run, max_lines: int = 0):
        self.run = run
        self._partial = ''
        if max_lines:
            run.max_buffer_lines = int(max_lines)

    def _feed(self, text):
        if not text:
            return
        self._partial += text
        while '\n' in self._partial:
            line, self._partial = self._partial.split('\n', 1)
            self.run.append_buffer(line)

    def _flush(self):
        if self._partial:
            self.run.append_buffer(self._partial)
            self._partial = ''

    def _line(self, text):
        self._flush()
        self.run.append_buffer(text)

    def token(self, text):
        self._feed(text)

    def thinking(self, text):
        self._feed(text)

    def thinking_begin(self):
        self._flush()

    def thinking_end(self, duration):
        self._flush()

    def status_begin(self, label):
        self._flush()

    def status_end(self, note=''):
        self._flush()
        if note:
            self._line(note)

    def warning(self, msg):
        self._line(f'[warning] {msg}')

    def error(self, code, msg):
        label = f'[Error {code}]' if code else '[Error]'
        self._line(f'{label} {msg}')

    def tool_status(self, name, value, body):
        self._line(f'[{name}: {value}]')
        for line in body:
            self._line(line)

    def activity(self, glyph, verb, label, body):
        self._line(f'{glyph} {verb} {label}')
        for line in body:
            self._line(line)

    def tool_error(self, msg):
        self._line(f'! {msg.split(chr(10), 1)[0]}')

    def tool_error_result(self, output):
        for line in output.splitlines():
            self._line(line)

    def tool_note(self, output):
        lines = [l for l in output.splitlines() if l]
        if lines:
            self._line(lines[-1])

    def tool_result(self, output):
        for line in output.splitlines():
            self._line(line)

    def tool_refine(self, old, new):
        self._line(f'[refine: "{old}" → "{new}"]')

    def footer(self, duration, counts, note=''):
        self._line(f'({duration:.1f}s)')

    def info(self, msg):
        self._line(msg)

    def confirm(self, name, label):
        return False

    def ask(self, question, context='', options=None, origin=''):
        return None


class SubRunUI(BufferUI):
    def __init__(self, run, parent, max_lines: int = 0,
                 forward_all: bool = False):
        super().__init__(run, max_lines)
        self._parent = parent
        self._forward_all = forward_all

    def activity(self, glyph, verb, label, body):
        super().activity(glyph, verb, label, body)
        if self._forward_all or glyph == '→':
            self._parent.activity(glyph, verb, label, body)


class HeadlessUI:
    def __init__(self, auto: str = 'deny', verbose: bool = False, stream: bool = True,
                 show_thinking: bool = True, show_thought_duration: bool = True,
                 footer_tokens: list | None = None):
        self.auto = auto
        self.verbose = verbose
        self.stream = stream
        self.show_thinking = show_thinking
        self.show_thought_duration = show_thought_duration
        self.footer_tokens = footer_tokens or ['context']

    def token(self, text):
        if self.stream:
            sys.stdout.write(text)
            sys.stdout.flush()

    def thinking(self, text):
        if self.verbose and self.stream:
            sys.stderr.write(text)
            sys.stderr.flush()

    def thinking_begin(self):
        if self.verbose and self.stream and self.show_thinking:
            sys.stderr.write('- Thinking\n')

    def thinking_end(self, duration):
        if not (self.verbose and self.stream):
            return
        if self.show_thinking:
            sys.stderr.write('\n')
            if self.show_thought_duration:
                sys.stderr.write(f'(Thought {duration:.1f}s)\n')
        else:
            sys.stderr.write(f'+ Thought {duration:.1f}s\n')

    def status_begin(self, label):
        pass

    def status_end(self, note=''):
        if self.verbose and note:
            sys.stderr.write(f'{note}\n')

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
        if self.stream:
            parts = []
            for key in self.footer_tokens:
                n = counts.get(key)
                if n is None:
                    continue
                parts.append(f'{n:,} tokens' if key == 'context' else f'{n}t')
            seg = '/'.join(parts)
            tail = f'  {note}' if note else ''
            if seg:
                sys.stderr.write(f'({duration:.1f}s, {seg}){tail}\n')
            else:
                sys.stderr.write(f'({duration:.1f}s){tail}\n')

    def info(self, msg):
        if self.verbose:
            sys.stderr.write(msg + '\n')

    def confirm(self, name, label):
        return self.auto == 'allow'

    def ask(self, question, context='', options=None, origin=''):
        return None
