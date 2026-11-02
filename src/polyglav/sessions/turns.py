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
                ended_at: str | None = None,
                usage: dict | None = None,
                context_tokens: int | None = None,
                finish_reason: str = '') -> dict:
    turn['status'] = status
    turn['ended_at'] = ended_at or _now()
    if usage is not None:
        turn['usage'] = usage
    if context_tokens is not None:
        turn['context_tokens'] = context_tokens
    if finish_reason:
        turn['finish_reason'] = finish_reason
    return turn


def add_part(turn: dict, part: dict) -> dict:
    turn.setdefault('parts', []).append(part)
    return part


def command_only(turn: dict) -> bool:
    parts = turn.get('parts') or []
    return bool(parts) and all(p.get('type') == 'command' for p in parts)


def _part(kind: str, timestamp: str | None = None, **fields) -> dict:
    return {'type': kind, 'timestamp': timestamp or _now(), **fields}


def user_part(text: str, timestamp: str | None = None,
              origin: str = '') -> dict:
    part = _part('user', text=text, timestamp=timestamp)
    if origin and origin != 'user':
        part['origin'] = origin
    return part


def text_part(text: str, timestamp: str | None = None) -> dict:
    return _part('text', text=text, timestamp=timestamp)


def thinking_part(text: str, timestamp: str | None = None) -> dict:
    return _part('thinking', text=text, timestamp=timestamp)


def system_part(text: str, timestamp: str | None = None) -> dict:
    return _part('system', text=text, timestamp=timestamp)


def command_part(command: str, summary: str = '', compact_from=None,
                 timestamp: str | None = None,
                 compact_from_part=None) -> dict:
    part = _part('command', text=command, summary=summary,
                 compact_from=compact_from, timestamp=timestamp)
    if compact_from_part is not None:
        part['compact_from_part'] = compact_from_part
    return part


def tool_part(name: str, input=None, output: str = '', is_error: bool = False,
              analysis: str | None = None, timestamp: str | None = None,
              call_id: str = '', refs: list | None = None) -> dict:
    part = _part('tool', name=name, input=input, output=output,
                 is_error=is_error, analysis=analysis, timestamp=timestamp)
    if call_id:
        part['call_id'] = call_id
    if refs:
        part['refs'] = list(refs)
    return part


def finish_tool(part: dict, output: str, is_error: bool = False,
                analysis: str | None = None,
                duration: float | None = None) -> dict:
    part['output'] = output
    part['is_error'] = is_error
    if analysis is not None:
        part['analysis'] = analysis
    if duration is not None:
        part['duration'] = duration
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


def turn_to_provider(turn: dict, start_part: int = 0,
                     keep_prelude: bool = False) -> list[dict]:
    out: list[dict] = []
    parts = turn.get('parts') or []
    index = turn.get('index', 0)
    pending_text: str | None = None
    pending_thinking: str | None = None
    i = 0
    if start_part > 0 and keep_prelude:
        while i < start_part:
            part = parts[i]
            kind = part.get('type')
            if kind == 'user':
                out.append({'role': 'user', 'content': part.get('text') or ''})
            elif kind == 'system':
                out.append({'role': 'system', 'content': part.get('text') or ''})
            i += 1
    else:
        i = max(0, start_part)
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
                call_id = tp.get('call_id') or f'call_{index}_{i}'
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
            message = {'role': 'assistant', 'content': pending_text or '',
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
        message = {'role': 'assistant', 'content': pending_text or ''}
        if pending_thinking:
            message['thinking'] = pending_thinking
        out.append(message)
    return out


def round_starts(turn: dict) -> list[int]:
    parts = turn.get('parts') or []
    starts: list[int] = []
    i = 0
    while i < len(parts):
        kind = parts[i].get('type')
        if kind == 'tool':
            starts.append(i)
            i += 1
            while i < len(parts) and parts[i].get('type') == 'tool':
                if parts[i].get('usage') is not None:
                    break
                i += 1
        elif kind == 'text':
            starts.append(i)
            while i < len(parts) and parts[i].get('type') == 'text':
                i += 1
        else:
            i += 1
    return starts


def compaction(turns) -> tuple[str, int, int]:
    summary = ''
    boundary_turn = 0
    boundary_part = 0
    for turn in turns:
        for part in turn.get('parts') or []:
            if part.get('type') != 'command' or not part.get('summary'):
                continue
            if part.get('compact_from') is None:
                continue
            value = part.get('compact_from')
            if not isinstance(value, int):
                continue
            value_part = part.get('compact_from_part')
            if not isinstance(value_part, int) or value_part < 0:
                value_part = 0
            if (value, value_part) >= (boundary_turn, boundary_part):
                summary = part['summary']
                boundary_turn = value
                boundary_part = value_part
    return summary, boundary_turn, boundary_part


def provider_messages(turns) -> list[dict]:
    summary, boundary_turn, boundary_part = compaction(turns)
    out: list[dict] = []
    if summary:
        out.append({
            'role': 'system',
            'content': 'Summary of earlier conversation:\n\n' + summary,
        })
    for turn in turns:
        index = turn.get('index', 0)
        if boundary_turn and index < boundary_turn:
            continue
        if boundary_turn and index == boundary_turn:
            out.extend(turn_to_provider(turn, start_part=boundary_part,
                                        keep_prelude=True))
        else:
            out.extend(turn_to_provider(turn))
    return out


def provider_messages_between(turns, start_turn: int = 0,
                              start_part: int = 0,
                              end_turn: int = 0,
                              end_part: int = 0) -> list[dict]:
    out: list[dict] = []
    for turn in turns:
        index = turn.get('index', 0)
        if start_turn and index < start_turn:
            continue
        if end_turn and index > end_turn:
            break
        parts = turn.get('parts') or []
        lo = start_part if index == start_turn else 0
        hi = end_part if index == end_turn else len(parts)
        if index == start_turn and start_part > 0:
            prelude = [p for p in parts[:start_part]
                       if p.get('type') in ('user', 'system')]
            if prelude:
                truncated = dict(turn)
                truncated['parts'] = prelude
                out.extend(turn_to_provider(truncated))
        if hi <= lo:
            continue
        truncated = dict(turn)
        truncated['parts'] = parts[lo:hi]
        out.extend(turn_to_provider(truncated))
    return out
