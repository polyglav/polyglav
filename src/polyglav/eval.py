from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .config import Config
from .engine import Engine
from .ui import HeadlessUI

DEFAULT_EVAL_PERMISSION = {
    'read': 'allow',
    'list': 'allow',
    'web': 'allow',
    'edit': 'deny',
    'bash': 'deny',
    'mcp': 'deny',
    'call': 'allow',
    'delegate': 'allow',
}


class EvalFixture:
    def __init__(self, id: str, task: str, description: str = '',
                 files: dict | None = None, expected: list | None = None,
                 verifier: dict | None = None,
                 tool_permission: dict | None = None,
                 tools_deny: list | None = None):
        self.id = id
        self.task = task
        self.description = description or ''
        self.files = dict(files or {})
        self.expected = list(expected or [])
        self.verifier = dict(verifier or {})
        self.tool_permission = dict(tool_permission or {})
        self.tools_deny = list(tools_deny or [])

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'task': self.task,
            'description': self.description,
            'files': self.files,
            'expected': self.expected,
            'verifier': self.verifier,
            'tool_permission': self.tool_permission,
            'tools_deny': self.tools_deny,
        }

    @classmethod
    def from_dict(cls, data: dict, id: str | None = None) -> 'EvalFixture':
        source = dict(data)
        if id is not None:
            source['id'] = id
        if not source.get('id') or not source.get('task'):
            raise ValueError('fixture requires id and task')
        return cls(
            id=str(source['id']),
            task=str(source['task']),
            description=str(source.get('description', '')),
            files=source.get('files'),
            expected=source.get('expected'),
            verifier=source.get('verifier'),
            tool_permission=source.get('tool_permission'),
            tools_deny=source.get('tools_deny'),
        )


def verify_fixture(fixture: EvalFixture, names: list[str],
                   trace: list[dict]) -> bool:
    v = fixture.verifier
    if 'exact' in v and names != list(v['exact']):
        return False
    for name in v.get('must_include', []):
        if name not in names:
            return False
    for name in v.get('avoid', []):
        if name in names:
            return False
    max_calls = v.get('max_calls')
    if max_calls is not None and len(names) > int(max_calls):
        return False
    min_calls = v.get('min_calls')
    if min_calls is not None and len(names) < int(min_calls):
        return False
    for tool, want in (v.get('args') or {}).items():
        if not any(
                e.get('name') == tool
                and all(e.get('arguments', {}).get(k) == val
                        for k, val in want.items())
                for e in trace):
            return False
    return True


def redundant_count(trace: list[dict]) -> int:
    seen: set = set()
    redundant = 0
    for t in trace:
        key = (t['name'], json.dumps(t.get('arguments') or {}, sort_keys=True))
        if key in seen:
            redundant += 1
        else:
            seen.add(key)
    return redundant


def token_total(usage: dict | None) -> int:
    if not usage:
        return 0
    total = usage.get('total_tokens')
    if total:
        return int(total)
    return int(usage.get('prompt_tokens', 0)) + int(usage.get('completion_tokens', 0))


def _eval_config(source: Config, overrides: dict,
                 fixture: EvalFixture) -> dict:
    permission = dict(DEFAULT_EVAL_PERMISSION)
    permission.update(fixture.tool_permission)
    deny = list(source.get('tools.deny') or [])
    deny.extend(fixture.tools_deny)
    return {
        'provider': overrides.get('provider') or source.get('provider', 'ollama'),
        'model': overrides.get('model') or source.get('model', ''),
        'base_url': overrides.get('base_url') or source.get('base_url', ''),
        'temperature': source.get('temperature', 0.7),
        'max_tokens': source.get('max_tokens', 0),
        'tool_calling': True,
        'tool_permission': permission,
        'tools.deny': deny,
    }


def _provision(worktree: Path, fixture: EvalFixture, config_data: dict):
    worktree.mkdir(parents=True, exist_ok=True)
    polyglav_dir = worktree / '.polyglav'
    polyglav_dir.mkdir(parents=True, exist_ok=True)
    (polyglav_dir / 'config.json').write_text(json.dumps(config_data, indent=2))
    for rel, content in fixture.files.items():
        target = worktree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')


def run_fixture(fixture: EvalFixture, source: Config | None = None,
                overrides: dict | None = None,
                provider=None) -> dict:
    source = source or Config()
    overrides = overrides or {}
    config_data = _eval_config(source, overrides, fixture)
    cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp:
        worktree = Path(tmp)
        _provision(worktree, fixture, config_data)
        ui = HeadlessUI(auto='allow', stream=False, verbose=False)
        engine = Engine(Config(path=str(worktree)), ui=ui, provider=provider)
        try:
            os.chdir(worktree)
            result = engine.chat(fixture.task, origin='eval')
        finally:
            os.chdir(cwd)
        trace = list(result.tool_calls or [])
        names = [t['name'] for t in trace]
        errors = len(result.errors) + sum(
            1 for turn in engine.current_session.turns
            for part in turn.get('parts') or []
            if part.get('type') == 'tool' and part.get('is_error'))
        return {
            'id': fixture.id,
            'trace': trace,
            'names': names,
            'accuracy': 1 if names == fixture.expected else 0,
            'pass': verify_fixture(fixture, names, trace),
            'calls': len(trace),
            'redundant': redundant_count(trace),
            'errors': errors,
            'tokens': token_total(result.usage),
            'status': result.status,
        }


