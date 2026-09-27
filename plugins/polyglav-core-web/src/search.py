import urllib.request
import urllib.parse
from html.parser import HTMLParser
from typing import Generator


SEARCH_URL = 'https://lite.duckduckgo.com/lite/'


class DDGResultParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results: list[dict] = []
        self._cur: dict | None = None
        self._state = 'idle'
        self._text = ''

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a' and a.get('rel') == 'nofollow':
            self._cur = {'url': a.get('href', ''), 'title': '', 'snippet': ''}
            self._state = 'link'
            self._text = ''
            return
        if self._state == 'idle':
            return
        if tag == 'br':
            if self._state in ('link', 'link_done'):
                if self._state == 'link':
                    self._cur['title'] = self._text.strip()
                self._state = 'snippet'
                self._text = ''
            elif self._state == 'snippet':
                self._cur['snippet'] = self._text.strip()
                self._state = 'done'
                self._text = ''

    def handle_data(self, data):
        if self._state in ('link', 'snippet'):
            self._text += data

    def handle_endtag(self, tag):
        if tag == 'a' and self._state == 'link':
            self._cur['title'] = self._text.strip()
            self._state = 'link_done'
            self._text = ''
        if tag == 'td' and self._cur:
            if self._cur.get('title'):
                self.results.append(self._cur)
            self._cur = None
            self._state = 'idle'
            self._text = ''


def search(query: str, num_results: int = 5) -> list[dict]:
    data = urllib.parse.urlencode({'q': query}).encode()
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'}
    req = urllib.request.Request(SEARCH_URL, data=data, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='replace')
    except Exception:
        return []

    parser = DDGResultParser()
    parser.feed(html)
    return parser.results[:num_results]
