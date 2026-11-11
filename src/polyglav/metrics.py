from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from . import get_version
from .config import Config
from .cost import cached_tokens, estimate_cost, rates_from_config, token_parts
from .engine import Engine
from .modes import merge_policy, mode_cap, read_keys
from .ui import HeadlessUI

DEFAULT_METRIC_PERMISSION = {
    'read': 'allow',
    'list': 'allow',
    'web': 'allow',
    'edit': 'deny',
    'bash': 'deny',
    'mcp': 'deny',
    'call': 'deny',
    'delegate': 'deny',
    'ask': 'deny',
}


class MetricConfigError(ValueError):
    pass


def _default_permission(mode: str) -> dict:
    permission = dict(DEFAULT_METRIC_PERMISSION)
    permission['edit'] = 'allow' if mode == 'write' else 'deny'
    return permission


def now_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def tokens_for(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def content_hash(text: str) -> str:
    return hashlib.sha1((text or '').encode('utf-8')).hexdigest()[:12]


def match_evidence(text: str, evidence: list['Evidence']) -> list[str]:
    low = (text or '').lower()
    found = []
    for item in evidence:
        if any(needle and needle.lower() in low for needle in item.needles):
            found.append(item.id)
    return found


def probe_correct(answer: str, probe: 'Probe') -> bool:
    low = (answer or '').lower()
    return any(canonical and canonical.lower() in low
               for canonical in probe.canonical)


_PROMPT_ORDER = ('summary', 'instructions', 'system', 'plan', 'todo')


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ''


def _source_hash() -> str:
    root = Path(__file__).resolve().parent
    digest = hashlib.sha1()
    try:
        for path in sorted(root.rglob('*.py')):
            digest.update(str(path.relative_to(root)).encode('utf-8'))
            digest.update(path.read_bytes())
    except OSError:
        return ''
    return digest.hexdigest()[:12]


def _system_prompt_hash(snapshot: dict | None) -> str:
    if not snapshot:
        return content_hash('')
    parts = [block.get('content') or ''
             for block in (snapshot.get('blocks') or [])
             if block.get('kind') in _PROMPT_ORDER]
    return content_hash('\n'.join(parts))


def _tools_hash(engine: Engine) -> str:
    try:
        schema = engine._tool_schema()
    except Exception:
        schema = []
    entries = []
    for item in schema:
        function = item.get('function') or {}
        entries.append({
            'name': function.get('name', ''),
            'description': function.get('description', ''),
        })
    return content_hash(json.dumps(entries, sort_keys=True))


def _instrument_block(engine: Engine, baseline: dict | None) -> dict:
    try:
        package_version = metadata.version('polyglav')
    except metadata.PackageNotFoundError:
        package_version = ''
    return {
        'name': 'polyglav',
        'version': get_version(),
        'package_version': package_version,
        'commit': _git_commit(),
        'source_hash': _source_hash(),
        'system_prompt_hash': _system_prompt_hash(baseline),
        'tools_hash': _tools_hash(engine),
        'python': platform.python_version(),
        'platform': platform.platform(),
    }


def _settings_block(engine: Engine) -> dict:
    config = engine.config
    mode = config.get('mode') or 'read'
    permissions, allow, deny = merge_policy(config, mode)
    return {
        'mode': mode,
        'cap': mode_cap(config, mode),
        'tool_permission': permissions,
        'tools.allow': allow,
        'tools.deny': deny,
        'compact_auto': bool(config.get('compact_auto', True)),
        'compact_at': config.get('compact_at'),
        'compact_before': config.get('compact_before'),
        'compact_keep': config.get('compact_keep'),
        'context_window': config.get('context_window'),
        'temperature': config.get('temperature'),
        'max_tokens': config.get('max_tokens'),
    }


@dataclass
class Evidence:
    id: str
    needles: list[str] = field(default_factory=list)
    critical: bool = True

    @classmethod
    def from_dict(cls, data: dict, index: int = 0) -> 'Evidence':
        return cls(
            id=str(data.get('id') or f'e{index + 1}'),
            needles=[str(value) for value in (data.get('needles') or [])],
            critical=bool(data.get('critical', True)),
        )


@dataclass
class Probe:
    id: str
    question: str
    checkpoint: str = ''
    canonical: list[str] = field(default_factory=list)
    at_turn: int = 0

    @classmethod
    def from_dict(cls, data: dict, index: int = 0) -> 'Probe':
        return cls(
            id=str(data.get('id') or f'p{index + 1}'),
            question=str(data.get('question') or ''),
            checkpoint=str(data.get('checkpoint') or ''),
            canonical=[str(value) for value in (data.get('canonical') or [])],
            at_turn=int(data.get('at_turn') or 0),
        )


@dataclass
class MetricTask:
    id: str
    prompt: str = ''
    turns: list[str] = field(default_factory=list)
    description: str = ''
    files: dict = field(default_factory=dict)
    tool_permission: dict = field(default_factory=dict)
    tools_deny: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    goal_evidence: list[str] = field(default_factory=list)
    probes: list[Probe] = field(default_factory=list)
    compact: dict = field(default_factory=dict)
    seed: int = 0
    mode: str = 'read'
    temperature: float = 0.0
    system_prompt: str = ''

    @classmethod
    def from_dict(cls, data: dict, id: str | None = None) -> 'MetricTask':
        source = dict(data)
        if id is not None:
            source['id'] = id
        task_id = str(source.get('id') or '')
        prompt = str(source.get('prompt') or '')
        turns = [str(value) for value in (source.get('turns') or [])]
        if not task_id or (not prompt and not turns):
            raise ValueError('task requires id and prompt or turns')
        evidence = [Evidence.from_dict(item, index)
                    for index, item in enumerate(source.get('evidence') or [])
                    if isinstance(item, dict)]
        probes = [Probe.from_dict(item, index)
                  for index, item in enumerate(source.get('probes') or [])
                  if isinstance(item, dict)]
        mode = str(source.get('mode') or 'read').strip().lower()
        if mode not in ('read', 'write'):
            raise MetricConfigError(
                f"metric task '{task_id}' has unknown mode '{mode}'")
        try:
            temperature = float(source.get('temperature', 0.0) or 0.0)
        except (TypeError, ValueError):
            raise MetricConfigError(
                f"metric task '{task_id}' has invalid temperature")
        return cls(
            id=task_id,
            prompt=prompt,
            turns=turns,
            description=str(source.get('description') or ''),
            files=dict(source.get('files') or {}),
            tool_permission=dict(source.get('tool_permission') or {}),
            tools_deny=[str(value) for value in (source.get('tools_deny') or [])],
            evidence=evidence,
            goal_evidence=[str(value) for value in (source.get('goal_evidence') or [])],
            probes=probes,
            compact=dict(source.get('compact') or {}),
            seed=int(source.get('seed') or 0),
            mode=mode,
            temperature=temperature,
            system_prompt=str(source.get('system_prompt') or ''),
        )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'prompt': self.prompt,
            'turns': self.turns,
            'description': self.description,
            'files': self.files,
            'tool_permission': self.tool_permission,
            'tools_deny': self.tools_deny,
            'evidence': [item.__dict__ for item in self.evidence],
            'goal_evidence': self.goal_evidence,
            'probes': [item.__dict__ for item in self.probes],
            'compact': self.compact,
            'seed': self.seed,
            'mode': self.mode,
            'temperature': self.temperature,
            'system_prompt': self.system_prompt,
        }


