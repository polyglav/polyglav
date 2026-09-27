import json
import tempfile
import unittest
from pathlib import Path

from polyglav.models import ModelRegistry
from polyglav.config import Config


class TestModelRegistry(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _reg(self):
        return ModelRegistry(global_dir=self.base)

    def test_path_under_global_dir(self):
        self.assertEqual(self._reg().path,
                         self.base / '.config' / 'polyglav' / 'models.json')

    def test_put_and_find(self):
        reg = self._reg()
        reg.put('ollama', 'm1')
        entry = reg.find('ollama', 'm1')
        self.assertIsNotNone(entry)
        self.assertEqual(entry.provider, 'ollama')
        self.assertEqual(entry.model, 'm1')
        self.assertTrue(entry.added_at)
        self.assertTrue(entry.last_used)

    def test_put_dedupes_and_updates_last_used(self):
        reg = self._reg()
        reg.put('ollama', 'm')
        first = reg.find('ollama', 'm').last_used
        reg.put('ollama', 'm')
        self.assertEqual(len(reg.all()), 1)
        self.assertGreaterEqual(reg.find('ollama', 'm').last_used, first)

    def test_put_distinct_models_keep_separate_entries(self):
        reg = self._reg()
        reg.put('ollama', 'a')
        reg.put('ollama', 'b')
        reg.put('openai', 'g1')
        self.assertEqual(len(reg.all()), 3)

    def test_find_unknown_returns_none(self):
        self.assertIsNone(self._reg().find('ollama', 'nope'))

    def test_touch_updates_last_used(self):
        reg = self._reg()
        reg.put('ollama', 'm')
        before = reg.find('ollama', 'm').last_used
        reg.touch('ollama', 'm')
        self.assertGreaterEqual(reg.find('ollama', 'm').last_used, before)

    def test_touch_unknown_returns_none(self):
        self.assertIsNone(self._reg().touch('ollama', 'nope'))

    def test_remove(self):
        reg = self._reg()
        reg.put('ollama', 'm')
        self.assertTrue(reg.remove('ollama', 'm'))
        self.assertIsNone(reg.find('ollama', 'm'))
        self.assertFalse(reg.remove('ollama', 'm'))

    def test_grouped(self):
        reg = self._reg()
        reg.put('ollama', 'm1')
        reg.put('ollama', 'm2')
        reg.put('openai', 'g1')
        groups = dict(reg.grouped())
        self.assertEqual([e.model for e in groups['ollama']], ['m1', 'm2'])
        self.assertEqual([e.model for e in groups['openai']], ['g1'])

    def test_reload_from_disk(self):
        self._reg().put('ollama', 'm')
        reg2 = ModelRegistry(global_dir=self.base)
        self.assertEqual(reg2.find('ollama', 'm').model, 'm')

    def test_corrupt_file_tolerated(self):
        reg = self._reg()
        reg.put('ollama', 'm')
        self.base.joinpath('.config', 'polyglav').mkdir(parents=True, exist_ok=True)
        self.base.joinpath('.config', 'polyglav', 'models.json').write_text('{oops')
        reg2 = ModelRegistry(global_dir=self.base)
        self.assertEqual(reg2.all(), [])

    def test_old_shape_dropped_without_migration(self):
        old = [
            {'provider': 'ollama', 'base_url': 'https://api.ollama.com',
             'model': 'm1', 'api_key': 'secret', 'added_at': 't', 'last_used': 't'},
        ]
        path = self.base / '.config' / 'polyglav' / 'models.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(old))
        reg = ModelRegistry(global_dir=self.base)
        entry = reg.find('ollama', 'm1')
        self.assertIsNotNone(entry)
        self.assertEqual(entry.model, 'm1')
        self.assertFalse(hasattr(entry, 'api_key'))
        self.assertFalse(hasattr(entry, 'base_url'))

    def test_default_uses_config_global_dir(self):
        prev = Config.GLOBAL_DIR
        Config.GLOBAL_DIR = self.base
        try:
            reg = ModelRegistry()
            self.assertEqual(reg.path,
                             self.base / '.config' / 'polyglav' / 'models.json')
        finally:
            Config.GLOBAL_DIR = prev


if __name__ == '__main__':
    unittest.main()