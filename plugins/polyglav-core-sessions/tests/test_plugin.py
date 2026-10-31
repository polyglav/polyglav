import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from polyglav.commands.registry import CommandRegistry

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load():
    path = SRC / 'plugin.py'
    spec = importlib.util.spec_from_file_location(
        '_sessions_plugin_under_test', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plugin = _load()


class TestSessionsPlugin(unittest.TestCase):

    def test_registers_sessions_command(self):
        registry = CommandRegistry(MagicMock())
        plugin.register_commands(registry)
        self.assertIn('sessions', registry.commands)
