import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from polyglav.config import Config, verbosity_level


class TestVerbosityResolution(unittest.TestCase):

    def test_presets(self):
        quiet = {'verbosity': 'quiet'}
        self.assertEqual(verbosity_level(quiet, 'thinking'), 'off')
        self.assertEqual(verbosity_level(quiet, 'output'), 'off')
        self.assertEqual(verbosity_level(quiet, 'status'), 'off')
        self.assertEqual(verbosity_level(quiet, 'tools'), 'off')
        normal = {'verbosity': 'normal'}
        self.assertEqual(verbosity_level(normal, 'thinking'), 'off')
        self.assertEqual(verbosity_level(normal, 'output'), 'agent')
        self.assertEqual(verbosity_level(normal, 'status'), 'on')
        self.assertEqual(verbosity_level(normal, 'tools'), 'summary')
        verbose = {'verbosity': 'verbose'}
        self.assertEqual(verbosity_level(verbose, 'thinking'), 'all')
        self.assertEqual(verbosity_level(verbose, 'output'), 'all')
        self.assertEqual(verbosity_level(verbose, 'tools'), 'full')
        self.assertEqual(verbosity_level(verbose, 'footer'), 'full')

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
        self.assertEqual(verbosity_level(None, 'thinking'), 'off')
        self.assertEqual(verbosity_level(None, 'tools'), 'off')

    def test_old_thinking_values_are_normalized(self):
        self.assertEqual(
            verbosity_level({'verbosity.thinking': 'summary'}, 'thinking'), 'off')
        self.assertEqual(
            verbosity_level({'verbosity.thinking': 'full'}, 'thinking'), 'all')


class TestVerbosityRendering(unittest.TestCase):

    def setUp(self):
        from tests.helpers import make_chat
        self.chat = make_chat()
        self.ui = self.chat._ui

    def tearDown(self):
        self.ui._stop_spinner()
        self.chat._tmp.cleanup()

    def _capture(self, fn):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            fn()
        return out.getvalue()

    def _thinking(self, scope):
        self.chat.config.set('verbosity.thinking', scope)
        return self._capture(lambda: (
            self.ui.thinking_begin(), self.ui.thinking('secret'),
            self.ui.thinking_end(1.0)))

    def test_thinking_off(self):
        value = self._thinking('off')
        self.assertNotIn('secret', value)
        self.assertNotIn('Thought', value)

    def test_thinking_assistant(self):
        value = self._thinking('assistant')
        self.assertIn('secret', value)
        self.assertIn('✓ Thought 1.0s', value)

    def test_thinking_agent_and_all_include_root(self):
        for scope in ('agent', 'all'):
            value = self._thinking(scope)
            self.assertIn('secret', value)
            self.assertIn('✓ Thought 1.0s', value)

    def test_thinking_scope_for_role_subrun(self):
        self.ui._loop.role = 'writer'
        self.ui._loop._sub_run = True
        try:
            self.assertIn('secret', self._thinking('agent'))
            self.assertNotIn('secret', self._thinking('assistant'))
            self.assertIn('secret', self._thinking('all'))
        finally:
            self.ui._loop.role = ''
            self.ui._loop._sub_run = False

    def test_output_scope(self):
        self.chat.config.set('verbosity.output', 'off')
        self.assertNotIn('Draft', self._capture(
            lambda: self.ui.sub_result('[call writer] Draft', role='writer')))
        self.chat.config.set('verbosity.output', 'assistant')
        self.assertNotIn('Draft', self._capture(
            lambda: self.ui.sub_result('[call writer] Draft', role='writer')))
        self.chat.config.set('verbosity.output', 'agent')
        self.assertIn('Draft', self._capture(
            lambda: self.ui.sub_result('[call writer] Draft', role='writer')))
        self.assertNotIn('Draft', self._capture(
            lambda: self.ui.sub_result('[delegate] Draft', role='')))
        self.chat.config.set('verbosity.output', 'all')
        self.assertIn('Draft', self._capture(
            lambda: self.ui.sub_result('[delegate] Draft', role='')))

    def test_status_lines_show_regardless_of_output(self):
        self.chat.config.set('verbosity.output', 'off')
        value = self._capture(lambda: (
            self.ui.status_begin('Call writer', name='writer'),
            self.ui.status_end('1.0s')))
        self.assertIn('Call writer', value)
        self.assertIn('✓ Worked: writer 1.0s', value)

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

    def test_old_keys_map_to_scopes(self):
        config = self._config({
            'show_thinking': True,
            'show_tool_output': True,
            'subrun_verbosity': 'full',
            'delegate_echo': True,
            'show_context_size': False,
            'show_errors': True,
        })
        self.assertEqual(config.get('verbosity.thinking'), 'all')
        self.assertEqual(config.get('verbosity.tools'), 'full')
        self.assertEqual(config.get('verbosity.output'), 'all')
        self.assertEqual(config.get('verbosity.footer'), 'summary')
        for key in ('show_thinking', 'show_tool_output', 'subrun_verbosity',
                    'delegate_echo', 'show_context_size', 'show_errors'):
            self.assertNotIn(key, config._local_raw)

    def test_old_thinking_values_map_to_scopes(self):
        summary = self._config({'verbosity.thinking': 'summary'})
        self.assertEqual(summary.get('verbosity.thinking'), 'off')
        full = self._config({'verbosity.thinking': 'full'})
        self.assertEqual(full.get('verbosity.thinking'), 'all')

    def test_old_subruns_map_to_output(self):
        summary = self._config({'verbosity.subruns': 'summary'})
        self.assertEqual(summary.get('verbosity.output'), 'assistant')
        full = self._config({'verbosity.subruns': 'full'})
        self.assertEqual(full.get('verbosity.output'), 'all')
        off = self._config({'verbosity.subruns': 'off'})
        self.assertEqual(off.get('verbosity.output'), 'off')
        self.assertNotIn('verbosity.subruns', summary._local_raw)

    def test_tool_status_visible_maps_to_tools_level(self):
        hidden = self._config({'tool_status_visible': False})
        self.assertEqual(hidden.get('verbosity.tools'), 'off')
        self.assertNotIn('tool_status_visible', hidden._local_raw)
        shown = self._config({'tool_status_visible': True})
        self.assertEqual(shown.get('verbosity.tools'), 'summary')

    def test_quiet_old_flags_map_to_off(self):
        config = self._config({
            'show_thinking': False,
            'show_notes': False,
            'delegate_echo': False,
            'status_spinner': False,
        })
        self.assertEqual(config.get('verbosity.thinking'), 'off')
        self.assertEqual(config.get('verbosity.tools'), 'off')
        self.assertEqual(config.get('verbosity.output'), 'off')

    def test_new_key_wins_over_old_key(self):
        config = self._config({
            'verbosity.thinking': 'agent',
            'show_thinking': True,
        })
        self.assertEqual(config.get('verbosity.thinking'), 'agent')
        self.assertNotIn('show_thinking', config._local_raw)


if __name__ == '__main__':
    unittest.main()
