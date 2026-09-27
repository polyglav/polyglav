import importlib.util
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polyglav.tools.registry import ToolRegistry


def _load_plugin(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ws_plugin = _load_plugin('polyglav_ws_plugin', SRC / 'plugin.py')
import display
import search as ddg


class _Resp:
    def __init__(self, content: str):
        self._content = content

    def read(self):
        return self._content.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


LITE_HTML = (
    '<table><tr><td>'
    '<a rel="nofollow" href="http://e.com/1">Example title</a>'
    '<br>Example snippet<br>'
    '</td></tr>'
    '<tr><td>'
    '<a rel="nofollow" href="http://e.com/2">Second</a>'
    '<br>Another snippet<br>'
    '</td></tr></table>'
)


class TestDdgParser(unittest.TestCase):

    def test_parses_lite_results(self):
        parser = ddg.DDGResultParser()
        parser.feed(LITE_HTML)
        self.assertEqual(parser.results, [
            {'url': 'http://e.com/1', 'title': 'Example title', 'snippet': 'Example snippet'},
            {'url': 'http://e.com/2', 'title': 'Second', 'snippet': 'Another snippet'},
        ])

    def test_search_slices_to_num_results(self):
        with patch('urllib.request.urlopen', return_value=_Resp(LITE_HTML)):
            results = ddg.search('example', num_results=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'Example title')

    def test_search_network_error_returns_empty(self):
        def _raise(*a, **kw):
            raise OSError('boom')
        with patch('urllib.request.urlopen', _raise):
            self.assertEqual(ddg.search('example'), [])


class TestDisplay(unittest.TestCase):

    def test_format_results(self):
        out = display.format_results('q', [
            {'title': 'T', 'url': 'http://x', 'snippet': 'S'}])
        self.assertIn('1. T', out)
        self.assertIn('http://x', out)
        self.assertIn('(S)', out)

    def test_format_results_skips_missing_fields(self):
        out = display.format_results('q', [{}, {'title': 'T', 'url': 'http://x'}])
        self.assertNotIn('None', out)
        self.assertIn('2. T', out)

    def test_format_context(self):
        out = display.format_context('q', [
            {'title': 'T', 'url': 'http://x', 'snippet': 'S'}])
        self.assertIn('1. T', out)
        self.assertIn('URL: http://x', out)
        self.assertIn('Snippet: S', out)


class TestTextExtractor(unittest.TestCase):

    def test_strips_script_and_style(self):
        raw = ('<html><head><style>.x{}</style>'
               '<script>var a=1;</script></head><body>'
               '<p>Hello</p><p>World</p></body></html>')
        extractor = ws_plugin._TextExtractor()
        extractor.feed(raw)
        self.assertEqual(extractor.text(), 'Hello\n\nWorld')

    def test_collapses_whitespace(self):
        extractor = ws_plugin._TextExtractor()
        extractor.feed('<div>   a   <br>b   </div>')
        self.assertEqual(extractor.text(), 'a\nb')


class TestFetchText(unittest.TestCase):

    def test_extracts_and_paginates(self):
        body = ''.join(f'<p>para{i:04d} text</p>' for i in range(700))
        content = f'<html><body>{body}</body></html>'
        with patch('urllib.request.urlopen', return_value=_Resp(content)):
            result = ws_plugin._fetch_text('http://x.dev/p')
        self.assertIn('[offset', result)
        self.assertGreater(len(result), ws_plugin.MAX_FETCH_CHARS)

    def test_fetch_error(self):
        def _raise(*a, **kw):
            raise OSError('nope')
        with patch('urllib.request.urlopen', _raise):
            self.assertIn('Error fetching page', ws_plugin._fetch_text('http://x.dev/p'))

    def test_empty_content(self):
        with patch('urllib.request.urlopen', return_value=_Resp('<html></html>')):
            self.assertEqual(ws_plugin._fetch_text('http://x.dev/p'), '(empty content)')

    def test_offset_beyond_end(self):
        def _raise(*a, **kw):
            return _Resp('<html><body>short</body></html>')
        with patch('urllib.request.urlopen', _raise):
            self.assertEqual(ws_plugin._fetch_text('http://x.dev/p', offset=100),
                             '(end of content)')


class TestOpenTarget(unittest.TestCase):

    def setUp(self):
        ws_plugin.SERVICE.last_results = [
            {'url': 'http://x.dev/1', 'title': 'T1', 'snippet': 'S1'},
        ]

    def test_url_passthrough(self):
        self.assertEqual(ws_plugin._open_target(url='http://direct'),
                         ('http://direct', None))

    def test_id_resolves_last_results(self):
        self.assertEqual(ws_plugin._open_target(id=1), ('http://x.dev/1', None))

    def test_missing_id_and_url(self):
        target, err = ws_plugin._open_target()
        self.assertIsNone(target)
        self.assertIn('url" or "id"', err)

    def test_out_of_range_id(self):
        target, err = ws_plugin._open_target(id=5)
        self.assertIn('out of range', err)

    def test_non_integer_id(self):
        target, err = ws_plugin._open_target(id='x')
        self.assertIn('must be an integer', err)

    def test_url_string_id_is_treated_as_url(self):
        target, err = ws_plugin._open_target(id='https://direct.example/p')
        self.assertEqual((target, err), ('https://direct.example/p', None))

    def test_no_previous_results(self):
        ws_plugin.SERVICE.last_results = []
        target, err = ws_plugin._open_target(id=1)
        self.assertIn('no previous web_search', err)


class TestRegistration(unittest.TestCase):

    def setUp(self):
        self.registry = ToolRegistry()
        ws_plugin.register_tools(self.registry)

    def test_tools_and_metadata(self):
        self.assertTrue(self.registry.refine_required('web_search'))
        self.assertEqual(self.registry.permission_for('web_search'), 'web')
        self.assertEqual(self.registry.key_arg_for('web_search'), 'query')
        self.assertEqual(self.registry.permission_for('web_fetch'), 'read')
        self.assertEqual(self.registry.permission_for('open'), 'read')
        self.assertEqual(self.registry.permission_for('fetch_page'), 'read')
        self.assertEqual(self.registry.path_arg_for('web_fetch'), None)
        self.assertEqual(self.registry.key_arg_for('web_fetch'), 'url')
        self.assertTrue(self.registry.is_note_result('web_fetch', '(end of content)'))
        self.assertTrue(self.registry.is_note_result('open', '(empty content)'))
        self.assertTrue(self.registry.is_note_result('web_search', 'No search results found.'))
        self.assertFalse(self.registry.is_note_result('web_search', 'Some results found.'))

    def test_web_fetch_canonical_with_aliases(self):
        self.assertTrue(self.registry.is_registered('web_fetch'))
        self.assertTrue(self.registry.is_registered('open'))
        self.assertTrue(self.registry.is_registered('fetch_page'))
        names = [s['function']['name'] for s in self.registry.schema_filtered(
            {'web_fetch', 'open', 'fetch_page'})]
        self.assertEqual(names, ['web_fetch'])

    def test_web_fetch_resolves_url_and_id(self):
        ws_plugin.SERVICE.last_results = [{'url': 'http://x.dev/1', 'title': 'T1'}]
        with patch('urllib.request.urlopen', return_value=_Resp('<p>page</p>')):
            self.assertEqual(self.registry.execute('web_fetch', {'id': 1}), 'page')
        with patch('urllib.request.urlopen', return_value=_Resp('<p>page</p>')):
            self.assertEqual(self.registry.execute('web_fetch', {'url': 'http://x.dev/2'}), 'page')

    def test_web_search_records_last_results(self):
        with patch('search.search', return_value=[
            {'url': 'http://x.dev/1', 'title': 'T1', 'snippet': 'S1'}]):
            out = self.registry.execute('web_search', {'query': 'hi'})
        self.assertIn('T1', out)
        self.assertEqual(ws_plugin.SERVICE.last_results[0]['url'], 'http://x.dev/1')

    def test_search_alias_resolves_to_web_search(self):
        self.assertTrue(self.registry.is_registered('search'))
        with patch('search.search', return_value=[
            {'url': 'http://x.dev/1', 'title': 'T1', 'snippet': 'S1'}]):
            out = self.registry.execute('search', {'q': 'hi'})
        self.assertIn('T1', out)

    def test_open_by_id(self):
        ws_plugin.SERVICE.last_results = [{'url': 'http://x.dev/1', 'title': 'T1'}]
        with patch('urllib.request.urlopen', return_value=_Resp('<p>page</p>')):
            out = self.registry.execute('open', {'id': 1})
        self.assertEqual(out, 'page')


if __name__ == '__main__':
    unittest.main()