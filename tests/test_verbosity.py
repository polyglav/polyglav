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


class TestVerbosityRendering(unittest.TestCase):

    def setUp(self):
        from tests.helpers import make_chat
        self.chat = make_chat()
        self.ui = self.chat._ui

    def tearDown(self):
        self.ui._stop_spinner()
        self.chat._tmp.cleanup()

    def _capture(self, fn):
        import io
        from unittest.mock import patch
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            fn()
        return out.getvalue()

    def test_thinking_levels(self):
        self.chat.config.set('verbosity.thinking', 'off')
        value = self._capture(lambda: (
            self.ui.thinking_begin(), self.ui.thinking('secret'),
            self.ui.thinking_end(1.0)))
        self.assertNotIn('secret', value)
        self.assertNotIn('Thought', value)
        self.chat.config.set('verbosity.thinking', 'summary')
        value = self._capture(lambda: (
            self.ui.thinking_begin(), self.ui.thinking('secret'),
            self.ui.thinking_end(1.0)))
        self.assertNotIn('secret', value)
        self.assertIn('✓ Thought 1.0s', value)
        self.chat.config.set('verbosity.thinking', 'full')
        value = self._capture(lambda: (
            self.ui.thinking_begin(), self.ui.thinking('secret'),
            self.ui.thinking_end(1.0)))
        self.assertIn('secret', value)
        self.assertIn('✓ Thought 1.0s', value)

    def test_tool_levels(self):
        self.chat.config.set('verbosity.tools', 'off')
        value = self._capture(lambda: (
            self.ui.activity('→', 'Write', 'a.md', ['+ body']),
            self.ui.tool_result('output')))
        self.assertNotIn('→', value)
        self.assertNotIn('+ body', value)
        self.assertNotIn('output', value)
        self.chat.config.set('verbosity.tools', 'summary')
        value = self._capture(
            lambda: self.ui.activity('→', 'Write', 'a.md', ['+ body']))
        self.assertIn('→ Write a.md', value)
        self.assertNotIn('+ body', value)
        self.assertIn('/print', value)
        self.chat.config.set('verbosity.tools', 'full')
        value = self._capture(lambda: (
            self.ui.activity('→', 'Write', 'a.md', ['+ body']),
            self.ui.tool_result('output')))
        self.assertIn('+ body', value)
        self.assertIn('output', value)

    def test_footer_levels(self):
        self.chat.config.set('verbosity.footer', 'off')
        value = self._capture(lambda: self.ui.footer(1.0, {'context': 42}))
        self.assertNotIn('Done', value)
        self.chat.config.set('verbosity.footer', 'summary')
        value = self._capture(lambda: self.ui.footer(1.0, {'context': 42}))
        self.assertIn('✓ Done 1.0s (42 tokens)', value)
        self.chat.config.set('verbosity.footer', 'full')
        self.chat.config.set('footer_tokens', ['in', 'out'])
        value = self._capture(
            lambda: self.ui.footer(1.0, {'in': 3, 'out': 4}))
        self.assertIn('✓ Done 1.0s (3t/4t)', value)

    def test_subrun_level_controls_status(self):
        self.chat.config.set('verbosity.subruns', 'off')
        value = self._capture(lambda: (
            self.ui.status_begin('Call writer', name='writer'),
            self.ui.status_end('1.0s')))
        self.assertNotIn('Call writer', value)
        self.assertNotIn('Worked', value)
        self.chat.config.set('verbosity.subruns', 'summary')
        value = self._capture(lambda: (
            self.ui.status_begin('Call writer', name='writer'),
            self.ui.status_end('1.0s')))
        self.assertIn('↳ Call writer', value)
        self.assertIn('✓ Worked: writer 1.0s', value)


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
