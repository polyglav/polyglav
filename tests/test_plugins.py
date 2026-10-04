import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from polyglav.config import Config
from polyglav.plugins.manager import PluginManager, PluginError, version_matches
from polyglav.tools.registry import ToolRegistry
from polyglav.tools.policy import ToolPolicy
from polyglav.commands.registry import CommandRegistry
from polyglav.ui import NullUI


SIMPLE_TOOL_PLUGIN = '''
def register_tools(registry):
    @registry.register(
        name='hello',
        description='Say hello',
        parameters={'type': 'object', 'properties': {}},
    )
    def hello():
        return 'hello from plugin'
'''

PROVIDER_PLUGIN = '''
from polyglav.providers.base import OpenAICompatibleProvider


class MyProvider(OpenAICompatibleProvider):
    DEFAULT_BASE_URL = 'https://my.example.com'
    DEFAULT_MODEL = 'my-model'


def register_providers(providers):
    providers['myprovider'] = MyProvider
'''

COMMAND_PLUGIN = '''
def register_commands(commands):
    @commands.register('frobnicate', description='Frobnicate')
    def frob(_=None):
        print('frobbed')
'''

LAZY_DEP_PLUGIN = '''
def register_tools(registry):
    @registry.register(
        name='uses_dep',
        description='Use a missing dependency',
        parameters={'type': 'object', 'properties': {}},
    )
    def uses_dep():
        try:
            import polyglav_definitely_missing_pkg
        except ImportError:
            return 'Error: uses_dep requires "polyglav_definitely_missing_pkg" - pip install polyglav_definitely_missing_pkg'
        return 'ok'
'''

POLICY_PLUGIN = '''
def register_tools(registry):
    @registry.register(
        name='confidential',
        description='Read a secret file',
        parameters={'type': 'object', 'properties': {}},
        category='read',
        permission='read',
    )
    def confidential():
        return 'secret'
'''

SERVICE_PLUGIN = '''
def register_services(services):
    services['greet'] = lambda: 'hello from service'
'''

TYPE_PLUGIN = '''
def register_roles(registry):
    registry.add_plugin({'name': 'helper',
                         'system_prompt': 'Helper type from a plugin',
                         'tags': ['plugin']})
'''

TYPE_FAIL_PLUGIN = '''
def register_roles(registry):
    raise RuntimeError('type hook exploded')
'''

TEAM_PLUGIN = '''
def register_teams(teams):
    teams.add_plugin({'name': 'sme',
                      'description': 'Small team from a plugin',
                      'stages': [{'role': 'researcher', 'task_hint': 'gather'},
                                 {'role': 'writer'}]})
'''

SKILL_PLUGIN = '''
def register_skills(skills):
    skills.add_plugin({'name': 'writers',
                       'description': 'Team writing skills',
                       'content': '# Writers\\n\\nProduce clean prose.'})
'''

FIXTURE_PLUGIN = '''
def register_fixtures(fixtures):
    fixtures.update({'read-foo': {'task': 'Read foo', 'expected': ['file_read']},
                     'list-dir': {'task': 'List the dir'}})
'''


SIMPLE_MANIFEST = {
    'name': 'hello',
    'version': '1.2.3',
    'description': 'A test plugin',
    'provides': {'tools': ['hello'], 'providers': [], 'commands': []},
}


def write_plugin(plugins_root, name, entry, manifest=None):
    pdir = plugins_root / name
    pdir.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        with open(pdir / 'manifest.json', 'w') as f:
            json.dump(manifest, f)
    with open(pdir / 'plugin.py', 'w') as f:
        f.write(entry)


def write_bare_py(plugins_root, name, content):
    (plugins_root / f'{name}.py').write_text(content)


class TestVersionMatches(unittest.TestCase):

    def test_empty_constraint(self):
        self.assertTrue(version_matches('0.13.0', ''))

    def test_operator_ranges(self):
        self.assertTrue(version_matches('0.13.0', '>=0.12.0,<1.0'))
        self.assertTrue(version_matches('0.12.0', '==0.12.0'))
        self.assertTrue(version_matches('0.12.5', '>=0.12.0,<0.13.0'))

    def test_operator_ranges_reject(self):
        self.assertFalse(version_matches('0.11.0', '>=0.12.0'))
        self.assertFalse(version_matches('1.1.0', '<1.0'))
        self.assertFalse(version_matches('0.13.0', '<=0.12.0'))
        self.assertFalse(version_matches('0.12.5', '==0.12.0'))


class PluginTestBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.plugins_dir = self.root / '.polyglav' / 'plugins'
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        with open(self.root / '.polyglav' / 'config.json', 'w') as f:
            json.dump({'plugins': []}, f)
        self.config = Config(path=self.root)
        self.pm = PluginManager(self.config)

    def tearDown(self):
        self.tmp.cleanup()

    def make_pm(self, config_data=None):
        data = {'plugins': []}
        if config_data:
            data.update(config_data)
        with open(self.root / '.polyglav' / 'config.json', 'w') as f:
            json.dump(data, f)
        self.config = Config(path=self.root)
        return PluginManager(self.config)


class TestDiscovery(PluginTestBase):

    def test_bundled_dir_resolves(self):
        from polyglav.plugins.manager import PluginManager
        d = PluginManager._bundled_dir()
        self.assertTrue(d.is_dir())
        self.assertTrue((d / 'polyglav-core-fs').is_dir())

    def test_bundled_dir_import_failure_falls_back(self):
        import sys as _sys
        from polyglav import plugins as pkg
        from polyglav.plugins.manager import PluginManager
        key = 'polyglav.plugins.bundled'
        saved_module = _sys.modules.get(key)
        saved_attr = getattr(pkg, 'bundled', None)
        saved_path = list(pkg.__path__)
        _sys.modules.pop(key, None)
        try:
            delattr(pkg, 'bundled')
        except AttributeError:
            pass
        try:
            pkg.__path__[:] = []
            d = PluginManager._bundled_dir()
            self.assertTrue(d.is_dir())
            self.assertTrue((d / 'polyglav-core-fs').is_dir())
        finally:
            pkg.__path__[:] = saved_path
            if saved_attr is not None:
                pkg.bundled = saved_attr
            if saved_module is not None:
                _sys.modules[key] = saved_module

    def test_bare_py_plugin(self):
        write_bare_py(self.plugins_dir, 'hello', SIMPLE_TOOL_PLUGIN)
        self.pm.load()
        info = self.pm.get('hello')
        self.assertIsNotNone(info)
        self.assertEqual(info.entry, 'hello.py')
        self.assertEqual(info.version, '0.0.0')
        self.assertEqual(info.status, 'loaded')

    def test_directory_plugin_manifest(self):
        write_plugin(self.plugins_dir, 'hello', SIMPLE_TOOL_PLUGIN, SIMPLE_MANIFEST)
        self.pm.load()
        info = self.pm.get('hello')
        self.assertEqual(info.version, '1.2.3')
        self.assertEqual(info.description, 'A test plugin')
        self.assertEqual(info.status, 'loaded')

    def test_directory_without_manifest_skipped(self):
        write_plugin(self.plugins_dir, 'orphan', SIMPLE_TOOL_PLUGIN)
        self.pm.load()
        self.assertIsNone(self.pm.get('orphan'))

    def test_invalid_manifest_is_error(self):
        pdir = self.plugins_dir / 'broken'
        pdir.mkdir(parents=True, exist_ok=True)
        with open(pdir / 'manifest.json', 'w') as f:
            f.write('{not valid json')
        with open(pdir / 'plugin.py', 'w') as f:
            f.write('def register_tools(registry):\n    pass\n')
        self.pm.load()
        info = self.pm.get('broken')
        self.assertEqual(info.status, 'error')
        self.assertIn('invalid manifest', info.error)

    def test_local_wins_over_global(self):
        gdir = self.root / 'global_plugins'
        gdir.mkdir()
        write_plugin(gdir, 'hello', SIMPLE_TOOL_PLUGIN,
                     {'name': 'hello', 'version': '0.1.0'})
        write_plugin(self.plugins_dir, 'hello', SIMPLE_TOOL_PLUGIN,
                     {'name': 'hello', 'version': '9.9.9'})
        self.pm.global_dir = gdir
        self.pm.load()
        info = self.pm.get('hello')
        self.assertEqual(info.version, '9.9.9')
        self.assertFalse(info.global_)

    def test_src_entry_with_sibling_import(self):
        pdir = self.plugins_dir / 'srclay'
        src = pdir / 'src'
        src.mkdir(parents=True)
        with open(pdir / 'manifest.json', 'w') as f:
            json.dump({'name': 'srclay', 'entry': 'src/plugin.py'}, f)
        (src / 'helper.py').write_text('VALUE = "from-helper"\n')
        (src / 'plugin.py').write_text(
            'import helper\n'
            'def register_tools(registry):\n'
            '    @registry.register("peek", "Peek", '
            '{"type": "object", "properties": {}})\n'
            '    def peek():\n'
            '        return helper.VALUE\n')
        self.pm.load()
        info = self.pm.get('srclay')
        self.assertEqual(info.status, 'loaded')
        reg = ToolRegistry()
        self.pm.register_tools(reg)
        self.assertEqual(reg.execute('peek', {}), 'from-helper')


