import importlib.util
import sys
import unittest
from pathlib import Path

from polyglav.plugins.manager import CLIRegistry

SRC = Path(__file__).resolve().parents[1] / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load():
    path = SRC / 'plugin.py'
    spec = importlib.util.spec_from_file_location(
        '_fleet_plugin_under_test', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plugin = _load()


class TestFleetPlugin(unittest.TestCase):

    def test_registers_fleet_cli(self):
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest='command')
        cli = CLIRegistry(sub, object(), None)
        plugin.register_cli(cli)
        self.assertIn('fleet', cli.names())
        args = parser.parse_args(['fleet', 'status'])
        self.assertEqual(args.action, 'status')
        self.assertTrue(callable(args.func))
