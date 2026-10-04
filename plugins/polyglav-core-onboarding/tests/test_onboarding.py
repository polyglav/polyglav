import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from polyglav.config import Config

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load():
    path = SRC / 'plugin.py'
    spec = importlib.util.spec_from_file_location(
        '_onboarding_plugin_under_test', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plugin = _load()


class TestOnboarding(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Config(path=self.tmp.name)
        self._stdin = patch('sys.stdin')
        stdin = self._stdin.start()
        stdin.isatty.return_value = True

    def tearDown(self):
        self._stdin.stop()
        self.tmp.cleanup()

    def _chat(self, unattended=False, ui=None):
        return SimpleNamespace(
            config=self.config,
            _is_unattended=lambda: unattended,
            _ui=ui)

    def test_compose_prompt_includes_purpose_and_persona(self):
        prompt = plugin.compose_prompt('a CLI for widgets', 'You are Widget.')
        self.assertIn('You are Widget.', prompt)
        self.assertIn('Project purpose: a CLI for widgets', prompt)

    def test_compose_prompt_default_persona(self):
        prompt = plugin.compose_prompt('', '')
        self.assertIn(plugin.DEFAULT_PERSONA, prompt)

    def test_should_run_without_config(self):
        self.assertTrue(plugin.should_run(self._chat()))

    def test_should_run_false_with_config(self):
        self.config.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.local_path.write_text('{}')
        self.assertFalse(plugin.should_run(self._chat()))

    def test_should_run_false_unattended(self):
        self.assertFalse(plugin.should_run(self._chat(unattended=True)))

    def test_run_writes_config(self):
        answers = {
            plugin.PROMPT_PURPOSE: 'a widget factory',
            plugin.PROMPT_PERSONA: 'You are the widget assistant.',
            plugin.PROMPT_FOLLOW: 'n',
            plugin.PROMPT_LABEL: 'y',
        }
        self.assertTrue(plugin.run(self._chat(), ask=answers.get))
        self.assertEqual(self.config.get('focus_on_delegate'), 'off')
        self.assertTrue(self.config.get('prompt_role'))
        self.assertIn('widget assistant', self.config.get('system_prompt'))
        self.assertTrue(self.config.local_path.exists())

    def test_run_skips_when_configured(self):
        self.config.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.local_path.write_text('{}')
        self.assertFalse(plugin.run(self._chat(), ask=lambda q: 'x'))

    def test_run_force_overrides_guard(self):
        self.config.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.local_path.write_text('{}')
        self.assertTrue(plugin.run(self._chat(), force=True, ask=lambda q: 'x'))

    def test_run_skips_unattended(self):
        self.assertFalse(plugin.run(self._chat(unattended=True), force=True,
                                    ask=lambda q: 'x'))

    def test_register_startup_appends_run(self):
        hooks = []
        plugin.register_startup(hooks)
        self.assertEqual(hooks, [plugin.run])

    def test_register_commands(self):
        class FakeRegistry:
            def __init__(self):
                self.commands = {}

            def register(self, name, handler=None, description=''):
                self.commands[name] = handler

        registry = FakeRegistry()
        plugin.register_commands(registry)
        self.assertIn('onboard', registry.commands)


if __name__ == '__main__':
    unittest.main()