class TestCompatibility(PluginTestBase):

    def test_polyglav_version_skip(self):
        write_plugin(self.plugins_dir, 'old', 'def register_tools(registry):\n    pass\n',
                     {'name': 'old', 'polyglav_version': '>=99.0.0'})
        self.pm.load()
        info = self.pm.get('old')
        self.assertEqual(info.status, 'incompatible')
        self.assertIn('99.0.0', info.error)
        reg = ToolRegistry()
        self.pm.register_tools(reg)
        self.assertNotIn('old', reg.names())

    def test_polyglav_version_ok(self):
        write_plugin(self.plugins_dir, 'cur', 'def register_tools(registry):\n    pass\n',
                     {'name': 'cur', 'polyglav_version': '>=0.1.0,<99.0.0'})
        self.pm.load()
        self.assertEqual(self.pm.get('cur').status, 'loaded')

    def test_python_version_skip(self):
        write_plugin(self.plugins_dir, 'py', 'def register_tools(registry):\n    pass\n',
                     {'name': 'py', 'python': '>=99.0'})
        self.pm.load()
        self.assertEqual(self.pm.get('py').status, 'incompatible')


class TestPluginsConfig(PluginTestBase):

    def test_allowlist(self):
        write_plugin(self.plugins_dir, 'a', SIMPLE_TOOL_PLUGIN, {'name': 'a'})
        write_plugin(self.plugins_dir, 'b', SIMPLE_TOOL_PLUGIN, {'name': 'b'})
        pm = self.make_pm({'plugins': ['b']})
        pm.load()
        self.assertEqual(pm.get('a').status, 'disabled')
        self.assertEqual(pm.get('b').status, 'loaded')

    def test_empty_means_all(self):
        write_plugin(self.plugins_dir, 'a', SIMPLE_TOOL_PLUGIN, {'name': 'a'})
        write_plugin(self.plugins_dir, 'b', SIMPLE_TOOL_PLUGIN, {'name': 'b'})
        pm = self.make_pm({'plugins': []})
        pm.load()
        self.assertEqual(pm.get('a').status, 'loaded')
        self.assertEqual(pm.get('b').status, 'loaded')


class TestEntryErrors(PluginTestBase):

    def test_entry_raises_is_error(self):
        write_plugin(self.plugins_dir, 'boom', 'raise RuntimeError("kaboom")\n', {'name': 'boom'})
        self.pm.load()
        info = self.pm.get('boom')
        self.assertEqual(info.status, 'error')
        self.assertIn('kaboom', info.error)

    def test_missing_entry_is_error(self):
        pdir = self.plugins_dir / 'nofile'
        pdir.mkdir(parents=True, exist_ok=True)
        with open(pdir / 'manifest.json', 'w') as f:
            json.dump({'name': 'nofile', 'entry': 'nope.py'}, f)
        self.pm.load()
        info = self.pm.get('nofile')
        self.assertEqual(info.status, 'error')
        self.assertIn('nope.py', info.error)

    def test_one_bad_plugin_does_not_break_others(self):
        write_plugin(self.plugins_dir, 'boom', 'raise RuntimeError("kaboom")\n', {'name': 'boom'})
        write_plugin(self.plugins_dir, 'ok', SIMPLE_TOOL_PLUGIN, {'name': 'ok'})
        self.pm.load()
        self.assertEqual(self.pm.get('boom').status, 'error')
        self.assertEqual(self.pm.get('ok').status, 'loaded')


