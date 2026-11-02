from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .cost import estimate_cost, rates_from_config, token_parts
from .engine import Engine
from .ui import HeadlessUI

DEFAULT_METRIC_PERMISSION = {
    'read': 'allow',
    'list': 'allow',
    'web': 'allow',
    'edit': 'allow',
    'bash': 'deny',
    'mcp': 'deny',
    'call': 'deny',
    'delegate': 'deny',
    'ask': 'deny',
}


def now_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


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
    temperature: float | None = None

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
        temperature = source.get('temperature')
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
            temperature=(None if temperature is None else float(temperature)),
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
            'temperature': self.temperature,
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
    permission = dict(DEFAULT_METRIC_PERMISSION)
    permission.update(task.tool_permission)
    deny = list(source.get('tools.deny') or [])
    deny.extend(task.tools_deny)
    provider = overrides.get('provider') or ''
    model = overrides.get('model') or source.get('model') or ''
    if provider and model and '/' not in model:
        model = f'{provider}/{model}'
    compact = task.compact or {}
    return {
        'model': model,
        'base_url': overrides.get('base_url') or source.get('base_url', ''),
        'temperature': (task.temperature if task.temperature is not None
                        else source.get('temperature', 0.7)),
        'max_tokens': source.get('max_tokens', 0),
        'tool_calling': True,
        'tool_permission': permission,
        'tools.deny': deny,
        'compact_auto': compact.get('auto', source.get('compact_auto', True)),
        'compact_at': compact.get('at', source.get('compact_at', 170000)),
        'compact_before': compact.get('before', source.get('compact_before', 3)),
        'compact_keep': compact.get('keep', source.get('compact_keep', 1)),
        'context_window': compact.get('window', source.get('context_window', 0)),
        'cost.rates': source.get('cost.rates', {}),
    }


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
                 task_hash: str):
        self.task = task
        self.condition = condition
        self.rates = rates
        self.task_hash = task_hash
        self.started_at = now_stamp()
        self.rounds: list[dict] = []
        self.tool_calls: list[dict] = []
        self.edits: list[dict] = []
        self.compactions: list[dict] = []
        self.probes: list[dict] = []
        self.statuses: list[str] = []
        self.last_result = None
        self.main_rounds = 0
        self._round: dict | None = None
        self._probe: Probe | None = None
        self._ran_probes: set[str] = set()

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
            self._round = {
                'turn': event.get('turn', 0),
                'round': event.get('round', 0),
                'probe': self._probe.id if self._probe else '',
                'ctx_tokens': event.get('ctx_tokens', 0),
                'context_blocks': self._blocks(
                    event.get('context_blocks') or []),
            }
        elif kind == 'request_end':
            current = self._round or {
                'turn': event.get('turn', 0),
                'round': event.get('round', 0),
                'probe': self._probe.id if self._probe else '',
                'ctx_tokens': 0,
                'context_blocks': [],
            }
            usage = event.get('usage')
            current.update({
                'input_tokens': event.get('input_tokens', 0),
                'cache_read_tokens': event.get('cache_read_tokens', 0),
                'completion_tokens': event.get('completion_tokens', 0),
                'ctx_tokens': event.get('ctx_tokens',
                                        current.get('ctx_tokens', 0)),
                'status': event.get('status', ''),
                'finish_reason': event.get('finish_reason', ''),
                'usage': usage,
                'cost': estimate_cost(usage, self.rates),
            })
            if not current.get('probe'):
                self.main_rounds += 1
            self.rounds.append(current)
            self._round = None
        elif kind == 'tool_end':
            self._tool(event)
        elif kind == 'compaction':
            item = {key: value for key, value in event.items()
                    if key != 'type'}
            item['probe'] = self._probe.id if self._probe else ''
            item['cost'] = estimate_cost(event.get('usage'), self.rates)
            self.compactions.append(item)

    def _tool(self, event: dict) -> None:
        output = event.get('output') or ''
        evidence_ids = match_evidence(output, self.task.evidence)
        entry = {
            'name': event.get('name', ''),
            'turn': event.get('turn', 0),
            'round': event.get('round', 0),
            'part': event.get('part', 0),
            'category': event.get('category', ''),
            'result_tokens': event.get('result_tokens', 0),
            'evidence_ids': evidence_ids,
            'content_hash': content_hash(output),
            'is_error': bool(event.get('is_error')),
            'probe': self._probe.id if self._probe else '',
        }
        self.tool_calls.append(entry)
        name = entry['name']
        if entry['category'] == 'edit' or name in ('file_edit', 'file_write'):
            arguments = event.get('arguments') or {}
            self.edits.append({
                'turn': entry['turn'],
                'round': entry['round'],
                'path': arguments.get('path', ''),
                'category': entry['category'],
                'result_tokens': entry['result_tokens'],
                'evidence_ids': evidence_ids,
                'content_hash': entry['content_hash'],
                'probe': entry['probe'],
            })

    def note_result(self, result) -> None:
        self.last_result = result
        self.statuses.append(result.status)

    def run_probes(self, engine: Engine, after_turn: int,
                   all_probes: bool = False) -> None:
        for probe in self.task.probes:
            if probe.id in self._ran_probes:
                continue
            if not all_probes and probe.at_turn != after_turn:
                continue
            self._probe = probe
            result = engine.chat(probe.question, origin='metric-probe',
                                 deny_tools=['*'])
            self._probe = None
            self._ran_probes.add(probe.id)
            answer = result.content or ''
            turns = engine.current_session.turns
            probe_turn = turns[-1].get('index', 0) if turns else 0
            self.probes.append({
                'id': probe.id,
                'after_turn': after_turn,
                'probe_turn': probe_turn,
                'question': probe.question,
                'answer': answer,
                'correct': probe_correct(answer, probe),
                'checkpoint': probe.checkpoint,
                'evidence_ids': match_evidence(answer, self.task.evidence),
            })

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
        total = round(total_cost, 6)
        temperature = (self.task.temperature
                       if self.task.temperature is not None
                       else float(engine.config.get('temperature', 0.0) or 0.0))
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
            },
            goal_evidence=list(self.task.goal_evidence),
            rounds=self.rounds,
            tool_calls=self.tool_calls,
            edits=self.edits,
            compactions=self.compactions,
            probes=self.probes,
            cost={**total_parts, 'total': total},
            artifacts={},
        )


