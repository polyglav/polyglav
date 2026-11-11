from __future__ import annotations

DEFAULT_RATES = {'input': 0.0, 'output': 0.0, 'cache_read': 0.0}
PER_MILLION = 1_000_000


def normalise_rates(rates: dict | None) -> dict:
    out = dict(DEFAULT_RATES)
    if isinstance(rates, dict):
        for key in out:
            value = rates.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[key] = float(value)
    return out


def cached_tokens(usage: dict | None) -> int:
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get('prompt_tokens_details')
    if isinstance(details, dict) and isinstance(details.get('cached_tokens'), int):
        return details['cached_tokens']
    if isinstance(usage.get('cached_tokens'), int):
        return usage['cached_tokens']
    if isinstance(usage.get('prompt_cache_hit_tokens'), int):
        return usage['prompt_cache_hit_tokens']
    return 0


def cache_reported(usage: dict | None) -> bool:
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get('prompt_tokens_details')
    if isinstance(details, dict) and isinstance(details.get('cached_tokens'), int):
        return True
    if isinstance(usage.get('cached_tokens'), int):
        return True
    return isinstance(usage.get('prompt_cache_hit_tokens'), int)


def token_parts(usage: dict | None) -> dict:
    usage = usage if isinstance(usage, dict) else {}
    return {
        'input': int(usage.get('prompt_tokens') or 0),
        'output': int(usage.get('completion_tokens') or 0),
        'cache_read': cached_tokens(usage),
    }


def estimate_cost(usage: dict | None, rates: dict | None = None) -> float:
    r = normalise_rates(rates)
    parts = token_parts(usage)
    cached = min(parts['cache_read'], parts['input'])
    uncached = parts['input'] - cached
    cached_rate = r['cache_read'] if r['cache_read'] > 0 else r['input']
    total = (uncached * r['input']
             + cached * cached_rate
             + parts['output'] * r['output'])
    return round(total / PER_MILLION, 6)


def rates_from_config(config, provider: str = '', model: str = '') -> dict:
    table = config.get('cost.rates') if config is not None else None
    if not isinstance(table, dict):
        return dict(DEFAULT_RATES)
    for key in (f'{provider}/{model}', provider, 'default'):
        if not key:
            continue
        entry = table.get(key)
        if isinstance(entry, dict):
            return normalise_rates(entry)
    return dict(DEFAULT_RATES)
