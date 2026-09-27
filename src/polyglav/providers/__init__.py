from .base import OpenAICompatibleProvider

PROVIDERS = {
    'openai-compatible': OpenAICompatibleProvider,
}


def detect_provider(base_url: str = '', providers: dict | None = None) -> str:
    if providers is None:
        providers = dict(PROVIDERS)
    url = (base_url or '').lower().rstrip('/')
    best: str | None = None
    best_len = -1
    for name, factory in sorted(providers.items()):
        for pattern in getattr(factory, 'HOST_PATTERNS', ()) or ():
            pattern = str(pattern).lower()
            if pattern and pattern in url and len(pattern) > best_len:
                best = name
                best_len = len(pattern)
    return best or 'openai-compatible'


def merged_providers(config=None) -> dict:
    from ..config import Config
    from ..plugins.manager import PluginManager
    cfg = config if config is not None else Config()
    pm = PluginManager(cfg)
    pm.load()
    merged = dict(PROVIDERS)
    merged.update(pm.provider_classes())
    return merged


__all__ = ['PROVIDERS', 'detect_provider', 'merged_providers',
           'OpenAICompatibleProvider']