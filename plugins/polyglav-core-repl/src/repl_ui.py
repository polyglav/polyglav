import re
import sys
import threading
import time

from polyglav.config import verbosity_level
from polyglav.ui import (
    BRIGHT_BLUE, CYAN, DIM, GREEN, ITALIC_GRAY, MAGENTA, ORANGE, RED, RESET,
    YELLOW, SPINNER_FRAMES, SPINNER_INTERVAL, colors_enabled, glyph, glyph_map,
    reasoning_visible, thought_marker_visible, render_markdown, _hidden_input,
    _key_input, _select_option, _timed_input, is_internal_verdict_line,
)


class ReplUI:
    interactive = True
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
        self._status_metrics = None
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
        if last == -1 and len(self._word_buffer) < 120:
            return
        if last == -1:
            last = len(self._word_buffer) - 1
        self._render(self._word_buffer[:last + 1])
        self._word_buffer = self._word_buffer[last + 1:]

    def flush(self):
        if self._word_buffer:
            self._render(self._word_buffer)
            self._word_buffer = ''

    def _thinking_visible(self) -> bool:
        return reasoning_visible(
            self._loop.config,
            role=str(getattr(self._loop, 'role', '') or ''),
            sub_run=bool(getattr(self._loop, '_sub_run', False)))

    def output_visible(self, role: str = '') -> bool:
        scope = verbosity_level(self._loop.config, 'output')
        if scope == 'all':
            return True
        if scope == 'agent':
            return bool(role)
        return False

    def _output_visible(self, role: str = '') -> bool:
        return self.output_visible(role)

    def thinking_begin(self):
        if not thought_marker_visible(self._loop.config):
            return
        self.flush()
        self._ensure_newline()
        self._thinking_streamed = False
        self._start_spinner('Thinking')

    def status_begin(self, label: str, name: str = '', metrics=None):
        self.flush()
        self._ensure_newline()
        text = str(label or 'Working').rstrip('.').strip()
        self._status_name = (name or text).rstrip('.').strip()
        self._status_metrics = metrics
        mark = glyph(self._loop.config, 'enter', '↳')
        self._emit(f'{mark} {text}', DIM)
        self._start_spinner(text)

    def status_end(self, note: str = '', ok: bool = True):
        self._stop_spinner()
        name = self._status_name
        self._status_metrics = None
        self.worked(name, note, ok=ok)

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
                sys.stdout.write(f'\r\033[K{frame} {self._spinner_text()}')
                sys.stdout.flush()
            time.sleep(SPINNER_INTERVAL)

    def _spinner_text(self) -> str:
        label = self._spinner_label
        if (self._status_metrics is not None
                and verbosity_level(self._loop.config, 'status') == 'on'):
            label = self._status_metrics.label(label)
        return label

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
        if not self._thinking_visible():
            return
        self.flush()
        if not self._thinking_streamed:
            self._stop_spinner()
            self._thinking_streamed = True
        self._write(text, DIM)
        self.content_newline = text.endswith('\n')

    def thinking_end(self, duration):
        if not thought_marker_visible(self._loop.config):
            return
        self.flush()
        self._stop_spinner()
        self._ensure_newline()
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

    def tool_call_progress(self, name, chars):
        if verbosity_level(self._loop.config, 'tools') == 'off':
            return
        self.flush()
        self._start_spinner(str(name))

    def tool_status(self, name, value, body):
        self._stop_spinner()
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
        self._stop_spinner()
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

    def sub_result(self, text, role: str = ''):
        if not self._output_visible(role):
            return
        self.flush()
        self._ensure_newline()
        mark = glyph(self._loop.config, 'return', '↲')
        lines = str(text or '').splitlines() or ['']
        first = re.sub(r'^\[(?:call|delegate)[^\]]*\]\s*', '', lines[0])
        self._emit(f'{mark} {first}', DIM)
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
        n = counts.get('context')
        return f'{n:,} tokens' if n is not None else ''

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
            own = counts.get('total')
            tree = counts.get('tree')
            if own and tree and tree != own:
                body += f' ({own:,}/{tree:,} tokens)'
            elif own:
                body += f' ({own:,} tokens)'
            elif counts.get('context') is not None:
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
                    answer = _key_input(prompt, timeout, ('y', 'n'),
                                        default='y', echo=not hidden)
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
                    return False
                self._emit(f'{mark} please answer y or n', YELLOW)
        finally:
            self._prompting.clear()

    def confirm_text(self, prompt, default='y'):
        timeout = self._confirm_timeout()
        try:
            answer = _key_input(prompt, timeout, ('y', 'n'),
                                default=default, echo=True)
        except (EOFError, KeyboardInterrupt):
            sys.stdout.write('\n')
            return False
        if answer is None:
            return False
        normalized = answer.strip().lower()
        if normalized == '':
            return default == 'y'
        if normalized in ('y', 'yes'):
            return True
        if normalized in ('n', 'no'):
            return False
        return False

    def secret(self, prompt):
        try:
            value = _hidden_input(prompt, 0.0, mask=True)
        except EOFError:
            sys.stdout.write('\n')
            return ''
        except KeyboardInterrupt:
            sys.stdout.write('\n')
            raise
        return str(value or '')

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
        question_color = ORANGE if colors_enabled() else ''
        self._emit(f'{mark} {prefix}{question}', question_color)
        if context:
            for line in str(context).splitlines():
                self._emit(f'  {line}')
        for i, opt in enumerate(options, 1):
            self._emit(f'  {i}) {opt}')
        prompt = '> '
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


    def sub_ui(self, engine, role: str = '', label: str = '',
               depth: int = 0):
        return SubRunUI(self, engine, role=role, label=label, depth=depth)