class TestRegistration(PluginTestBase):

    def test_register_tools_hook(self):
        write_plugin(self.plugins_dir, 'hello', SIMPLE_TOOL_PLUGIN, SIMPLE_MANIFEST)
        self.pm.load()
        reg = ToolRegistry()
        self.pm.register_tools(reg)
        self.assertIn('hello', reg.names())
        self.assertEqual(reg.execute('hello', {}), 'hello from plugin')

    def test_register_providers_hook(self):
        write_plugin(self.plugins_dir, 'prov', PROVIDER_PLUGIN, {'name': 'prov'})
        self.pm.load()
        classes = self.pm.provider_classes()
        self.assertIn('myprovider', classes)
        self.assertEqual(classes['myprovider'].DEFAULT_MODEL, 'my-model')

    def test_register_services_hook(self):
        write_plugin(self.plugins_dir, 'svc', SERVICE_PLUGIN, {'name': 'svc'})
        self.pm.load()
        self.assertEqual(self.pm.service('greet')(), 'hello from service')
        self.assertIsNone(self.pm.service('nonexistent'))

    def test_register_commands_hook(self):
        write_plugin(self.plugins_dir, 'cmd', COMMAND_PLUGIN, {'name': 'cmd'})
        self.pm.load()
        reg = CommandRegistry(object())
        self.pm.register_commands(reg)
        self.assertIn('frobnicate', reg.commands)

    def _type_registry(self):
        from polyglav.roles import RoleRegistry
        return RoleRegistry(
            global_dir=self.root,
            local_path=self.root / '.polyglav' / 'roles.json')

    def test_register_roles_hook(self):
        write_plugin(self.plugins_dir, 'pers', TYPE_PLUGIN, {'name': 'pers'})
        self.pm.load()
        reg = self._type_registry()
        self.pm.register_roles(reg)
        p = reg.find('helper')
        self.assertIsNotNone(p)
        self.assertEqual(p.system_prompt, 'Helper type from a plugin')
        self.assertEqual(reg.origin('helper'), 'plugin')

    def test_register_roles_hook_failure_marks_error(self):
        write_plugin(self.plugins_dir, 'boom', TYPE_FAIL_PLUGIN, {'name': 'boom'})
        self.pm.load()
        reg = self._type_registry()
        self.pm.register_roles(reg)
        info = self.pm.get('boom')
        self.assertEqual(info.status, 'error')
        self.assertIn('register_roles failed', info.error)

    def test_register_teams_hook(self):
        write_plugin(self.plugins_dir, 'team', TEAM_PLUGIN, {'name': 'team'})
        self.pm.load()
        from polyglav.teams import TeamRegistry
        reg = TeamRegistry(global_dir=self.root,
                           local_path=self.root / '.polyglav' / 'teams.json')
        self.pm.register_teams(reg)
        t = reg.find('sme')
        self.assertIsNotNone(t)
        self.assertEqual([s.role for s in t.stages],
                         ['researcher', 'writer'])
        self.assertEqual(t.stages[0].task_hint, 'gather')
        self.assertEqual(reg.origin('sme'), 'plugin')

    def test_register_skills_hook(self):
        write_plugin(self.plugins_dir, 'skill', SKILL_PLUGIN, {'name': 'skill'})
        self.pm.load()
        from polyglav.skills import SkillRegistry
        reg = SkillRegistry(global_dir=self.root,
                            local_dir=self.root / '.polyglav' / 'skills')
        self.pm.register_skills(reg)
        s = reg.find('writers')
        self.assertIsNotNone(s)
        self.assertEqual(s.description,
                         'Team writing skills')
        self.assertIn('clean prose', s.content)
        self.assertEqual(reg.origin('writers'), 'plugin')

    def test_teams_and_skills_hook_failure_marks_error(self):
        write_plugin(self.plugins_dir, 'boom',
                     'def register_teams(teams):\n    raise RuntimeError("t")\n'
                     'def register_skills(skills):\n    raise RuntimeError("s")\n',
                     {'name': 'boom'})
        self.pm.load()
        self.pm.register_teams({})
        self.assertEqual(self.pm.get('boom').status, 'error')
        self.assertIn('register_teams failed', self.pm.get('boom').error)
        self.pm.load()
        self.pm.register_skills({})
        self.assertIn('register_skills failed', self.pm.get('boom').error)

    def test_register_fixtures_hook(self):
        write_plugin(self.plugins_dir, 'eval', FIXTURE_PLUGIN, {'name': 'eval'})
        self.pm.load()
        from polyglav.eval import discover_fixtures
        fixtures = discover_fixtures(plugin_manager=self.pm)
        self.assertIn('read-foo', fixtures)
        self.assertEqual(fixtures['read-foo'].expected, ['file_read'])
        self.assertEqual(fixtures['list-dir'].task, 'List the dir')

    def test_fixtures_hook_failure_marks_error(self):
        write_plugin(self.plugins_dir, 'boom',
                     'def register_fixtures(fixtures):\n    raise RuntimeError("f")\n',
                     {'name': 'boom'})
        self.pm.load()
        self.pm.register_fixtures({})
        self.assertEqual(self.pm.get('boom').status, 'error')
        self.assertIn('register_fixtures failed', self.pm.get('boom').error)

    def test_lazy_dep_error_surfaces_pip_guidance(self):
        write_plugin(self.plugins_dir, 'lazy', LAZY_DEP_PLUGIN, {'name': 'lazy'})
        self.pm.load()
        self.assertEqual(self.pm.get('lazy').status, 'loaded')
        reg = ToolRegistry()
        self.pm.register_tools(reg)
        out = reg.execute('uses_dep', {})
        self.assertIn('pip install polyglav_definitely_missing_pkg', out)

    def test_dep_status_reports_missing(self):
        write_plugin(self.plugins_dir, 'hello', SIMPLE_TOOL_PLUGIN,
                     {'name': 'hello', 'requires': ['polyglav_definitely_missing_pkg']})
        self.pm.load()
        status = self.pm.dep_status(self.pm.get('hello'))
        self.assertEqual(status, [('polyglav_definitely_missing_pkg', False)])

    def test_plugin_tool_respects_tool_policy(self):
        write_plugin(self.plugins_dir, 'sec', POLICY_PLUGIN, {'name': 'sec'})
        self.pm.load()
        reg = ToolRegistry()
        self.pm.register_tools(reg)
        self.assertIn('confidential', reg.names())
        policy = ToolPolicy({'read': 'allow'}, deny=['confidential'])
        allowed = {n for n in reg.names() if policy.allowed(n)}
        self.assertNotIn('confidential', allowed)