@dataclass
class MetricRecord:
    task_id: str
    condition: str
    provider: str = ''
    model: str = ''
    seed: int = 0
    temperature: float = 0.0
    config_hash: str = ''
    task_hash: str = ''
    started_at: str = ''
    ended_at: str = ''
    run_end: dict = field(default_factory=dict)
    goal_evidence: list = field(default_factory=list)
    rounds: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    edits: list = field(default_factory=list)
    compactions: list = field(default_factory=list)
    probes: list = field(default_factory=list)
    cost: dict = field(default_factory=dict)
    instrument: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'task_id': self.task_id,
            'condition': self.condition,
            'provider': self.provider,
            'model': self.model,
            'seed': self.seed,
            'temperature': self.temperature,
            'config_hash': self.config_hash,
            'task_hash': self.task_hash,
            'started_at': self.started_at,
            'ended_at': self.ended_at,
            'run_end': self.run_end,
            'goal_evidence': self.goal_evidence,
            'rounds': self.rounds,
            'tool_calls': self.tool_calls,
            'edits': self.edits,
            'compactions': self.compactions,
            'probes': self.probes,
            'cost': self.cost,
            'instrument': self.instrument,
            'settings': self.settings,
            'artifacts': self.artifacts,
        }

    def write(self, path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2), encoding='utf-8')
        return target


