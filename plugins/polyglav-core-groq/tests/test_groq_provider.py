import importlib.util
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_plugin():
    name = 'polyglav_groq_provider_plugin'
    spec = importlib.util.spec_from_file_location(name, str(SRC / 'plugin.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


GroqProvider = _load_plugin().GroqProvider


class TestGroqProvider(unittest.TestCase):

    def test_defaults(self):
        p = GroqProvider()
        self.assertEqual(p.base_url, 'https://api.groq.com/openai/v1')
        self.assertEqual(p.model, 'llama-3.3-70b-versatile')
        self.assertEqual(p._endpoint(), 'https://api.groq.com/openai/v1/chat/completions')

    def test_host_patterns(self):
        self.assertIn('groq.com', GroqProvider.HOST_PATTERNS)


if __name__ == '__main__':
    unittest.main()