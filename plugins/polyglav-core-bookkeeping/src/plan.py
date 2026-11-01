from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

PLAN_DIR = '.polyglav/plans'
MAX_PLAN_CHARS = 8000
REQUIRED_SECTIONS = (
    'Goal',
    'Instructions and constraints',
    'Findings',
    'Decisions',
    'Steps',
    'Role and team split',
    'Verification',
    'Open questions',
    'Next',
)

_FRONTMATTER = re.compile(r'^---\n(.*?)\n---\n?', re.S)
_STEP_LINE = re.compile(r'^\s*\d+\.\s', re.M)
_REVISION = re.compile(r'^## Revision \d+', re.M)


def plans_dir(config) -> Path:
    root = config.local_path.parent.parent
    raw = str(config.get('plan.dir') or PLAN_DIR).strip() or PLAN_DIR
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe(value: str) -> str:
    text = re.sub(r'[^A-Za-z0-9_.-]+', '-', str(value or '').strip())
    return text.strip('.-') or 'session'


def _rel(config, path: Path) -> str:
    root = config.local_path.parent.parent
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _session_id(session) -> str:
    return _safe(getattr(session, 'session_id', '')
                 or getattr(session, 'session_name', '') or 'session')


def plan_path(config, session, create: bool = True) -> Path | None:
    current = str(getattr(session, 'plan', '') or '').strip()
    if current:
        path = Path(current).expanduser()
        if not path.is_absolute():
            path = config.local_path.parent.parent / path
        return path
    if not create:
        return None
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return plans_dir(config) / f'plan_{ts}_{_session_id(session)}.md'


def _missing_sections(content: str) -> list[str]:
    text = content.lower()
    return [name for name in REQUIRED_SECTIONS
            if f'## {name.lower()}' not in text]


def _frontmatter(session, path: Path, mode: str, next_mode: str,
                 next_role: str, team: str, status: str) -> str:
    created = datetime.now(timezone.utc).isoformat(timespec='seconds')
    return (
        '---\n'
        f'plan: {path.stem}\n'
        f'session: {session.session_name}\n'
        f'todo: .polyglav/todos/{session.session_name}.json\n'
        f'created: {created}\n'
        f'mode: {mode}\n'
        f'status: {status}\n'
        f'next_mode: {next_mode}\n'
        f'next_role: {next_role}\n'
        f'team: {team}\n'
        '---\n'
    )


def parse_plan(text: str) -> tuple[dict, str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta: dict = {}
    for line in match.group(1).splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        meta[key.strip()] = value.strip()
    return meta, text[match.end():]


def list_plans(config) -> list[Path]:
    return sorted(plans_dir(config).glob('plan_*.md'))


def resolve_plan(config, ident: str) -> Path | None:
    text = str(ident or '').strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = config.local_path.parent.parent / path
    if path.is_file():
        return path.resolve()
    for candidate in list_plans(config):
        if candidate.stem == text or candidate.stem.endswith(f'_{text}'):
            return candidate
    return None


def display_path(config, path: Path) -> str:
    return _rel(config, path)


def plan_context(config, session, max_chars: int = MAX_PLAN_CHARS) -> str:
    path = plan_path(config, session, create=False)
    if path is None:
        return ''
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    meta, body = parse_plan(text)
    body = body.strip()
    if max_chars and len(body) > max_chars:
        body = body[:max_chars].rsplit('\n', 1)[0] + '\n... (truncated)'
    mode = meta.get('mode') or 'read'
    next_mode = meta.get('next_mode') or ''
    next_role = meta.get('next_role') or ''
    status = meta.get('status') or 'draft'
    header = f'Internal plan: {_rel(config, path)}\n'
    header += f'Mode: {mode}. Next: {next_mode} {next_role}. Status: {status}.\n'
    header += ('Follow the plan. Re-read the file if the context was compacted. '
               'Update it with plan_write when it changes. Do not read the plan '
               'aloud unless asked.\n\n')
    return header + body


def write_plan(engine, content: str, next_mode: str = 'write',
               next_role: str = '', team: str = '', status: str = 'draft',
               append: bool = False, replace: bool = False) -> str:
    session = engine.current_session
    text = str(content or '').strip()
    if not text:
        return 'Error: plan content is empty'
    path = plan_path(engine.config, session)
    exists = path.exists()
    with_revision = (append or exists) and not replace
    if with_revision and exists:
        try:
            prior = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            prior = ''
        revision = len(_REVISION.findall(prior)) + 1
        block = f'\n\n## Revision {revision}\n\n{text}\n'
        path.write_text(prior.rstrip() + block, encoding='utf-8')
        session.plan = _rel(engine.config, path)
        engine.session_auto_save()
        return f'Plan updated: {_rel(engine.config, path)}'
    missing = _missing_sections(text)
    if missing:
        return ('Error: plan is missing required sections: '
                + ', '.join(missing))
    header = _frontmatter(session, path, engine._mode(), next_mode,
                          next_role, team, status)
    path.write_text(header + '\n' + text + '\n', encoding='utf-8')
    session.plan = _rel(engine.config, path)
    engine.session_auto_save()
    verb = 'updated' if exists else 'saved'
    steps = len(_STEP_LINE.findall(text))
    return f'Plan {verb}: {_rel(engine.config, path)} ({steps} steps)'


def register_plan_tool(registry, engine) -> Callable:
    @registry.register(
        name='plan_write',
        description=(
            'Write or revise the durable internal plan under the configured '
            'plan directory. Use it when the task is large or long-running, '
            'or when the user asks for a plan. It is not needed for a one-step '
            'answer. The plan survives compaction and role switches.'
        ),
        parameters={
            'type': 'object',
            'properties': {
                'content': {
                    'type': 'string',
                    'description': 'The plan body. It must contain the sections '
                                   'Goal, Instructions and constraints, Findings, '
                                   'Decisions, Steps, Role and team split, '
                                   'Verification, Open questions, and Next.',
                },
                'next_mode': {
                    'type': 'string',
                    'enum': ['read', 'write'],
                    'description': 'Mode to use after the plan. Default write.',
                },
                'next_role': {
                    'type': 'string',
                    'description': 'Role or team to start after the plan.',
                },
                'team': {
                    'type': 'string',
                    'description': 'Team to run after the plan, when any.',
                },
                'status': {
                    'type': 'string',
                    'enum': ['draft', 'approved', 'in_progress', 'done'],
                    'description': 'Plan status. Default draft.',
                },
                'append': {
                    'type': 'boolean',
                    'description': 'Append a revision block to the active plan.',
                },
                'replace': {
                    'type': 'boolean',
                    'description': 'Rewrite the active plan instead of appending.',
                },
            },
            'required': ['content'],
        },
        category='read',
        permission='read',
        short='Write the plan',
        glyph='#',
        verb='Plan',
        note=lambda result: result.startswith(('Plan saved', 'Plan updated')),
    )
    def plan_write(content: str, next_mode: str = 'write',
                   next_role: str = '', team: str = '', status: str = 'draft',
                   append: bool = False, replace: bool = False) -> str:
        return write_plan(engine, content, next_mode=next_mode,
                          next_role=next_role, team=team, status=status,
                          append=append, replace=replace)
    return plan_write
