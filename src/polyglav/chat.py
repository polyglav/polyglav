import subprocess
import sys
import readline
from pathlib import Path

from .config import Config
from .engine import Engine
from .ui import DIM, MAGENTA, RESET, ReplUI
from .modes import mode_color, resolve_mode, unknown_mode
from . import get_version

HISTFILE = '.polyglav_history'

MAIN_PROMPT = '_ '
CONT_PROMPT = '... '


def _display_path(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(Path.home())
    except ValueError:
        return str(path)
    return '~' if str(rel) == '.' else f'~/{rel}'


def _git_branch(path: Path) -> str:
    try:
        proc = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=str(path), capture_output=True, text=True, timeout=1)
    except (OSError, subprocess.SubprocessError):
        return ''
    branch = proc.stdout.strip()
    return branch if proc.returncode == 0 and branch != 'HEAD' else ''


def _open_delim(text: str) -> str | None:
    if _overlap_count(text, '"""') % 2 == 1:
        return '"""'
    if _overlap_count(text, "'''") % 2 == 1:
        return "'''"
    return None


def _overlap_count(text: str, delim: str) -> int:
    n = 0
    i = text.find(delim)
    while i != -1:
        n += 1
        i = text.find(delim, i + 1)
    return n


def _strip_framing(text: str, delim: str) -> str:
    first = text.find(delim)
    last = text.rfind(delim)
    if first == -1 or last <= first:
        return text
    return (text[:first] + text[first + len(delim):last]
            + text[last + len(delim):]).strip('\n')


def _strip_open(text: str, delim: str) -> str:
    idx = text.find(delim)
    if idx == -1:
        return text
    return (text[:idx] + text[idx + len(delim):]).strip('\n')