def run_suite(fixtures: dict[str, EvalFixture], source: Config,
              overrides: dict | None = None,
              provider=None) -> tuple[list[dict], dict]:
    results = [run_fixture(f, source, overrides, provider)
               for f in fixtures.values()]
    return results, summarize(results)


def summarize(results: list[dict]) -> dict:
    n = len(results)

    def avg(key: str) -> float:
        return round(sum(r[key] for r in results) / n, 2) if n else 0.0

    return {
        'fixtures': n,
        'accuracy': avg('accuracy'),
        'pass_rate': avg('pass'),
        'avg_calls': avg('calls'),
        'avg_redundant': avg('redundant'),
        'errors': sum(r['errors'] for r in results),
        'total_tokens': sum(r['tokens'] for r in results),
        'avg_tokens': round(sum(r['tokens'] for r in results) / n, 1) if n else 0.0,
    }


def _load_fixture_file(path: Path) -> EvalFixture | None:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return EvalFixture.from_dict(data, id=path.stem)
    except ValueError:
        return None


def discover_fixtures(local_dir: Path | None = None,
                      global_dir: Path | None = None,
                      plugin_manager=None) -> dict[str, EvalFixture]:
    fixtures: dict[str, EvalFixture] = {}
    if plugin_manager is not None:
        plugin_fixtures: dict[str, dict] = {}
        plugin_manager.register_fixtures(plugin_fixtures)
        for fid, data in plugin_fixtures.items():
            try:
                fixtures[fid] = EvalFixture.from_dict(data, id=fid)
            except ValueError:
                continue
    for directory in (global_dir, local_dir):
        if directory is None or not directory.is_dir():
            continue
        for path in sorted(directory.glob('*.json')):
            fixture = _load_fixture_file(path)
            if fixture is not None:
                fixtures[fixture.id] = fixture
    return fixtures


def discover_eval(source: Config) -> dict[str, EvalFixture]:
    from .plugins.manager import PluginManager
    local = source.local_path.parent / 'eval'
    home = source.GLOBAL_DIR if source.GLOBAL_DIR is not None else Path.home()
    global_ = home / '.config' / 'polyglav' / 'eval'
    pm = PluginManager(source)
    pm.load()
    return discover_fixtures(local, global_, pm)


def select_fixtures(fixtures: dict[str, EvalFixture],
                    query: str | None) -> dict[str, EvalFixture]:
    if not query:
        return dict(fixtures)
    exact = {fid: f for fid, f in fixtures.items() if fid == query}
    if exact:
        return exact
    return {fid: f for fid, f in fixtures.items() if query in fid}


def format_results(results: list[dict], summary: dict) -> str:
    lines = [
        f'{"fixture":<26} {"acc":<5} {"pass":<5} {"calls":<6} '
        f'{"redun":<6} {"err":<4} {"tokens":<9} {"status":<9}',
        '-' * 76,
    ]
    for r in results:
        lines.append(
            f'{r["id"][:26]:<26} {r["accuracy"]:<5} {str(r["pass"]):<5} '
            f'{r["calls"]:<6} {r["redundant"]:<6} {r["errors"]:<4} '
            f'{r["tokens"]:<9} {r["status"]:<9}')
    s = summary
    lines.append('-' * 76)
    lines.append(
        f'{s["fixtures"]} fixtures - accuracy {s["accuracy"]:.2f}, '
        f'pass {s["pass_rate"]:.2f}, avg calls {s["avg_calls"]}, '
        f'avg redundant {s["avg_redundant"]}, errors {s["errors"]}, '
        f'tokens {s["total_tokens"]} ({s["avg_tokens"]}/fixture)')
    return '\n'.join(lines)


def run_compare(fixtures: dict[str, EvalFixture], source: Config,
                providers: list[str], model: str = '') -> list[dict]:
    rows = []
    for provider in providers:
        _, summary = run_suite(fixtures, source, {'provider': provider, 'model': model})
        rows.append({'provider': provider, 'summary': summary})
    return rows


def format_compare(rows: list[dict]) -> str:
    keys = ('fixtures', 'accuracy', 'pass_rate', 'avg_calls',
            'avg_redundant', 'errors', 'avg_tokens')
    lines = [f'{"provider":<12}' + ''.join(f'{k:<12}' for k in keys)]
    lines.append('-' * (12 + 12 * len(keys)))
    for row in rows:
        s = row['summary']
        cells = ''.join(f'{s[k]:<12}' for k in keys)
        lines.append(f'{row["provider"][:12]:<12}{cells}')
    return '\n'.join(lines)