def run_task(task: MetricTask, source: Config | None = None,
             condition: str = 'single',
             overrides: dict | None = None,
             provider=None) -> MetricRecord:
    source = source or Config()
    overrides = overrides or {}
    condition = condition if condition in ('single', 'multi') else 'single'
    config_data = _task_config(source, task, overrides)
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
        recorder = _Recorder(task, condition, rates, task_hash)
        engine.add_observer(recorder.observe)
        try:
            os.chdir(worktree)
            if condition == 'single':
                prompt = task.prompt or '\n\n'.join(task.turns)
                recorder.note_result(engine.chat(prompt, origin='metric'))
                recorder.run_probes(engine, after_turn=1, all_probes=True)
            else:
                for index, prompt in enumerate(task.turns or [task.prompt], 1):
                    recorder.note_result(engine.chat(prompt, origin='metric'))
                    recorder.run_probes(engine, after_turn=index)
                recorder.run_probes(engine, after_turn=0)
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
        f'{"ok":<4} {"comp":<5} {"peak":<9} {"cost":<10} {"status":<10}',
        '-' * 88,
    ]
    for record in records:
        peak = max((int(item.get('ctx_tokens') or 0)
                    for item in record.rounds), default=0)
        correct = sum(1 for item in record.probes if item.get('correct'))
        lines.append(
            f'{record.task_id[:24]:<24} {record.condition:<7} '
            f'{record.run_end.get("main_rounds", 0):<5} '
            f'{len(record.probes):<7} {correct:<4} '
            f'{len(record.compactions):<5} {peak:<9} '
            f'{record.cost.get("total", 0):<10} '
            f'{record.run_end.get("status", ""):<10}')
    lines.append('-' * 88)
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
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    out_dir = (Path(args.out) if getattr(args, 'out', None)
               else source.local_path.parent / 'metrics' / 'runs')
    for task in selected.values():
        for condition in conditions:
            record = run_task(task, source, condition, overrides)
            records.append(record)
            try:
                record.write(out_dir / f'{task.id}_{condition}_{stamp}.json')
            except OSError as e:
                print(f'Error writing metric record: {e}', file=sys.stderr)
    if getattr(args, 'output', 'table') == 'json':
        sys.stdout.write(json.dumps([record.to_dict() for record in records],
                                    indent=2) + '\n')
    else:
        sys.stdout.write(format_results(records) + '\n')
    return 0
