import json
import tempfile
import unittest

from polyglav.config import Config
from polyglav.plugins.manager import PluginManager, PluginError
from polyglav.tools.registry import ToolRegistry

BUNDLED = {
    'polyglav-core-anthropic',
    'polyglav-core-dev',
    'polyglav-core-edit',
    'polyglav-core-eval',
    'polyglav-core-exec',
    'polyglav-core-fs',
    'polyglav-core-git',
    'polyglav-core-groq',
    'polyglav-core-mcp',
    'polyglav-core-ollama',
    'polyglav-core-openai',
    'polyglav-core-opencode',
    'polyglav-core-web',
    'polyglav-core-webhook',
}


class TestBundledPlugins(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Config(path=self.tmp.name)
        self.pm = PluginManager(self.config)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bundled_discovered_and_loaded(self):
        self.pm.load()
        names = {i.name for i in self.pm.status()}
        self.assertEqual(names, BUNDLED)
        for n in names:
            info = self.pm.get(n)
            self.assertEqual(info.status, 'loaded', n)
            self.assertEqual(info.origin, 'bundled', n)

    def test_bundled_tools_registered(self):
        self.pm.load()
        reg = ToolRegistry()
        self.pm.register_tools(reg)
        tools = set(reg.names())
        self.assertTrue({'web_search', 'web_fetch'} <= tools)
        self.assertTrue({'file_read', 'list_dir', 'file_write', 'glob', 'grep'} <= tools)
        self.assertIn('run_command', tools)
        self.assertIn('file_edit', tools)
        self.assertIn('git', tools)
        self.assertIn('git_commit', tools)
        self.assertTrue({'code_test', 'code_lint', 'code_format'} <= tools)

    def test_search_service_registered(self):
        self.pm.load()
        service = self.pm.service('search')
        self.assertIsNotNone(service)
        self.assertTrue(callable(service.search))
        self.assertTrue(callable(service.display))
        self.assertTrue(callable(service.context))

    def test_mcp_server_service_registered(self):
        self.pm.load()
        service = self.pm.service('mcp_server')
        self.assertIsNotNone(service)
        self.assertTrue(callable(service.serve_stdio))
        self.assertTrue(callable(service.handle_http))

    def test_report_service_registered(self):
        self.pm.load()
        service = self.pm.service('report')
        self.assertIsNotNone(service)
        self.assertTrue(callable(service.report))

    def test_bundled_cannot_uninstall(self):
        self.pm.load()
        with self.assertRaises(PluginError):
            self.pm.uninstall('polyglav-core-fs')

    def test_bundled_cannot_update(self):
        self.pm.load()
        with self.assertRaises(PluginError):
            self.pm.update('polyglav-core-fs')

    def test_bundled_override_by_local(self):
        local = self.config.local_path.parent / 'plugins' / 'polyglav-core-fs'
        local.mkdir(parents=True, exist_ok=True)
        with open(local / 'manifest.json', 'w') as f:
            json.dump({'name': 'polyglav-core-fs', 'version': '9.0.0'}, f)
        with open(local / 'plugin.py', 'w') as f:
            f.write('def register_tools(registry):\n    pass\n')
        self.pm.load()
        info = self.pm.get('polyglav-core-fs')
        self.assertEqual(info.version, '9.0.0')
        self.assertEqual(info.origin, 'local')

    def test_bundled_disabled_via_plugins_config(self):
        self.config.set('plugins', ['polyglav-core-web', 'polyglav-core-fs'])
        self.pm.load()
        self.assertEqual(self.pm.get('polyglav-core-web').status, 'loaded')
        self.assertEqual(self.pm.get('polyglav-core-fs').status, 'loaded')
        self.assertEqual(self.pm.get('polyglav-core-exec').status, 'disabled')

    def test_bundled_in_default_config(self):
        from polyglav.config import DEFAULT_CONFIG
        for name in BUNDLED:
            self.assertIn(name, DEFAULT_CONFIG['plugins'])

    def test_bundled_providers_registered(self):
        self.pm.load()
        providers = set(self.pm.provider_classes())
        self.assertTrue({'ollama', 'openai', 'groq', 'anthropic', 'opencode', 'opencode-go'} <= providers)


if __name__ == '__main__':
    unittest.main()
