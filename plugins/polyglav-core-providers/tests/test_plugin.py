import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from polyglav.commands.registry import CommandRegistry
from polyglav.plugins.manager import CLIRegistry

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load():
    path = SRC / 'plugin.py'
    spec = importlib.util.spec_from_file_location(
        '_providers_plugin_under_test', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plugin = _load()


class TestProvidersPlugin(unittest.TestCase):

    def test_registers_provider_commands(self):
        registry = CommandRegistry(MagicMock())
        plugin.register_commands(registry)
        for name in ('connect', 'model', 'models', 'provider', 'providers'):
            self.assertIn(name, registry.commands)

    def test_provider_names_keep_ollama_first(self):
        names = plugin._ordered_provider_names(
            {'openai-compatible': object, 'ollama': object, 'openai': object})
        self.assertEqual(names[0], 'ollama')
        self.assertEqual(names[-1], 'openai-compatible')

    def test_derive_provider_name(self):
        self.assertEqual(
            plugin._derive_provider_name('https://llm.acme.example/v1'),
            'acme-example')

    def test_registers_models_cli(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest='command')
        cli = CLIRegistry(sub, object(), None)
        plugin.register_cli(cli)
        self.assertIn('models', cli.names())
        args = parser.parse_args(['models', 'list', 'openai'])
        self.assertEqual(args.action, 'list')
        self.assertEqual(args.provider, 'openai')
        self.assertTrue(callable(args.func))