class TestInstallUpdateUninstall(PluginTestBase):

    def _make_source(self):
        src = self.root / 'src_plugin'
        src.mkdir()
        with open(src / 'manifest.json', 'w') as f:
            json.dump({'name': 'hello', 'version': '0.5.0'}, f)
        with open(src / 'plugin.py', 'w') as f:
            f.write(SIMPLE_TOOL_PLUGIN)
        return src

    def test_install_from_path(self):
        src = self._make_source()
        info = self.pm.install(str(src))
        self.assertEqual(info.name, 'hello')
        installed = self.pm.get('hello')
        self.assertIsNotNone(installed)
        self.assertEqual(installed.version, '0.5.0')
        self.assertEqual(installed.status, 'loaded')
        self.assertTrue((self.plugins_dir / 'hello' / 'manifest.json').exists())
        manifest = json.loads((self.plugins_dir / 'hello' / 'manifest.json').read_text())
        self.assertEqual(manifest['source'], str(src))

    def test_install_missing_source_raises(self):
        with self.assertRaises(PluginError):
            self.pm.install('/nonexistent/plugin/path')

    def test_update_from_path(self):
        src = self._make_source()
        self.pm.install(str(src))
        with open(src / 'plugin.py', 'w') as f:
            f.write(SIMPLE_TOOL_PLUGIN + '\n# v2\n')
        info = self.pm.update('hello')
        self.assertEqual(info.version, '0.5.0')
        content = (self.plugins_dir / 'hello' / 'plugin.py').read_text()
        self.assertIn('# v2', content)

    def test_update_unknown_raises(self):
        with self.assertRaises(PluginError):
            self.pm.update('nope')

    def test_uninstall(self):
        src = self._make_source()
        self.pm.install(str(src))
        self.pm.uninstall('hello')
        self.assertFalse((self.plugins_dir / 'hello').exists())
        self.assertIsNone(self.pm.get('hello'))


