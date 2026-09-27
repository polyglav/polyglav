import re
from html.parser import HTMLParser

import search
import display

MAX_FETCH_CHARS = 8000


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip_depth = 0
        self._skip_tags = frozenset({'script', 'style', 'svg', 'noscript'})
        self._block_tags = frozenset({
            'p', 'br', 'li', 'div', 'tr', 'td', 'th',
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'blockquote', 'pre', 'hr',
        })

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip_depth += 1
        if self._skip_depth == 0 and tag in self._block_tags:
            self._parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip_depth = max(0, self._skip_depth - 1)
        if self._skip_depth == 0 and tag in self._block_tags:
            self._parts.append('\n')

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self):
        text = ''.join(self._parts)
        text = re.sub(r' +', ' ', text)
        text = re.sub(r'\n ', '\n', text)
        text = re.sub(r' \n', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()


class _SearchService:
    def __init__(self):
        self.last_results: list[dict] = []

    def search(self, query: str, num: int = 5) -> list[dict]:
        return search.search(query, num)

    def display(self, query: str, results: list[dict]) -> str:
        return display.format_results(query, results)

    def context(self, query: str, results: list[dict]) -> str:
        return display.format_context(query, results)


SERVICE = _SearchService()


def _fetch_text(url: str, offset: int = 0) -> str:
    import urllib.request
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode('utf-8', errors='replace')
        extractor = _TextExtractor()
        extractor.feed(content)
        text = extractor.text()
    except Exception as e:
        return f'Error fetching page: {e}'
    total = len(text)
    start = max(0, int(offset or 0))
    if start >= total:
        return '(end of content)' if total else '(empty content)'
    remaining = text[start:]
    if len(remaining) > MAX_FETCH_CHARS:
        next_offset = start + MAX_FETCH_CHARS
        return (remaining[:MAX_FETCH_CHARS]
                + f'\n[offset {next_offset} of {total} chars - continue with cursor={next_offset}]')
    return remaining


def _open_target(url: str | None = None, id=None) -> tuple[str, str | None]:
    if url:
        return url, None
    if id is None:
        return None, 'Error: open requires "url" or "id" (from the most recent web_search)'
    if isinstance(id, str) and id.lower().startswith(('http://', 'https://')):
        return id, None
    if not SERVICE.last_results:
        return None, 'Error: no previous web_search results to open'
    try:
        index = int(id)
    except (TypeError, ValueError):
        return None, f'Error: open id must be an integer, got {id}'
    if not (1 <= index <= len(SERVICE.last_results)):
        return None, (f'Error: open id {index} out of range, '
                      f'web_search returned {len(SERVICE.last_results)} results')
    return SERVICE.last_results[index - 1].get('url', ''), None


def _open_status(args: dict) -> str:
    url = args.get('url')
    if url:
        return url
    target, err = _open_target(id=args.get('id'))
    return target if not err else ''


def register_services(services):
    services['search'] = SERVICE


def register_tools(registry):
    @registry.register(
        name='web_search',
        description='Search the web for current information. Use this to find recent news, facts, documentation, and any information that may be time-sensitive or outside the model\'s training data.',
        parameters={
            'type': 'object',
            'properties': {
                'query': {
                    'type': 'string',
                    'description': 'The search query - be specific and concise',
                },
            },
            'required': ['query'],
        },
        refine=True,
        category='search',
        permission='web',
        key_arg='query',
        short='Search the web',
        aliases=['search', 'web'],
        param_aliases={'q': 'query'},
        note=lambda r: r == 'No search results found.',
    )
    def web_search(query: str) -> str:
        results = SERVICE.search(query)
        SERVICE.last_results = results
        if not results:
            return 'No search results found.'
        return SERVICE.context(query, results)

    @registry.register(
        name='web_fetch',
        description='Fetch and read the full content of a web page. Use this when search result snippets are insufficient and you need detailed information from a specific URL. Pass url directly, or id (the 1-based result number from the most recent web_search) to fetch that result. Pass offset to continue reading from a previous offset marker.',
        parameters={
            'type': 'object',
            'properties': {
                'url': {
                    'type': 'string',
                    'description': 'The full URL of the page to fetch',
                },
                'id': {
                    'type': 'integer',
                    'description': '1-based result number from the most recent web_search to open',
                },
                'offset': {
                    'type': 'integer',
                    'description': 'Character offset to resume reading from, as reported by the previous offset marker',
                },
            },
        },
        category='read',
        permission='read',
        key_arg='url',
        short='Open a web page or a web_search result',
        glyph='↓',
        verb='Fetch',
        status=_open_status,
        aliases=['open', 'fetch_page'],
        param_aliases={'cursor': 'offset'},
        note=lambda r: r in ('(end of content)', '(empty content)'),
    )
    def web_fetch(url: str | None = None, id=None, offset: int = 0) -> str:
        target, err = _open_target(url, id)
        if err:
            return err
        return _fetch_text(target, offset)
