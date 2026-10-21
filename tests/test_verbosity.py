import json
import tempfile
import unittest
from pathlib import Path

from polyglav.config import Config, verbosity_level


class TestVerbosityResolution(unittest.TestCase):

    def test_presets(self):
        self.assertEqual(verbosity_level({'verbosity': 'quiet'}, 'thinking'), 'off')
        self.assertEqual(verbosity_level({'verbosity': 'normal'}, 'thinking'), 'summary')
        self.assertEqual(verbosity_level({'verbosity': 'verbose'}, 'thinking'), 'full')
        self.assertEqual(verbosity_level({'verbosity': 'quiet'}, 'tools'), 'off')
        self.assertEqual(verbosity_level({'verbosity': 'normal'}, 'subruns'), 'summary')
        self.assertEqual(verbosity_level({'verbosity': 'verbose'}, 'footer'), 'full')

    def test_scoped_override_wins(self):
        config = {'verbosity': 'quiet', 'verbosity.tools': 'full'}
        self.assertEqual(verbosity_level(config, 'tools'), 'full')
        self.assertEqual(verbosity_level(config, 'thinking'), 'off')

    def test_inherit_uses_preset(self):
        config = {'verbosity': 'verbose', 'verbosity.tools': 'inherit'}
        self.assertEqual(verbosity_level(config, 'tools'), 'full')

    def test_invalid_values_fall_back(self):
        config = {'verbosity': 'nonsense', 'verbosity.tools': 'nonsense'}
        self.assertEqual(verbosity_level(config, 'tools'), 'summary')
        self.assertEqual(verbosity_level(config, 'unknown'), 'summary')
        self.assertEqual(verbosity_level(None, 'tools'), 'summary')


class TestVerbosityMigration(unittest.TestCase):

    def setUp(self):
        self._old_global = Config.GLOBAL_DIR
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        Config.GLOBAL_DIR = self.root / 'global'

    def tearDown(self):
        Config.GLOBAL_DIR = self._old_global
        self._tmp.cleanup()

    def _config(self, data):
        local = self.root / '.polyglav'
        local.mkdir(parents=True, exist_ok=True)
        (local / 'config.json').write_text(json.dumps(data))
        return Config(path=str(self.root))

    def test_old_keys_map_to_scoped_levels(self):
        config = self._config({
            'show_thinking': True,
            'show_thought_duration': False,
            'show_tool_output': True,
            'subrun_verbosity': 'full',
            'delegate_echo': True,
            'show_context_size': False,
            'show_errors': True,
        })
        self.assertEqual(config.get('verbosity.thinking'), 'full')
        self.assertEqual(config.get('verbosity.tools'), 'full')
        self.assertEqual(config.get('verbosity.subruns'), 'full')
        self.assertEqual(config.get('verbosity.footer'), 'summary')
        for key in ('show_thinking', 'show_thought_duration', 'show_tool_output',
                    'subrun_verbosity', 'delegate_echo', 'show_context_size',
                    'show_errors'):
            self.assertNotIn(key, config._local_raw)

    def test_quiet_old_flags_map_to_off(self):
        config = self._config({
            'show_thinking': False,
            'show_thought_duration': False,
            'show_notes': False,
            'delegate_echo': False,
            'status_spinner': False,
        })
        self.assertEqual(config.get('verbosity.thinking'), 'off')
        self.assertEqual(config.get('verbosity.tools'), 'off')
        self.assertEqual(config.get('verbosity.subruns'), 'off')

    def test_new_key_wins_over_old_key(self):
        config = self._config({
            'verbosity.thinking': 'summary',
            'show_thinking': True,
        })
        self.assertEqual(config.get('verbosity.thinking'), 'summary')
        self.assertNotIn('show_thinking', config._local_raw)


if __name__ == '__main__':
    unittest.main()
