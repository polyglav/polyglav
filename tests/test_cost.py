import unittest

from polyglav.cost import (DEFAULT_RATES, cache_reported, cached_tokens,
                           estimate_cost, normalise_rates, rates_from_config,
                           token_parts)


class _Config:

    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        return self.data.get(key, default)


class TestCost(unittest.TestCase):

    def test_normalise_rates(self):
        self.assertEqual(normalise_rates(None), DEFAULT_RATES)
        self.assertEqual(normalise_rates({'input': 1}),
                         {'input': 1.0, 'output': 0.0, 'cache_read': 0.0})

    def test_token_parts(self):
        usage = {'prompt_tokens': 100, 'completion_tokens': 10,
                 'prompt_tokens_details': {'cached_tokens': 40}}
        self.assertEqual(token_parts(usage),
                         {'input': 100, 'output': 10, 'cache_read': 40})

    def test_cached_tokens_fallbacks(self):
        self.assertEqual(cached_tokens(
            {'prompt_tokens_details': {'cached_tokens': 4}}), 4)
        self.assertEqual(cached_tokens({'cached_tokens': 7}), 7)
        self.assertEqual(cached_tokens({'prompt_cache_hit_tokens': 9}), 9)
        self.assertEqual(cached_tokens(None), 0)

    def test_cache_reported(self):
        self.assertTrue(cache_reported(
            {'prompt_tokens_details': {'cached_tokens': 0}}))
        self.assertTrue(cache_reported({'cached_tokens': 0}))
        self.assertTrue(cache_reported({'prompt_cache_hit_tokens': 0}))
        self.assertFalse(cache_reported({'prompt_tokens': 10}))
        self.assertFalse(cache_reported(None))

    def test_estimate_cost(self):
        usage = {'prompt_tokens': 100, 'completion_tokens': 10,
                 'prompt_tokens_details': {'cached_tokens': 40}}
        rates = {'input': 1.0, 'output': 2.0, 'cache_read': 0.5}
        self.assertAlmostEqual(estimate_cost(usage, rates), 0.0001)

    def test_rates_from_config_precedence(self):
        config = _Config({'cost.rates': {
            'default': {'input': 1},
            'ollama': {'input': 2},
            'ollama/m': {'input': 3},
        }})
        self.assertEqual(rates_from_config(config, 'ollama', 'm')['input'], 3.0)
        self.assertEqual(rates_from_config(config, 'ollama', 'x')['input'], 2.0)
        self.assertEqual(rates_from_config(config, 'other', 'x')['input'], 1.0)

    def test_rates_from_config_empty(self):
        self.assertEqual(rates_from_config(_Config({}))['input'], 0.0)


if __name__ == '__main__':
    unittest.main()
