import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
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


class FakeFactory:
    DEFAULT_BASE_URL = 'https://api.ollama.com'


class FakeOpenAIFactory:
    DEFAULT_BASE_URL = 'https://api.openai.com/v1'


class FakeEntry:
    def __init__(self, provider):
        self.provider = provider


class FakeProviders:
    def __init__(self):
        self.entries = {}
        self.keys = {}
        self.urls = {}

    def all(self):
        return [FakeEntry(name) for name in sorted(self.entries)]

    def api_key_for(self, name):
        return self.keys.get(name, '')

    def base_url_for(self, name):
        return self.urls.get(name, '')

    def put(self, name, base_url, api_key):
        self.entries[name] = True
        self.urls[name] = base_url
        if api_key or name not in self.keys:
            self.keys[name] = api_key


class FakeModels:
    def __init__(self):
        self.entries = []

    def put(self, provider, model):
        self.entries.append((provider, model))


class FakeUI:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(message)


class FakeChat:
    def __init__(self, config, unattended=False, ui=None,
                 connected=True, models=None):
        self.config = config
        self._unattended = unattended
        self._ui = ui
        self.providers = FakeProviders()
        self.models = FakeModels()
        self.connected = connected
        self.model_list = list(models or ['model-a', 'model-b'])
        self.reinitialized = False

    def _is_unattended(self):
        return self._unattended

    def _merged_providers(self):
        return {'ollama': FakeFactory, 'openai': FakeOpenAIFactory}

    def check_connection(self, **_kwargs):
        if self.connected:
            return True, 'ok', list(self.model_list)
        return False, 'connection refused', []

    def _reinit_provider(self):
        self.reinitialized = True


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

    def _chat(self, unattended=False, ui=None, **kwargs):
        return FakeChat(self.config, unattended=unattended, ui=ui, **kwargs)

    def _answers(self, **values):
        return values.get

    def test_compose_prompt_includes_purpose_and_persona(self):
        prompt = plugin.compose_prompt('a CLI for widgets', 'You are Widget.')
        self.assertIn('You are Widget.', prompt)
        self.assertIn('Project purpose: a CLI for widgets', prompt)

    def test_compose_prompt_default_persona(self):
        prompt = plugin.compose_prompt('', '')
        self.assertIn(plugin.DEFAULT_PERSONA, prompt)

    def test_compose_prompt_guides_team_confirmation(self):
        prompt = plugin.compose_prompt('a CLI', 'You are Assistant.')
        self.assertIn('confirm the design', prompt)
        self.assertIn('hierarchical', prompt.lower())

    def test_should_run_without_config(self):
        self.assertTrue(plugin.should_run(self._chat()))

    def test_should_run_false_with_config(self):
        self.config.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.local_path.write_text('{}')
        self.assertFalse(plugin.should_run(self._chat()))

    def test_should_run_false_unattended(self):
        self.assertFalse(plugin.should_run(self._chat(unattended=True)))

    def test_run_writes_config(self):
        chat = self._chat()
        answers = self._answers(**{
            plugin.PROMPT_PROVIDER.format(default='ollama'): '1',
            plugin.PROMPT_KEY_EMPTY: '',
            plugin.PROMPT_MODEL.format(default='model-a'): '1',
            plugin.PROMPT_MODE.format(default='read'): 'write',
            plugin.PROMPT_PURPOSE: 'a widget factory',
            plugin.PROMPT_PERSONA: 'You are the widget assistant.',
            plugin.PROMPT_OUTPUT: 'y',
        })
        self.assertTrue(plugin.run(chat, ask=answers, secret=lambda _: ''))
        self.assertTrue(self.config.get('output_log'))
        self.assertIn('widget assistant', self.config.get('system_prompt'))
        self.assertIsNone(self.config.get('focus_on_delegate'))
        self.assertIsNone(self.config.get('prompt_role'))
        self.assertTrue(self.config.local_path.exists())
        self.assertEqual(self.config.get('provider'), 'ollama')
        self.assertEqual(self.config.get('base_url'), 'https://api.ollama.com')
        self.assertEqual(self.config.get('model'), 'model-a')
        self.assertEqual(self.config.get('mode'), 'write')
        self.assertIn(('ollama', 'model-a'), chat.models.entries)
        self.assertTrue(chat.reinitialized)

    def test_run_keeps_stored_key(self):
        chat = self._chat()
        chat.providers.keys['ollama'] = 'stored-key'
        answers = self._answers(**{
            plugin.PROMPT_PROVIDER.format(default='ollama'): '',
            plugin.PROMPT_KEY.format(default='stored'): '',
            plugin.PROMPT_MODEL.format(default='model-a'): '',
            plugin.PROMPT_MODE.format(default='read'): '',
            plugin.PROMPT_PURPOSE: '',
            plugin.PROMPT_PERSONA: '',
            plugin.PROMPT_OUTPUT: '',
        })
        self.assertTrue(plugin.run(chat, ask=answers, secret=lambda _: ''))
        self.assertEqual(chat.providers.keys['ollama'], 'stored-key')

    def test_run_selects_model_by_number(self):
        chat = self._chat()
        answers = self._answers(**{
            plugin.PROMPT_PROVIDER.format(default='ollama'): '1',
            plugin.PROMPT_KEY_EMPTY: 'key-123',
            plugin.PROMPT_MODEL.format(default='model-a'): '2',
            plugin.PROMPT_MODE.format(default='read'): '',
            plugin.PROMPT_PURPOSE: '',
            plugin.PROMPT_PERSONA: '',
            plugin.PROMPT_OUTPUT: '',
        })
        self.assertTrue(plugin.run(chat, ask=answers, secret=lambda _: 'key-123'))
        self.assertEqual(chat.providers.keys['ollama'], 'key-123')
        self.assertEqual(self.config.get('model'), 'model-b')

    def test_run_custom_provider_url(self):
        chat = self._chat()
        answers = self._answers(**{
            plugin.PROMPT_PROVIDER.format(default='ollama'): 'https://llm.example/v1',
            plugin.PROMPT_KEY_EMPTY: '',
            plugin.PROMPT_MODEL.format(default='model-a'): '1',
            plugin.PROMPT_MODE.format(default='read'): '',
            plugin.PROMPT_PURPOSE: '',
            plugin.PROMPT_PERSONA: '',
            plugin.PROMPT_OUTPUT: '',
        })
        self.assertTrue(plugin.run(chat, ask=answers, secret=lambda _: ''))
        self.assertEqual(self.config.get('provider'), 'llm-example')
        self.assertEqual(self.config.get('base_url'), 'https://llm.example/v1')
        self.assertEqual(self.config.get('model'), 'model-a')

    def test_run_openai_compatible_asks_base_url(self):
        chat = self._chat()
        answers = self._answers(**{
            plugin.PROMPT_PROVIDER.format(default='ollama'): 'openai-compatible',
            'Base URL: ': 'https://gateway.example/v1',
            plugin.PROMPT_KEY_EMPTY: '',
            plugin.PROMPT_MODEL.format(default='model-a'): '',
            plugin.PROMPT_MODE.format(default='read'): '',
            plugin.PROMPT_PURPOSE: '',
            plugin.PROMPT_PERSONA: '',
            plugin.PROMPT_OUTPUT: '',
        })
        self.assertTrue(plugin.run(chat, ask=answers, secret=lambda _: ''))
        self.assertEqual(self.config.get('provider'), 'openai-compatible')
        self.assertEqual(self.config.get('base_url'), 'https://gateway.example/v1')

    def test_run_manual_model_when_probe_fails(self):
        chat = self._chat(connected=False)
        answers = self._answers(**{
            plugin.PROMPT_PROVIDER.format(default='ollama'): '1',
            plugin.PROMPT_KEY_EMPTY: '',
            plugin.PROMPT_MODEL.format(default=self.config.get('model')):
                'manual-model',
            plugin.PROMPT_SAVE_ANYWAY: 'y',
            plugin.PROMPT_MODE.format(default='read'): '',
            plugin.PROMPT_PURPOSE: '',
            plugin.PROMPT_PERSONA: '',
            plugin.PROMPT_OUTPUT: '',
        })
        self.assertTrue(plugin.run(chat, ask=answers, secret=lambda _: ''))
        self.assertEqual(self.config.get('model'), 'manual-model')

    def test_run_unknown_mode_keeps_current(self):
        chat = self._chat()
        answers = self._answers(**{
            plugin.PROMPT_PROVIDER.format(default='ollama'): '1',
            plugin.PROMPT_KEY_EMPTY: '',
            plugin.PROMPT_MODEL.format(default='model-a'): '',
            plugin.PROMPT_MODE.format(default='read'): 'bogus',
            plugin.PROMPT_PURPOSE: '',
            plugin.PROMPT_PERSONA: '',
            plugin.PROMPT_OUTPUT: '',
        })
        self.assertTrue(plugin.run(chat, ask=answers, secret=lambda _: ''))
        self.assertEqual(self.config.get('mode'), 'read')

    def test_run_warm_welcome_and_option_hint(self):
        chat = self._chat(ui=FakeUI())
        answers = self._answers(**{
            plugin.PROMPT_PROVIDER.format(default='ollama'): '1',
            plugin.PROMPT_KEY_EMPTY: '',
            plugin.PROMPT_MODEL.format(default='model-a'): '',
            plugin.PROMPT_MODE.format(default='read'): '',
            plugin.PROMPT_PURPOSE: '',
            plugin.PROMPT_PERSONA: '',
            plugin.PROMPT_OUTPUT: '',
        })
        self.assertTrue(plugin.run(chat, ask=answers, secret=lambda _: ''))
        welcome = chat._ui.messages[0]
        self.assertIn('Welcome to Polyglav', welcome)
        self.assertIn('set up this project together', welcome)
        hint = chat._ui.messages[-1]
        self.assertIn('/connect', hint)
        self.assertIn('/model', hint)
        self.assertIn('/modes', hint)
        self.assertIn('/config --verbose', hint)

    def test_run_output_log_default_off(self):
        chat = self._chat()
        answers = self._answers(**{
            plugin.PROMPT_PROVIDER.format(default='ollama'): '1',
            plugin.PROMPT_KEY_EMPTY: '',
            plugin.PROMPT_MODEL.format(default='model-a'): '',
            plugin.PROMPT_MODE.format(default='read'): '',
            plugin.PROMPT_PURPOSE: '',
            plugin.PROMPT_PERSONA: '',
            plugin.PROMPT_OUTPUT: '',
        })
        self.assertTrue(plugin.run(chat, ask=answers, secret=lambda _: ''))
        self.assertFalse(self.config.get('output_log'))

    def test_run_skips_when_configured(self):
        self.config.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.local_path.write_text('{}')
        self.assertFalse(plugin.run(self._chat(), ask=lambda q: 'x'))

    def test_run_force_overrides_guard(self):
        self.config.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.local_path.write_text('{}')
        chat = self._chat()
        answers = self._answers(**{
            plugin.PROMPT_PROVIDER.format(default='ollama'): '1',
            plugin.PROMPT_KEY_EMPTY: '',
            plugin.PROMPT_MODEL.format(default='model-a'): '',
            plugin.PROMPT_MODE.format(default='read'): '',
            plugin.PROMPT_PURPOSE: '',
            plugin.PROMPT_PERSONA: '',
            plugin.PROMPT_OUTPUT: '',
        })
        self.assertTrue(plugin.run(chat, force=True, ask=answers,
                                   secret=lambda _: ''))

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
