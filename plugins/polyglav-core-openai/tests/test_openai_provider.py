import importlib.util
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_plugin():
    name = 'polyglav_openai_provider_plugin'
    spec = importlib.util.spec_from_file_location(name, str(SRC / 'plugin.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


OpenAIProvider = _load_plugin().OpenAIProvider


class TestOpenAIProvider(unittest.TestCase):

    def test_defaults(self):
        p = OpenAIProvider()
        self.assertEqual(p.base_url, 'https://api.openai.com/v1')
        self.assertEqual(p.model, 'gpt-4o-mini')
        self.assertEqual(p._endpoint(), 'https://api.openai.com/v1/chat/completions')

    def test_host_patterns(self):
        self.assertIn('openai.com', OpenAIProvider.HOST_PATTERNS)

    def test_no_auth_header_without_key(self):
        p = OpenAIProvider(api_key='')
        headers = p._headers()
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertNotIn('Authorization', headers)

    def test_bearer_auth_with_key(self):
        p = OpenAIProvider(api_key='sk-test')
        self.assertEqual(p._headers()['Authorization'], 'Bearer sk-test')

    def test_reasoning_off(self):
        p = OpenAIProvider(reasoning=False)
        payload = p._payload([{'role': 'user', 'content': 'hi'}])
        self.assertNotIn('reasoning_effort', payload)

    def test_reasoning_auto_maps_to_medium(self):
        p = OpenAIProvider(reasoning='auto')
        payload = p._payload([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(payload['reasoning_effort'], 'medium')

    def test_reasoning_effort_pass_through(self):
        p = OpenAIProvider(reasoning='high')
        payload = p._payload([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(payload['reasoning_effort'], 'high')


if __name__ == '__main__':
    unittest.main()