class TestEngineIntegration(PluginTestBase):

    def test_engine_loads_plugin_tools(self):
        write_plugin(self.plugins_dir, 'hello', SIMPLE_TOOL_PLUGIN, SIMPLE_MANIFEST)
        from polyglav.engine import Engine
        engine = Engine(self.config, ui=NullUI())
        engine._init_tooling()
        self.assertIn('hello', engine._tool_registry.names())

    def test_engine_registers_plugin_commands(self):
        write_plugin(self.plugins_dir, 'cmd', COMMAND_PLUGIN, {'name': 'cmd'})
        from polyglav.engine import Engine
        engine = Engine(self.config, ui=NullUI())
        self.assertIn('frobnicate', engine.registry.commands)

    def test_plugins_slash_command_lists(self):
        write_plugin(self.plugins_dir, 'hello', SIMPLE_TOOL_PLUGIN, SIMPLE_MANIFEST)
        from polyglav.engine import Engine
        engine = Engine(self.config, ui=NullUI())
        buf = io.StringIO()
        with redirect_stdout(buf):
            engine.registry.dispatch('/plugins')
        self.assertIn('hello', buf.getvalue())

    def test_engine_types_include_plugin_contributions(self):
        write_plugin(self.plugins_dir, 'pers', TYPE_PLUGIN, {'name': 'pers'})
        from polyglav.engine import Engine
        engine = Engine(self.config, ui=NullUI())
        p = engine.roles.find('helper')
        self.assertIsNotNone(p)
        self.assertEqual(p.system_prompt, 'Helper type from a plugin')
        self.assertEqual(engine.roles.origin('helper'), 'plugin')

    def test_engine_teams_include_plugin_contributions(self):
        write_plugin(self.plugins_dir, 'team', TEAM_PLUGIN, {'name': 'team'})
        from polyglav.engine import Engine
        engine = Engine(self.config, ui=NullUI())
        t = engine.teams.find('sme')
        self.assertIsNotNone(t)
        self.assertEqual([s.role for s in t.stages],
                         ['researcher', 'writer'])
        self.assertEqual(engine.teams.origin('sme'), 'plugin')

    def test_engine_skills_include_plugin_contributions(self):
        write_plugin(self.plugins_dir, 'skill', SKILL_PLUGIN, {'name': 'skill'})
        from polyglav.engine import Engine
        engine = Engine(self.config, ui=NullUI())
        s = engine.skills.find('writers')
        self.assertIsNotNone(s)
        self.assertIn('clean prose', s.content)
        self.assertEqual(engine.skills.origin('writers'), 'plugin')


class TestPluginsTestCommand(PluginTestBase):

    def _write_test_plugin(self, suite_body='        self.assertTrue(True)\n'):
        write_plugin(self.plugins_dir, 'hello', SIMPLE_TOOL_PLUGIN, SIMPLE_MANIFEST)
        tdir = self.plugins_dir / 'hello' / 'tests'
        tdir.mkdir(exist_ok=True)
        (tdir / 'test_hello.py').write_text(
            'import unittest\n'
            'class TestHello(unittest.TestCase):\n'
            '    def test_ok(self):\n'
            f'{suite_body}'
        )

    def _cmd(self, **kw):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from types import SimpleNamespace
        from polyglav.cli import cmd_plugins
        args = dict(action='test', path=str(self.root), verbose=False)
        args.update(kw)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            return cmd_plugins(SimpleNamespace(**args))

    def test_load_plugin_test_suite(self):
        from polyglav.plugins.manager import load_plugin_test_suite
        self._write_test_plugin()
        suite = load_plugin_test_suite(self.plugins_dir / 'hello')
        self.assertEqual(suite.countTestCases(), 1)

    def test_cli_test_runs_named(self):
        self._write_test_plugin()
        self.assertEqual(self._cmd(name='hello'), 0)

    def test_cli_test_all_runs_each_plugin(self):
        self._write_test_plugin()
        write_plugin(self.plugins_dir, 'other', SIMPLE_TOOL_PLUGIN, {'name': 'other'})
        self.assertEqual(self._cmd(name=None), 0)

    def test_cli_test_unknown_returns_1(self):
        self.assertEqual(self._cmd(name='nope'), 1)

    def test_cli_test_no_tests_returns_1(self):
        write_plugin(self.plugins_dir, 'hello', SIMPLE_TOOL_PLUGIN, SIMPLE_MANIFEST)
        self.assertEqual(self._cmd(name='hello'), 1)

    def test_cli_test_failing_suite_returns_1(self):
        self._write_test_plugin('        self.assertTrue(False)\n')
        self.assertEqual(self._cmd(name='hello'), 1)


if __name__ == '__main__':
    unittest.main()
