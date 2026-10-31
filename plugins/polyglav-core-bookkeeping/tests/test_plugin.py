import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from polyglav.commands.registry import CommandRegistry
from polyglav.tools.registry import ToolRegistry

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load():
    path = SRC / 'plugin.py'
    spec = importlib.util.spec_from_file_location(
        '_bookkeeping_plugin_under_test', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plugin = _load()


class TestBookkeepingPlugin(unittest.TestCase):

    def test_registers_commands(self):
        registry = CommandRegistry(MagicMock())
        plugin.register_commands(registry)
        for name in ('plan', 'plans', 'todo', 'todos'):
            self.assertIn(name, registry.commands)

    def test_registers_tools(self):
        registry = ToolRegistry(engine=MagicMock())
        plugin.register_tools(registry)
        self.assertTrue(registry.is_registered('plan_write'))
        self.assertTrue(registry.is_registered('todo'))