def _config_hash(provider: str, model: str, temperature: float,
                 seed: int, condition: str, task_id: str) -> str:
    manifest = json.dumps({
        'provider': provider, 'model': model, 'temperature': temperature,
        'seed': seed, 'condition': condition, 'task': task_id,
    }, sort_keys=True)
    return hashlib.sha1(manifest.encode('utf-8')).hexdigest()[:12]


def _task_config(source: Config, task: MetricTask,
                 overrides: dict) -> dict:
    mode = overrides.get('mode') or task.mode
    permission = _default_permission(mode)
    permission.update(source.get('tool_permission') or {})
    permission.update(task.tool_permission)
    deny = list(source.get('tools.deny') or [])
    deny.extend(task.tools_deny)
    allow = list(source.get('tools.allow') or [])
    provider = overrides.get('provider') or ''
    model = overrides.get('model') or source.get('model') or ''
    if provider and model and '/' not in model:
        model = f'{provider}/{model}'
    compact = task.compact or {}
    return {
        'model': model,
        'base_url': overrides.get('base_url') or source.get('base_url', ''),
        'temperature': task.temperature,
        'max_tokens': source.get('max_tokens', 0),
        'tool_calling': True,
        'tool_permission': permission,
        'access': source.get('access') or {},
        'tools.allow': allow,
        'tools.deny': deny,
        'system_prompt': task.system_prompt,
        'mode': mode,
        'modes': source.get('modes') or {},
        'project_instructions': source.get('project_instructions', 'AGENTS.md'),
        'reasoning': source.get('reasoning', 'auto'),
        'compact_auto': compact.get('auto', source.get('compact_auto', True)),
        'compact_at': compact.get('at', source.get('compact_at', 170000)),
        'compact_before': compact.get('before', source.get('compact_before', 3)),
        'compact_keep': compact.get('keep', source.get('compact_keep', 1)),
        'context_window': compact.get('window', source.get('context_window', 0)),
        'cost.rates': source.get('cost.rates', {}),
    }


def _check_task_permissions(task: MetricTask, config_data: dict) -> None:
    mode = config_data.get('mode') or task.mode
    if mode_cap(config_data, mode) != 'read':
        return
    merged_edit = (config_data.get('tool_permission') or {}).get('edit')
    if merged_edit is True or str(merged_edit).lower() in ('allow', 'ask'):
        raise MetricConfigError(
            f"metric task '{task.id}' requests edit "
            f"but the effective mode cap is read")
    read = read_keys(config_data)
    for key in sorted(task.tool_permission or {}):
        action = task.tool_permission[key]
        requested = action is True or str(action).lower() in ('allow', 'ask')
        if requested and key not in read:
            raise MetricConfigError(
                f"metric task '{task.id}' requests {key} "
                f"but the effective mode cap is read")


def _provision(worktree: Path, task: MetricTask, config_data: dict) -> None:
    worktree.mkdir(parents=True, exist_ok=True)
    polyglav_dir = worktree / '.polyglav'
    polyglav_dir.mkdir(parents=True, exist_ok=True)
    (polyglav_dir / 'config.json').write_text(
        json.dumps(config_data, indent=2), encoding='utf-8')
    for rel, content in task.files.items():
        target = worktree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')