class ChatLoop(Engine):
    def __init__(self, config: Config):
        ui = ReplUI(self)
        super().__init__(config, ui=ui)
        self._model_cache: dict[str, list[str]] = {}
        self._load_history(config)
        self._setup_readline()

    def _run_startup(self):
        hooks: list = []
        self._plugin_manager.register_startup(hooks)
        for hook in hooks:
            try:
                hook(self)
            except Exception:
                pass

    def active(self) -> Engine:
        return self

    def _load_history(self, config):
        hist = config.local_path.parent / HISTFILE
        if hist.exists():
            try:
                readline.read_history_file(str(hist))
            except OSError:
                pass
        readline.set_history_length(1000)

    def _save_history(self):
        hist = self.config.local_path.parent / HISTFILE
        try:
            hist.parent.mkdir(parents=True, exist_ok=True)
            readline.write_history_file(str(hist))
        except OSError:
            pass

    def _setup_readline(self):
        readline.set_completer(self._completer)
        readline.set_completer_delims(' \t\n')
        if 'libedit' in (readline.__doc__ or ''):
            readline.parse_and_bind('bind ^I rl_complete')
        else:
            readline.parse_and_bind('tab: complete')

    def _completer(self, text: str, state: int) -> str | None:
        line = readline.get_line_buffer()
        head = line[: len(line) - len(text)]
        for prefix in ('/session load ', '/sessions preview ', '/sessions delete ', '/sessions export '):
            if head.endswith(prefix):
                names = [n for n in self.sessions.list() if n.startswith(text)]
                if state < len(names):
                    return names[state] + ' '
                return None
        for prefix in ('/plugins enable ', '/plugins disable ',
                       '/plugins update ', '/plugins uninstall '):
            if head.endswith(prefix):
                pm = getattr(self, '_plugin_manager', None)
                names = [i.name for i in pm.status()] if pm else []
                options = sorted(n for n in names if n.startswith(text))
                if state < len(options):
                    return options[state] + ' '
                return None
        if head.endswith('/tool '):
            options = sorted(n for n in self._tool_names() if n.startswith(text))
            if state < len(options):
                return options[state] + ' '
            return None
        if head.endswith('/mode '):
            from .modes import mode_list
            options = sorted(m.name for m in mode_list(self.config)
                             if m.name.startswith(text))
            if state < len(options):
                return options[state] + ' '
            return None
        if head.endswith('/model '):
            return self._complete_model_ref(text, state)
        if (head.endswith('/connect ') or head.endswith('/provider ')
                or head.endswith('/providers ')
                or head.endswith('/models list ')):
            return self._complete_options(self._provider_names(), text, state)
        if head.lstrip().startswith('/'):
            cmd = head.lstrip()[1:].strip().split(maxsplit=1)[0]
            meta = self.registry.meta.get(cmd)
            if meta and meta.get('subcommands'):
                options = sorted(n for n, _ in meta['subcommands']
                                 if n.startswith(text))
                if state < len(options):
                    return options[state] + ' '
                return None
            return self._path_complete(text, state)
        if text.startswith('/'):
            term = text[1:]
            options = sorted(c for c in self.registry.commands if c.startswith(term))
            if state < len(options):
                return '/' + options[state] + ' '
            return None
        return None

    def _tool_names(self):
        if not getattr(self, '_tool_registry', None):
            return []
        policy = getattr(self, '_tool_policy', None)
        names = self._tool_registry.names()
        if policy is None:
            return names
        return [n for n in names
                if policy.allowed(n, self._tool_registry.permission_for(n))]

    def _provider_names(self):
        names = set(self._merged_providers())
        names |= {e.provider for e in self.providers.all()}
        return sorted(names)

    def _complete_options(self, options, text: str, state: int,
                          suffix: str = ' ') -> str | None:
        matches = [o for o in options if o.startswith(text)]
        if state < len(matches):
            return matches[state] + suffix
        return None

    def _complete_model_ref(self, text: str, state: int) -> str | None:
        if '/' in text:
            provider, _, _ = text.partition('/')
            names: list[str] = []
            for entry in self.models.all():
                if entry.provider == provider and entry.model not in names:
                    names.append(entry.model)
            for model in getattr(self, '_model_cache', {}).get(provider, []):
                if model not in names:
                    names.append(model)
            options = [f'{provider}/{m}' for m in names
                       if f'{provider}/{m}'.startswith(text)]
            return self._complete_options(options, text, state)
        options = [n + '/' for n in self._provider_names()
                   if n.startswith(text)]
        return self._complete_options(options, text, state, '')

    def _path_complete(self, text: str, state: int) -> str | None:
        path = Path(text) if text else Path('.')
        name = path.name
        parent = path.parent if str(path.parent) else Path('.')
        try:
            options = sorted(p for p in parent.glob(name + '*'))
        except OSError:
            options = []
        if state < len(options):
            cand = options[state]
            return str(cand) + ('/' if cand.is_dir() else ' ')
        return None

    def _read_line(self) -> str | None:
        try:
            raw = self._read_input(self._prompt())
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        line = raw.strip()
        self._reprint_line(line)
        delim = _open_delim(line)
        if delim is not None:
            return self._read_block(line, delim)
        if line.endswith('\\'):
            return self._read_continued(line)
        return line

    def _read_input(self, prompt: str) -> str:
        try:
            return input(prompt)
        finally:
            sys.stdout.write('\033[0m')
            sys.stdout.flush()

    def _reprint_line(self, text: str) -> None:
        if not text:
            return
        engine = self.active()
        if text.startswith('/'):
            color = MAGENTA
            label = '/'
            body = text[1:].strip()
        else:
            spec, _ = resolve_mode(self.config, engine._mode())
            color = mode_color(spec)
            label = '>'
            body = text
        sys.stdout.write('\033[A\r\033[K')
        sys.stdout.write(f'\001{color}\002{label} {body}\001\033[0m\002\n')
        sys.stdout.flush()

    def _read_block(self, line: str, delim: str) -> str | None:
        parts = [line]
        while True:
            try:
                nxt = self._read_input(self._cont_prompt()).rstrip()
            except (EOFError, KeyboardInterrupt):
                print()
                return None
            parts.append(nxt)
            stripped = nxt.strip()
            if stripped == delim:
                composed = _strip_framing('\n'.join(parts), delim)
                self._remember(composed)
                return composed
            if stripped == '':
                composed = _strip_open('\n'.join(parts), delim)
                self._remember(composed)
                return composed

    def _read_continued(self, line: str) -> str | None:
        parts = [line[:-1].rstrip()]
        while True:
            try:
                nxt = self._read_input(self._cont_prompt()).rstrip()
            except (EOFError, KeyboardInterrupt):
                print()
                return None
            if nxt.endswith('\\'):
                parts.append(nxt[:-1].rstrip())
                continue
            parts.append(nxt)
            composed = '\n'.join(parts)
            self._remember(composed)
            return composed

    def _remember(self, text: str):
        try:
            readline.add_history(text)
        except Exception:
            pass

    def _prompt(self) -> str:
        return MAIN_PROMPT

    def _cont_prompt(self) -> str:
        return CONT_PROMPT

    def _open_output_log(self):
        if not self.config.get('output_log', False):
            return None
        from .ui import TeeStream
        worktree = self.config.local_path.parent.parent
        base = Path(str(self.config.get('output_log_dir', '.polyglav/output')
                         or '.polyglav/output'))
        if not base.is_absolute():
            base = worktree / base
        try:
            base.mkdir(parents=True, exist_ok=True)
            name = self.current_session.session_name or 'output'
            path = base / f'{name}.txt'
            stream = TeeStream(
                sys.stdout, path,
                ansi=bool(self.config.get('output_log_ansi', False)))
            stream.write(f'# Polyglav output log - {path.name}\n')
            return stream
        except OSError:
            return None

    def run(self):
        tee = self._open_output_log()
        if tee is not None:
            sys.stdout = tee
        try:
            self._run_repl()
        finally:
            if tee is not None:
                sys.stdout = tee._stream
                tee.close()

    def _run_repl(self):
        if self.config.get('clear_screen', True):
            sys.stdout.write('\033[3J\033[2J\033[H')
            sys.stdout.flush()

        model_str = self.config.get('model', '?')
        provider_str = self.config.get('provider', '?')
        session_mode = self.current_session.mode or None
        unknown = unknown_mode(self.config, session_mode)
        if unknown:
            print(f'Unknown mode "{unknown}" - using read mode')
        spec, _ = resolve_mode(self.config, session_mode)
        mode_str = spec.name.capitalize()
        worktree = self.config.local_path.parent.parent
        location = _display_path(worktree)
        branch = _git_branch(worktree)
        if branch:
            location = f'{location}:{branch}'
        title = f'Polyglav v{get_version()}' if self.config.get('show_version', True) else 'Polyglav'
        print(f'\033[1m{title}\033[0m {DIM}{location}{RESET}')
        print(f'{DIM}\033[3m/help to list commands{RESET}')
        print(f'{DIM}@ {mode_str} mode ({provider_str}/{model_str}){RESET}')

        self._run_startup()

        while True:
            line = self._read_line()
            if line is None:
                self._save_sessions()
                self._save_history()
                break

            if not line:
                continue

            engine = self
            try:
                if line.startswith('/'):
                    engine.current_session.add_command(line)
                    engine.registry.dispatch(line)
                    engine.session_auto_save()
                elif getattr(engine, '_paused', False):
                    label = engine.role or 'root'
                    print(f'{DIM}@ Paused #{engine.current_run.id} {label}{RESET}')
                else:
                    engine.chat(line)
            except Exception as e:
                engine.current_session.add_error(0, str(e))
                print(f'\001\033[91m\002[Error]\001\033[0m\002 {e}')

        self._save_history()

    def _save_sessions(self):
        self.session_auto_save()
