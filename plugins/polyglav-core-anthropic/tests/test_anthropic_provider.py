import importlib.util
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_plugin():
    name = 'polyglav_anthropic_provider_plugin'
    spec = importlib.util.spec_from_file_location(name, str(SRC / 'plugin.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


AnthropicProvider = _load_plugin().AnthropicProvider


class TestAnthropicProvider(unittest.TestCase):

    def test_defaults(self):
        p = AnthropicProvider()
        self.assertEqual(p.base_url, 'https://api.anthropic.com/v1')
        self.assertEqual(p.model, 'claude-sonnet-4-20250514')
        self.assertEqual(p._endpoint(), 'https://api.anthropic.com/v1/chat/completions')

    def test_host_patterns(self):
        self.assertIn('anthropic.com', AnthropicProvider.HOST_PATTERNS)

    def test_reasoning_off(self):
        p = AnthropicProvider(reasoning=False)
        payload = p._payload([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(payload['thinking'], {'type': 'disabled'})

    def test_reasoning_auto_maps_to_medium(self):
        p = AnthropicProvider(reasoning='auto')
        payload = p._payload([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(payload['thinking'],
                         {'type': 'enabled', 'budget_tokens': 2048})

    def test_reasoning_high_budget(self):
        p = AnthropicProvider(reasoning='high')
        payload = p._payload([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(payload['thinking'],
                         {'type': 'enabled', 'budget_tokens': 4096})


if __name__ == '__main__':
    unittest.main()