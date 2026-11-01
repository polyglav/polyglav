class CatalogRegistry:
    def __init__(self):
        self._adapters: dict[str, object] = {}

    def register(self, kind: str, adapter) -> None:
        key = str(kind or '').strip().lower()
        if not key:
            raise ValueError('catalog kind is required')
        self._adapters[key] = adapter

    def get(self, kind: str):
        return self._adapters.get(str(kind or '').strip().lower())

    def kinds(self) -> list[str]:
        return sorted(self._adapters)
