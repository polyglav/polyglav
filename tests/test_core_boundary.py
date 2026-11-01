import importlib.util
import tempfile
import unittest
from pathlib import Path

from polyglav.config import Config, DEFAULT_CONFIG
from polyglav.plugins.manager import FrontendRegistry, PluginManager


class TestCoreBoundary(unittest.TestCase):

    def test_core_modules_present(self):
        for name in ('polyglav.engine', 'polyglav.tools.registry',
                     'polyglav.tools.policy', 'polyglav.providers.base',
                     'polyglav.config', 'polyglav.sessions.manager',
                     'polyglav.runs'):
            self.assertIsNotNone(importlib.util.find_spec(name), name)

    def test_optional_modules_absent(self):
        for name in ('polyglav.chat', 'polyglav.jobs', 'polyglav.memory',
                     'polyglav.scheduler', 'polyglav.skills',
                     'polyglav.teams'):
            self.assertIsNone(importlib.util.find_spec(name), name)

    def test_default_plugins(self):
        plugins = set(DEFAULT_CONFIG['plugins'])
        self.assertIn('polyglav-core-repl', plugins)
        for name in ('polyglav-core-eval', 'polyglav-core-fleet',
                     'polyglav-core-jobs', 'polyglav-core-mcp',
                     'polyglav-core-quality', 'polyglav-core-storage-sqlite',
                     'polyglav-core-webhook'):
            self.assertNotIn(name, plugins)

    def test_default_services_and_frontend(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(path=tmp)
            pm = PluginManager(config)
            pm.load()
            for name in ('role_registry', 'team_registry', 'skill_registry',
                         'memory'):
                self.assertIsNotNone(pm.service(name), name)
            frontends = FrontendRegistry()
            pm.register_frontends(frontends)
            self.assertIn('repl', frontends.names())


if __name__ == '__main__':
    unittest.main()