class _Recorder:
    def __init__(self, task: MetricTask, condition: str, rates: dict,
                 task_hash: str, engine: Engine):
        self.task = task
        self.condition = condition
        self.rates = rates
        self.task_hash = task_hash
        self.engine = engine
        self.started_at = now_stamp()
        self._mono_start = time.monotonic()
        self.rounds: list[dict] = []
        self.tool_calls: list[dict] = []
        self.edits: list[dict] = []
        self.compactions: list[dict] = []
        self.probes: list[dict] = []
        self.patches: list[dict] = []
        self.statuses: list[str] = []
        self.last_result = None
        self.main_rounds = 0
        self.sub_rounds = 0
        self.baseline: dict | None = None
        self.turn_snapshots: list[dict] = []
        self.final_snapshot: dict | None = None
        self.probe_parts = {'input': 0, 'output': 0, 'cache_read': 0}
        self.probe_cost = 0.0
        self._round: dict | None = None
        self._pending_before: dict | None = None
        self._compaction_pairs: list[dict] = []

    def _offset(self, value) -> float:
        if not isinstance(value, (int, float)):
            return 0.0
        return round(value - self._mono_start, 3)

    def _snapshot(self) -> dict:
        return copy.deepcopy(self.engine.context_snapshot())

    def _blocks(self, blocks: list[dict]) -> list[dict]:
        out = []
        for block in blocks:
            out.append({
                'kind': block.get('kind', ''),
                'turn': block.get('turn', 0),
                'part': block.get('part'),
                'tokens': block.get('tokens', 0),
                'evidence_ids': match_evidence(
                    block.get('content') or '', self.task.evidence),
            })
        return out

    def observe(self, event: dict) -> None:
        kind = event.get('type')
        if kind == 'request_start':
            if self.baseline is None:
                self.baseline = self._snapshot()
            self._round = {
                'turn': event.get('turn', 0),
                'round': event.get('round', 0),
                'role': event.get('role', ''),
                'sub': bool(event.get('sub')),
                'session': event.get('session', ''),
                'ctx_tokens': event.get('ctx_tokens', 0),
                'context_blocks': self._blocks(
                    event.get('context_blocks') or []),
                'started_at': event.get('started_at', ''),
                'at': self._offset(event.get('started_mono')),
            }
        elif kind == 'request_end':
            current = self._round or {
                'turn': event.get('turn', 0),
                'round': event.get('round', 0),
                'role': event.get('role', ''),
                'sub': bool(event.get('sub')),
                'session': event.get('session', ''),
                'ctx_tokens': 0,
                'context_blocks': [],
                'started_at': '',
                'at': 0.0,
            }
            usage = event.get('usage')
            current.update({
                'input_tokens': event.get('input_tokens', 0),
                'cache_read_tokens': event.get('cache_read_tokens', 0),
                'cache_reported': bool(event.get('cache_reported')),
                'completion_tokens': event.get('completion_tokens', 0),
                'ctx_tokens': event.get('ctx_tokens',
                                        current.get('ctx_tokens', 0)),
                'ended_at': event.get('ended_at', ''),
                'duration': event.get('duration', 0.0),
                'status': event.get('status', ''),
                'finish_reason': event.get('finish_reason', ''),
                'usage': usage,
                'cost': estimate_cost(usage, self.rates),
            })
            if current.get('sub'):
                self.sub_rounds += 1
            else:
                self.main_rounds += 1
            self.rounds.append(current)
            self._round = None
        elif kind == 'tool_end':
            self._tool(event)
        elif kind == 'compaction_before':
            self._pending_before = {
                'index': event.get('compaction_index', 0),
                'turn': event.get('turn', 0),
                'snapshot': self._snapshot(),
            }
        elif kind == 'compaction':
            index = event.get('compaction_index', 0)
            before = self._pending_before
            if before is not None and before.get('index') != index:
                before = None
            self._compaction_pairs.append({
                'index': index,
                'turn': event.get('turn', 0),
                'before': before.get('snapshot') if before else None,
                'after': self._snapshot(),
            })
            self._pending_before = None
            item = {key: value for key, value in event.items()
                    if key != 'type'}
            item['cost'] = estimate_cost(event.get('usage'), self.rates)
            self.compactions.append(item)

    def _tool(self, event: dict) -> None:
        output = event.get('output') or ''
        arguments = event.get('arguments') or {}
        if not isinstance(arguments, dict):
            arguments = {}
        path = event.get('path') or arguments.get('path', '')
        try:
            argument_text = json.dumps(arguments, sort_keys=True)
        except (TypeError, ValueError):
            argument_text = ''
        truncated = len(argument_text) > 2000
        evidence_ids = match_evidence(output, self.task.evidence)
        entry = {
            'name': event.get('name', ''),
            'turn': event.get('turn', 0),
            'round': event.get('round', 0),
            'part': event.get('part', 0),
            'category': event.get('category', ''),
            'path': path,
            'arguments': {} if truncated else arguments,
            'arguments_truncated': truncated,
            'result_tokens': event.get('result_tokens', 0),
            'evidence_ids': evidence_ids,
            'content_hash': content_hash(output),
            'is_error': bool(event.get('is_error')),
        }
        self.tool_calls.append(entry)
        name = entry['name']
        if entry['category'] == 'edit' or name in ('file_edit', 'file_write'):
            self.edits.append({
                'turn': entry['turn'],
                'round': entry['round'],
                'path': path,
                'category': entry['category'],
                'result_tokens': entry['result_tokens'],
                'evidence_ids': evidence_ids,
                'content_hash': entry['content_hash'],
            })
            if output:
                self.patches.append({
                    'turn': entry['turn'],
                    'round': entry['round'],
                    'path': path,
                    'patch': output,
                    'bytes': len(output),
                    'lines': output.count('\n') + 1,
                })

    def note_result(self, result) -> None:
        self.last_result = result
        self.statuses.append(result.status)

    def capture_turn(self) -> None:
        self.turn_snapshots.append(self._snapshot())

    def capture_final(self) -> None:
        self.final_snapshot = self._snapshot()

    def _call_probe(self, provider, snapshot: dict, probe: Probe,
                    phase: str, after_turn: int,
                    compaction_index: int) -> tuple[str, dict | None, dict | None]:
        messages = copy.deepcopy(snapshot.get('messages') or [])
        messages.append({'role': 'user', 'content': probe.question})
        had_session = hasattr(provider, 'session_id')
        original = getattr(provider, 'session_id', None) if had_session else None
        if had_session:
            provider.session_id = (
                f'{original or "probe"}:probe:{probe.id}:{phase}:'
                f'{after_turn}:{compaction_index}')
        try:
            try:
                result = provider.chat_nonstreaming(messages, tools=None)
            except Exception as e:
                result = {'error': {'code': 0, 'message': str(e)}}
        finally:
            if had_session:
                provider.session_id = original
        if not isinstance(result, dict):
            result = {}
        usage = result.get('usage')
        answer = (result.get('content') or '').strip()
        error = result.get('error')
        return answer, usage, error

    def _ctx_tokens(self, usage: dict | None, messages: list[dict]) -> int:
        if isinstance(usage, dict):
            prompt = usage.get('prompt_tokens')
            prompt = prompt if isinstance(prompt, int) else 0
            cached = cached_tokens(usage)
            if prompt or cached:
                return prompt or cached
        chars = sum(len(m.get('content') or '') for m in messages)
        return max(1, chars // 4)

    def _probe_snapshot(self, provider, snapshot: dict | None, phase: str,
                        after_turn: int, compaction_index: int = 0) -> None:
        if not snapshot:
            return
        for probe in self.task.probes:
            if (phase == 'turn' and probe.at_turn > 0
                    and probe.at_turn != after_turn):
                continue
            answer, usage, error = self._call_probe(
                provider, snapshot, probe, phase, after_turn, compaction_index)
            messages = list(snapshot.get('messages') or [])
            messages.append({'role': 'user', 'content': probe.question})
            cost = estimate_cost(usage, self.rates)
            parts = token_parts(usage)
            for key in self.probe_parts:
                self.probe_parts[key] += parts[key]
            self.probe_cost += cost
            self.probes.append({
                'id': probe.id,
                'phase': phase,
                'after_turn': after_turn,
                'compaction_index': compaction_index,
                'question': probe.question,
                'answer': answer,
                'correct': probe_correct(answer, probe),
                'checkpoint': probe.checkpoint,
                'ctx_tokens': self._ctx_tokens(usage, messages),
                'usage': usage,
                'cost': cost,
                'error': error,
                'evidence_ids': match_evidence(answer, self.task.evidence),
            })

    def run_snapshot_probes(self, provider) -> None:
        if self.baseline:
            self._probe_snapshot(provider, self.baseline, 'baseline', 0)
        for pair in self._compaction_pairs:
            index = pair.get('index', 0)
            turn = pair.get('turn', 0)
            if pair.get('before'):
                self._probe_snapshot(provider, pair['before'],
                                     'compaction_before', turn, index)
            self._probe_snapshot(provider, pair['after'],
                                 'compaction_after', turn, index)
        if self.condition == 'multi':
            total = len(self.turn_snapshots)
            for index, snapshot in enumerate(self.turn_snapshots, 1):
                phase = 'final' if index == total else 'turn'
                self._probe_snapshot(provider, snapshot, phase, index)
        elif self.final_snapshot:
            self._probe_snapshot(provider, self.final_snapshot, 'final', 1)

    def finish(self, engine: Engine, reason: str = 'completed') -> MetricRecord:
        provider, _, model = engine.model_target()
        total_parts = {'input': 0, 'output': 0, 'cache_read': 0}
        total_cost = 0.0
        for item in self.rounds:
            parts = token_parts(item.get('usage'))
            for key in total_parts:
                total_parts[key] += parts[key]
            total_cost += float(item.get('cost') or 0.0)
        for item in self.compactions:
            parts = token_parts(item.get('usage'))
            for key in total_parts:
                total_parts[key] += parts[key]
            total_cost += float(item.get('cost') or 0.0)
        status = 'ok'
        if 'error' in self.statuses:
            status = 'error'
        elif self.statuses:
            status = self.statuses[-1]
        if status not in ('ok', 'truncated'):
            reason = status
        agent_total = round(total_cost, 6)
        probe_total = round(self.probe_cost, 6)
        temperature = float(
            engine.config.get('temperature', self.task.temperature) or 0.0)
        return MetricRecord(
            task_id=self.task.id,
            condition=self.condition,
            provider=provider,
            model=model,
            seed=self.task.seed,
            temperature=temperature,
            config_hash=_config_hash(provider, model, temperature,
                                     self.task.seed, self.condition,
                                     self.task.id),
            task_hash=self.task_hash,
            started_at=self.started_at,
            ended_at=now_stamp(),
            run_end={
                'reason': reason,
                'status': status,
                'turns': len(engine.current_session.turns),
                'main_turns': len(self.statuses),
                'rounds': len(self.rounds),
                'main_rounds': self.main_rounds,
                'sub_rounds': self.sub_rounds,
            },
            goal_evidence=list(self.task.goal_evidence),
            rounds=self.rounds,
            tool_calls=self.tool_calls,
            edits=self.edits,
            compactions=self.compactions,
            probes=self.probes,
            cost={
                **total_parts,
                'total': agent_total,
                'probe': {**self.probe_parts, 'total': probe_total},
                'total_including_probe': round(agent_total + probe_total, 6),
            },
            instrument=_instrument_block(engine, self.baseline),
            settings=_settings_block(engine),
            artifacts={'patches': self.patches},
        )


def run_task(task: MetricTask, source: Config | None = None,
             condition: str = 'single',
             overrides: dict | None = None,
             provider=None, mode: str | None = None) -> MetricRecord:
    source = source or Config()
    overrides = dict(overrides or {})
    if mode is not None:
        mode = str(mode).strip().lower()
        if mode not in ('read', 'write'):
            raise MetricConfigError(
                f"metric task '{task.id}' has unknown mode '{mode}'")
        overrides['mode'] = mode
    if task.mode not in ('read', 'write'):
        raise MetricConfigError(
            f"metric task '{task.id}' has unknown mode '{task.mode}'")
    condition = condition if condition in ('single', 'multi') else 'single'
    config_data = _task_config(source, task, overrides)
    _check_task_permissions(task, config_data)
    task_hash = content_hash(json.dumps(task.to_dict(), sort_keys=True))
    cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp:
        worktree = Path(tmp)
        _provision(worktree, task, config_data)
        config = Config(path=str(worktree))
        ui = HeadlessUI(auto='allow', stream=False, verbose=False)
        engine = Engine(config, ui=ui, provider=provider,
                        approve_models=True)
        engine.load_or_create_session(None)
        provider_name, _, model = engine.model_target()
        rates = rates_from_config(config, provider_name, model)
        recorder = _Recorder(task, condition, rates, task_hash, engine)
        engine.add_observer(recorder.observe)
        try:
            os.chdir(worktree)
            if condition == 'single':
                prompt = task.prompt or '\n\n'.join(task.turns)
                recorder.note_result(engine.chat(prompt, origin='metric'))
                recorder.capture_turn()
            else:
                for prompt in (task.turns or [task.prompt]):
                    recorder.note_result(engine.chat(prompt, origin='metric'))
                    recorder.capture_turn()
            recorder.capture_final()
            recorder.run_snapshot_probes(engine.provider)
        finally:
            os.chdir(cwd)
        return recorder.finish(engine)


def _load_task_file(path: Path) -> MetricTask | None:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return MetricTask.from_dict(data, id=path.stem)
    except ValueError:
        return None


def discover_tasks(local_dir: Path | None = None,
                   global_dir: Path | None = None) -> dict[str, MetricTask]:
    tasks: dict[str, MetricTask] = {}
    for directory in (global_dir, local_dir):
        if directory is None or not directory.is_dir():
            continue
        for path in sorted(directory.glob('*.json')):
            task = _load_task_file(path)
            if task is not None:
                tasks[task.id] = task
    return tasks


def discover_metrics(source: Config) -> dict[str, MetricTask]:
    local = source.local_path.parent / 'metrics'
    home = source.GLOBAL_DIR if source.GLOBAL_DIR is not None else Path.home()
    global_ = home / '.config' / 'polyglav' / 'metrics'
    return discover_tasks(local, global_)


def select_tasks(tasks: dict[str, MetricTask],
                 query: str | None) -> dict[str, MetricTask]:
    if not query:
        return dict(tasks)
    exact = {tid: task for tid, task in tasks.items() if tid == query}
    if exact:
        return exact
    return {tid: task for tid, task in tasks.items() if query in tid}


def format_results(records: list[MetricRecord]) -> str:
    lines = [
        f'{"task":<24} {"cond":<7} {"main":<5} {"probes":<7} '
        f'{"ok":<4} {"comp":<5} {"peak":<9} {"cost":<10} '
        f'{"probe":<10} {"status":<10}',
        '-' * 100,
    ]
    for record in records:
        peak = max((int(item.get('ctx_tokens') or 0)
                    for item in record.rounds), default=0)
        correct = sum(1 for item in record.probes if item.get('correct'))
        probe_cost = (record.cost.get('probe') or {}).get('total', 0)
        lines.append(
            f'{record.task_id[:24]:<24} {record.condition:<7} '
            f'{record.run_end.get("main_rounds", 0):<5} '
            f'{len(record.probes):<7} {correct:<4} '
            f'{len(record.compactions):<5} {peak:<9} '
            f'{record.cost.get("total", 0):<10} {probe_cost:<10} '
            f'{record.run_end.get("status", ""):<10}')
    lines.append('-' * 100)
    lines.append(f'{len(records)} run(s)')
    return '\n'.join(lines)


def cmd_metrics(args) -> int:
    source = Config(path=getattr(args, 'path', None))
    tasks = discover_metrics(source)
    if getattr(args, 'action', None) == 'list':
        if not tasks:
            print('No metric tasks found.')
            return 0
        for tid in sorted(tasks):
            task = tasks[tid]
            label = task.description or task.prompt or ' / '.join(task.turns)
            print(f'{tid} - {label[:70]} '
                  f'(evidence: {len(task.evidence)}, probes: {len(task.probes)})')
        return 0
    selected = select_tasks(tasks, getattr(args, 'task', None))
    if not selected:
        print('No metric tasks found.', file=sys.stderr)
        return 1
    conditions = [value.strip() for value in
                  (getattr(args, 'condition', 'single') or 'single').split(',')
                  if value.strip()]
    overrides = {}
    if getattr(args, 'provider', None):
        overrides['provider'] = args.provider
    if getattr(args, 'model', None):
        overrides['model'] = args.model
    if getattr(args, 'base_url', None):
        overrides['base_url'] = args.base_url
    records = []
    failed = False
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    out_dir = (Path(args.out) if getattr(args, 'out', None)
               else source.local_path.parent / 'metrics' / 'runs')
    for task in selected.values():
        for condition in conditions:
            try:
                record = run_task(task, source, condition, overrides,
                                  mode=getattr(args, 'mode', None))
            except MetricConfigError as e:
                print(f'Error: {e}', file=sys.stderr)
                failed = True
                continue
            records.append(record)
            try:
                record.write(out_dir / f'{task.id}_{condition}_{stamp}.json')
            except OSError as e:
                print(f'Error writing metric record: {e}', file=sys.stderr)
    if not records and failed:
        return 1
    if getattr(args, 'output', 'table') == 'json':
        sys.stdout.write(json.dumps([record.to_dict() for record in records],
                                    indent=2) + '\n')
    else:
        sys.stdout.write(format_results(records) + '\n')
    return 1 if failed else 0
