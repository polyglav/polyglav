from __future__ import annotations

import json
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def new_turn(index: int, model: str = '', provider: str = '',
             mode: str = '', reasoning=None) -> dict:
    return {
        'index': index,
        'started_at': _now(),
        'ended_at': '',
        'status': 'running',
        'model': model,
        'provider': provider,
        'mode': mode,
        'reasoning': reasoning,
        'parts': [],
    }


def finish_turn(turn: dict, status: str = 'ok',
                ended_at: str | None = None) -> dict:
    turn['status'] = status
    turn['ended_at'] = ended_at or _now()
    return turn


def add_part(turn: dict, part: dict) -> dict:
    turn.setdefault('parts', []).append(part)
    return part


def command_only(turn: dict) -> bool:
    parts = turn.get('parts') or []
    return bool(parts) and all(p.get('type') == 'command' for p in parts)


def _part(kind: str, timestamp: str | None = None, **fields) -> dict:
    return {'type': kind, 'timestamp': timestamp or _now(), **fields}


def user_part(text: str, timestamp: str | None = None) -> dict:
    return _part('user', text=text, timestamp=timestamp)


def text_part(text: str, timestamp: str | None = None) -> dict:
    return _part('text', text=text, timestamp=timestamp)


def thinking_part(text: str, timestamp: str | None = None) -> dict:
    return _part('thinking', text=text, timestamp=timestamp)


def system_part(text: str, timestamp: str | None = None) -> dict:
    return _part('system', text=text, timestamp=timestamp)


def command_part(command: str, summary: str = '', compact_from=None,
                 timestamp: str | None = None) -> dict:
    return _part('command', text=command, summary=summary,
                 compact_from=compact_from, timestamp=timestamp)


def tool_part(name: str, input=None, output: str = '', is_error: bool = False,
              analysis: str | None = None, timestamp: str | None = None) -> dict:
    return _part('tool', name=name, input=input, output=output,
                 is_error=is_error, analysis=analysis, timestamp=timestamp)


def finish_tool(part: dict, output: str, is_error: bool = False,
                analysis: str | None = None) -> dict:
    part['output'] = output
    part['is_error'] = is_error
    if analysis is not None:
        part['analysis'] = analysis
    return part


def _join(a: str | None, b: str | None) -> str:
    a = a or ''
    b = b or ''
    if a and b:
        return a + '\n\n' + b
    return a or b


def _arguments(value) -> str:
    if value is None:
        return '{}'
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return '{}'


def turn_to_provider(turn: dict) -> list[dict]:
    out: list[dict] = []
    parts = turn.get('parts') or []
    index = turn.get('index', 0)
    pending_text: str | None = None
    pending_thinking: str | None = None
    i = 0
    while i < len(parts):
        part = parts[i]
        kind = part.get('type')
        if kind == 'user':
            out.append({'role': 'user', 'content': part.get('text') or ''})
            i += 1
        elif kind == 'system':
            out.append({'role': 'system', 'content': part.get('text') or ''})
            i += 1
        elif kind == 'thinking':
            pending_thinking = _join(pending_thinking, part.get('text'))
            i += 1
        elif kind == 'text':
            pending_text = _join(pending_text, part.get('text'))
            i += 1
        elif kind == 'tool':
            calls: list[dict] = []
            results: list[dict] = []
            while i < len(parts) and parts[i].get('type') == 'tool':
                tp = parts[i]
                call_id = f'call_{index}_{i}'
                calls.append({
                    'id': call_id,
                    'type': 'function',
                    'function': {'name': tp.get('name', ''),
                                 'arguments': _arguments(tp.get('input'))},
                })
                results.append({
                    'role': 'tool',
                    'tool_call_id': call_id,
                    'content': tp.get('output') or '',
                })
                i += 1
            message = {'role': 'assistant', 'content': pending_text,
                       'tool_calls': calls}
            if pending_thinking:
                message['thinking'] = pending_thinking
            out.append(message)
            out.extend(results)
            pending_text = None
            pending_thinking = None
        else:
            i += 1
    if pending_text is not None or pending_thinking:
        message = {'role': 'assistant', 'content': pending_text}
        if pending_thinking:
            message['thinking'] = pending_thinking
        out.append(message)
    return out


def compaction(turns) -> tuple[str, int]:
    summary = ''
    boundary = 0
    for turn in turns:
        for part in turn.get('parts') or []:
            if part.get('type') != 'command' or not part.get('summary'):
                continue
            summary = part['summary']
            value = part.get('compact_from')
            if isinstance(value, int) and value > boundary:
                boundary = value
    return summary, boundary


def provider_messages(turns) -> list[dict]:
    summary, boundary = compaction(turns)
    out: list[dict] = []
    if summary:
        out.append({
            'role': 'system',
            'content': 'Summary of earlier conversation:\n\n' + summary,
        })
    for turn in turns:
        if boundary and turn.get('index', 0) < boundary:
            continue
        out.extend(turn_to_provider(turn))
    return out