class SubRunUI:
    interactive = True
    is_sub_run = True
    def __init__(self, parent, engine, role: str = '', label: str = '',
                 depth: int = 0):
        self.parent = parent
        self._loop = engine
        self.role = role
        self.label = label
        self.depth = depth
        self._prefix = '  ' * (depth + 1)
        self._at_line_start = True
        self.streamed = False
        self.content_newline = True

    def _enabled(self) -> bool:
        return self.parent.output_visible(self.role)

    def _thinking_visible(self) -> bool:
        return reasoning_visible(
            self._loop.config, role=self.role, sub_run=True)

    def _begin(self) -> None:
        if self._at_line_start:
            self.parent._stop_spinner()
            self.parent._ensure_newline()

    def _stream(self, text: str, ansi: str = '') -> None:
        if not self._enabled() or not text:
            return
        self.parent.flush()
        self._begin()
        for chunk in text.splitlines(keepends=True):
            if self._at_line_start:
                self.parent._write(self._prefix, DIM)
                self._at_line_start = False
            self.parent._write(chunk, ansi)
            if chunk.endswith('\n'):
                self._at_line_start = True
        if not text.endswith('\n'):
            self._at_line_start = False
        self.parent.content_newline = text.endswith('\n')

    def _line(self, text: str, ansi: str = DIM) -> None:
        if not self._enabled():
            return
        self.parent.flush()
        self._begin()
        self.parent._emit(self._prefix + text, ansi)
        self._at_line_start = True

    def token(self, text):
        if self._enabled():
            self.streamed = True
            self._stream(text)

    def thinking(self, text):
        if self._thinking_visible():
            self.parent.flush()
            self._begin()
            self._stream(text, DIM)

    def thinking_begin(self):
        pass

    def thinking_end(self, duration):
        if self._enabled() and thought_marker_visible(self._loop.config):
            mark = glyph(self._loop.config, 'done', '✓')
            self._line(f'{mark} Thought {duration:.1f}s', DIM)

    def status_begin(self, label, name='', metrics=None):
        if not self._enabled() or self.depth > 0:
            return
        self.parent.status_begin(self._prefix + str(label), name=name,
                                 metrics=metrics)

    def status_end(self, note='', ok=True):
        if not self._enabled() or self.depth > 0:
            return
        self.parent.status_end(note, ok=ok)

    def worked(self, name, note='', ok=True):
        if self._enabled():
            self.parent.worked(self._prefix + str(name), note, ok=ok)

    def output_visible(self, role=''):
        return self.parent.output_visible(role)

    def sub_result(self, text, role=''):
        if self.parent.output_visible(role):
            self.parent.sub_result(text, role=role)

    def warning(self, msg):
        if self._enabled():
            self._line(f'{glyph(self._loop.config, "warning", "!")} {msg}',
                       YELLOW)

    def error(self, code, msg):
        if self._enabled():
            mark = glyph(self._loop.config, 'error', '✗')
            text = f'{mark} [{code}] {msg}' if code else f'{mark} {msg}'
            self._line(text, RED)

    def tool_call_progress(self, name, chars):
        if self._enabled():
            self.parent.tool_call_progress(name, chars)

    def tool_status(self, name, value, body):
        if not self._enabled():
            return
        self.parent.tool_status(name, self._prefix + str(value), body)

    def activity(self, glyph_value, verb, label, body):
        if not self._enabled():
            return
        self.parent.activity(glyph_value, verb, self._prefix + str(label), body)

    def tool_error(self, msg):
        if self._enabled():
            self.parent.tool_error(msg)

    def tool_error_result(self, output):
        if self._enabled():
            self.parent.tool_error_result(output)

    def tool_note(self, output):
        if self._enabled():
            self.parent.tool_note(output)

    def tool_result(self, output):
        if not self._enabled():
            return
        level = verbosity_level(self._loop.config, 'tools')
        if level == 'full':
            for line in str(output or '').splitlines():
                self._line(line, DIM)
        elif level != 'off':
            self.parent._tool_output_hint()

    def tool_refine(self, old, new):
        if self._enabled():
            self.parent.tool_refine(old, new)

    def footer(self, duration, counts, note=''):
        pass

    def info(self, msg):
        if self._enabled():
            self._line(str(msg), DIM)

    def confirm(self, name, label):
        return False

    def confirm_text(self, prompt, default='y'):
        return False

    def secret(self, prompt):
        return ''

    def ask(self, question, context='', options=None, origin=''):
        return self.parent.ask(question, context=context, options=options,
                               origin=origin)

    def _stop_spinner(self):
        self.parent._stop_spinner()

    def _ensure_newline(self):
        self.parent._ensure_newline()
