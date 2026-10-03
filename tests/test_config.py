import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from polyglav.config import Config, DEFAULT_CONFIG
from polyglav.cli import cmd_config
from polyglav.tools.policy import ToolPolicy


class _IsolatedConfigBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir()
        self._prev_global_dir = Config.GLOBAL_DIR
        Config.GLOBAL_DIR = self.home
        self.project = Path(self.tmp.name) / 'project'
        (self.project / '.polyglav').mkdir(parents=True)

    def tearDown(self):
        Config.GLOBAL_DIR = self._prev_global_dir
        self.tmp.cleanup()

    @property
    def local_path(self):
        return self.project / '.polyglav' / 'config.json'

    @property
    def global_path(self):
        return self.home / '.config' / 'polyglav' / 'config.json'

    def local(self):
        if not self.local_path.exists():
            return {}
        return json.loads(self.local_path.read_text())

    def global_(self):
        if not self.global_path.exists():
            return {}
        return json.loads(self.global_path.read_text())


class TestConfigScopes(_IsolatedConfigBase):

    def test_set_default_writes_local_only(self):
        c = Config(path=str(self.project))
        c.set('temperature', 0.3)
        self.assertEqual(self.local(), {'temperature': 0.3})
        self.assertFalse(self.global_path.exists())
        self.assertEqual(c.get('temperature'), 0.3)

    def test_set_global_writes_global_not_local(self):
        c = Config(path=str(self.project))
        c.set('max_tokens', 0, scope='global')
        self.assertEqual(self.global_(), {'max_tokens': 0})
        self.assertFalse(self.local_path.exists())
        self.assertEqual(c.get('max_tokens'), 0)

    def test_local_holds_only_local_selection(self):
        c = Config(path=str(self.project))
        c.set('max_tokens', 0, scope='global')
        c.set('model', 'local-model')
        self.assertEqual(self.local(), {'model': 'local-model'})

    def test_set_global_does_not_shadow_local(self):
        c = Config(path=str(self.project))
        c.set('model', 'local-model')
        c.set('model', 'global-model', scope='global')
        self.assertEqual(c.get('model'), 'local-model')
        self.assertEqual(self.global_()['model'], 'global-model')
        self.assertEqual(self.local()['model'], 'local-model')

    def test_set_global_empty_local_value_does_not_shadow(self):
        c = Config(path=str(self.project))
        c.set('max_tokens', '', scope='local')
        c.set('max_tokens', 4096, scope='global')
        self.assertEqual(c.get('max_tokens'), 4096)

    def test_unset_restores_global_fallback(self):
        c = Config(path=str(self.project))
        c.set('model', 'local-model')
        c.set('model', 'global-model', scope='global')
        c.unset('model')
        self.assertNotIn('model', self.local())
        self.assertEqual(c.get('model'), 'global-model')

    def test_unset_restores_default(self):
        c = Config(path=str(self.project))
        c.set('max_tokens', 2048)
        c.unset('max_tokens')
        self.assertEqual(c.get('max_tokens'), DEFAULT_CONFIG['max_tokens'])
        self.assertNotIn('max_tokens', self.local())

    def test_unset_global_keeps_local(self):
        c = Config(path=str(self.project))
        c.set('model', 'local-model')
        c.set('model', 'global-model', scope='global')
        c.unset('model', scope='global')
        self.assertEqual(c.get('model'), 'local-model')

    def test_apply_is_in_memory_only(self):
        c = Config(path=str(self.project))
        c.apply('temperature', 0.5)
        self.assertEqual(c.get('temperature'), 0.5)
        self.assertFalse(self.local_path.exists())
        self.assertFalse(self.global_path.exists())

    def test_apply_does_not_survive_reload(self):
        c = Config(path=str(self.project))
        c.apply('temperature', 0.5)
        c2 = Config(path=str(self.project))
        self.assertEqual(c2.get('temperature'),
                         DEFAULT_CONFIG['temperature'])

    def test_tool_result_cap_defaults(self):
        c = Config(path=str(self.project))
        self.assertEqual(c.get('tool_max_result_chars'), 100000)
        self.assertEqual(c.get('list_dir_max_entries'), 200)
        self.assertEqual(DEFAULT_CONFIG['tool_max_result_chars'], 100000)
        self.assertEqual(DEFAULT_CONFIG['list_dir_max_entries'], 200)

    def test_origin(self):
        c = Config(path=str(self.project))
        self.assertEqual(c.origin('temperature'), 'default')
        c.set('model', 'global-model', scope='global')
        self.assertEqual(c.origin('model'), 'global')
        c.set('model', 'local-model')
        self.assertEqual(c.origin('model'), 'local')

    def test_load_merges_global_then_local(self):
        c = Config(path=str(self.project))
        c.set('temperature', 0.2, scope='global')
        c.set('temperature', 0.9)
        c2 = Config(path=str(self.project))
        self.assertEqual(c2.get('temperature'), 0.9)


class TestConfigMerge(_IsolatedConfigBase):

    def write_local(self, data):
        self.local_path.write_text(json.dumps(data))

    def write_global(self, data):
        self.global_path.parent.mkdir(parents=True, exist_ok=True)
        self.global_path.write_text(json.dumps(data))

    def test_vcs_category_defaults_to_ask(self):
        self.assertEqual(DEFAULT_CONFIG['tool_permission']['vcs'], 'ask')
        c = Config(path=str(self.project))
        self.assertEqual(c.get('tool_permission')['vcs'], 'ask')

    def test_local_tool_permission_keeps_default_categories(self):
        self.write_local({'tool_permission': {
            'bash': 'allow',
            'bash_allow': ['git'],
            'delegate': 'allow',
            'edit': 'allow',
            'list': 'allow',
            'read': 'allow',
            'web': 'allow',
        }})
        c = Config(path=str(self.project))
        permissions = c.get('tool_permission')
        self.assertEqual(permissions['ask'], 'allow')
        self.assertEqual(permissions['catalog'], 'allow')
        self.assertEqual(permissions['handoff'], 'allow')
        self.assertEqual(permissions['delegate'], 'allow')
        self.assertEqual(permissions['call'], 'allow')
        self.assertEqual(permissions['mcp'], 'ask')
        self.assertEqual(permissions['bash'], 'allow')
        self.assertEqual(permissions['bash_allow'], ['git'])

    def test_local_tool_permission_does_not_gate_default_categories(self):
        self.write_local({'tool_permission': {'bash': 'allow'}})
        c = Config(path=str(self.project))
        policy = ToolPolicy(c.get('tool_permission'))
        self.assertEqual(policy.action('ask', 'ask'), 'allow')
        self.assertEqual(policy.action('catalog', 'catalog'), 'allow')
        self.assertEqual(policy.action('handoff', 'handoff'), 'allow')
        self.assertEqual(policy.action('delegate', 'delegate'), 'allow')

    def test_partial_mode_keeps_default_keys(self):
        self.write_local({
            'modes': {'read': {'tool_permission': {'bash': 'allow'}}}})
        c = Config(path=str(self.project))
        modes = c.get('modes')
        self.assertEqual(modes['read']['tool_permission'], {'bash': 'allow'})
        self.assertEqual(modes['read']['system_prompt'],
                         DEFAULT_CONFIG['modes']['read']['system_prompt'])
        self.assertEqual(modes['write'], DEFAULT_CONFIG['modes']['write'])

    def test_partial_ask_policy_keeps_default_keys(self):
        self.write_local({'ask_policy': {'direction': 'lead'}})
        c = Config(path=str(self.project))
        self.assertEqual(c.get('ask_policy'),
                         {'permission': 'auto', 'direction': 'lead'})

    def test_partial_memory_scopes_keeps_default_keys(self):
        self.write_local({'memory_scopes': {'job': False}})
        c = Config(path=str(self.project))
        self.assertEqual(c.get('memory_scopes'),
                         {'role': True, 'team': True, 'job': False})

    def test_partial_grant_permission_merges_layers(self):
        self.write_global({'grant_permission': {'bash': ['git']}})
        self.write_local({'grant_permission': {'edit': ['file_write']}})
        c = Config(path=str(self.project))
        self.assertEqual(c.get('grant_permission'), {
            'bash': ['git'],
            'edit': ['file_write'],
        })

    def test_global_partial_override_merges_with_default(self):
        self.write_global({'tool_permission': {'bash': 'allow'}})
        c = Config(path=str(self.project))
        permissions = c.get('tool_permission')
        self.assertEqual(permissions['bash'], 'allow')
        self.assertEqual(permissions['edit'],
                         DEFAULT_CONFIG['tool_permission']['edit'])
        self.assertEqual(permissions['mcp'], 'ask')

    def test_local_partial_override_merges_over_global(self):
        self.write_global({
            'tool_permission': {'bash': 'allow', 'web': 'deny'}})
        self.write_local({'tool_permission': {'web': 'allow'}})
        c = Config(path=str(self.project))
        permissions = c.get('tool_permission')
        self.assertEqual(permissions['bash'], 'allow')
        self.assertEqual(permissions['web'], 'allow')
        self.assertEqual(permissions['read'], 'allow')
        self.assertEqual(permissions['mcp'], 'ask')

    def test_lists_and_scalars_replace(self):
        self.write_local({'noise_tools': ['web_fetch'],
                          'footer_tokens': ['tokens'],
                          'temperature': 0.1})
        c = Config(path=str(self.project))
        self.assertEqual(c.get('noise_tools'), ['web_fetch'])
        self.assertEqual(c.get('footer_tokens'), ['tokens'])
        self.assertEqual(c.get('temperature'), 0.1)

    def test_reload_keeps_nested_defaults(self):
        self.write_local({'tool_permission': {'bash': 'allow'}})
        c = Config(path=str(self.project))
        self.write_local({'tool_permission': {'web': 'deny'}})
        c.reload()
        permissions = c.get('tool_permission')
        self.assertEqual(permissions['web'], 'deny')
        self.assertEqual(permissions['bash'], 'ask')
        self.assertEqual(permissions['mcp'], 'ask')

    def test_unset_restores_unmentioned_default_keys(self):
        self.write_local({'tool_permission': {'bash': 'deny', 'read': 'deny'}})
        c = Config(path=str(self.project))
        self.assertEqual(c.get('tool_permission')['bash'], 'deny')
        c.unset('tool_permission')
        self.assertNotIn('tool_permission', self.local())
        self.assertEqual(c.get('tool_permission'),
                         DEFAULT_CONFIG['tool_permission'])

    def test_unset_local_falls_back_to_merged_global(self):
        self.write_global({'tool_permission': {'bash': 'allow'}})
        self.write_local({'tool_permission': {'web': 'deny'}})
        c = Config(path=str(self.project))
        self.assertEqual(c.get('tool_permission')['web'], 'deny')
        c.unset('tool_permission')
        permissions = c.get('tool_permission')
        self.assertEqual(permissions['bash'], 'allow')
        self.assertEqual(permissions['web'], 'allow')
        self.assertEqual(permissions['mcp'], 'ask')

    def test_unset_global_keeps_local_partial_override(self):
        self.write_global(
            {'tool_permission': {'bash': 'allow', 'web': 'deny'}})
        self.write_local({'tool_permission': {'web': 'allow'}})
        c = Config(path=str(self.project))
        c.unset('tool_permission', scope='global')
        permissions = c.get('tool_permission')
        self.assertEqual(permissions['web'], 'allow')
        self.assertEqual(permissions['bash'], 'ask')
        self.assertEqual(permissions['mcp'], 'ask')
        self.assertEqual(self.local()['tool_permission'], {'web': 'allow'})

    def test_unset_key_in_no_layer_removes_it(self):
        c = Config(path=str(self.project))
        c.apply('custom_key', 'value')
        self.assertEqual(c.get('custom_key'), 'value')
        c.unset('custom_key')
        self.assertIsNone(c.get('custom_key'))
        self.assertNotIn('custom_key', self.local())

    def test_partial_mode_permission_keeps_spec_isolated(self):
        self.write_local({
            'modes': {'read': {'tool_permission': {'edit': 'allow'}}}})
        c = Config(path=str(self.project))
        permissions = c.get('modes')['read']['tool_permission']
        self.assertEqual(permissions['edit'], 'allow')
        self.assertNotIn('bash', permissions)

    def test_new_mode_keeps_default_modes(self):
        self.write_local({'modes': {'custom': {'system_prompt': 'hi'}}})
        c = Config(path=str(self.project))
        modes = c.get('modes')
        self.assertEqual(modes['custom'], {'system_prompt': 'hi'})
        self.assertEqual(modes['write'], DEFAULT_CONFIG['modes']['write'])
        self.assertEqual(modes['read']['system_prompt'],
                         DEFAULT_CONFIG['modes']['read']['system_prompt'])

    def test_nested_list_value_replaces(self):
        self.write_global({'grant_permission': {'bash': ['git', 'pytest']}})
        self.write_local({'grant_permission': {'bash': ['git']}})
        c = Config(path=str(self.project))
        self.assertEqual(c.get('grant_permission')['bash'], ['git'])

    def test_local_plugins_list_replaces_default(self):
        self.write_local({'plugins': ['polyglav-core-web']})
        c = Config(path=str(self.project))
        plugins = c.get('plugins')
        self.assertNotIn('polyglav-core-fs', plugins)
        self.assertNotIn('polyglav-core-git', plugins)
        self.assertIn('polyglav-core-web', plugins)

    def test_non_dict_values_replace_objects(self):
        self.write_local({'ask_policy': 'off', 'model': {'name': 'x'}})
        c = Config(path=str(self.project))
        self.assertEqual(c.get('ask_policy'), 'off')
        self.assertEqual(c.get('model'), {'name': 'x'})

    def test_origin_stays_top_level(self):
        self.write_local({'tool_permission': {'bash': 'allow'}})
        c = Config(path=str(self.project))
        self.assertEqual(c.origin('tool_permission'), 'local')
        self.assertEqual(c.origin('ask_policy'), 'default')

    def test_load_does_not_mutate_defaults(self):
        self.write_local({'tool_permission': {'bash': 'allow'}})
        c = Config(path=str(self.project))
        self.assertIsNot(c.data['tool_permission'],
                         DEFAULT_CONFIG['tool_permission'])
        c.data['tool_permission']['bash'] = 'deny'
        self.assertEqual(DEFAULT_CONFIG['tool_permission']['bash'], 'ask')
        c.set('temperature', 0.3)
        self.assertEqual(self.local()['tool_permission']['bash'], 'allow')
        fresh = Config(path=str(self.project))
        self.assertEqual(fresh.get('tool_permission')['bash'], 'allow')


class TestConfigCli(_IsolatedConfigBase):

    def _args(self, **kw):
        base = dict(path=str(self.project), global_=False, action=None,
                    key=None, value=None, show_origin=False)
        base.update(kw)
        return SimpleNamespace(**base)

    def _run(self, args):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            rc = cmd_config(args)
        return rc, out.getvalue()

    def test_get_single_key(self):
        c = Config(path=str(self.project))
        c.set('temperature', 0.3)
        rc, out = self._run(self._args(action='get', key='temperature'))
        self.assertEqual(rc, 0)
        self.assertIn('temperature = 0.3', out)

    def test_get_show_origin(self):
        c = Config(path=str(self.project))
        c.set('model', 'local-model')
        rc, out = self._run(self._args(action='get', key='model',
                                       show_origin=True))
        self.assertIn('(local)', out)

    def test_set_local(self):
        rc, out = self._run(self._args(
            action='set', key='temperature', value='0.3'))
        self.assertEqual(rc, 0)
        self.assertEqual(self.local()['temperature'], 0.3)
        self.assertIn('saved to local config', out)

    def test_set_global(self):
        rc, _ = self._run(self._args(
            action='set', key='max_tokens', value='0', global_=True))
        self.assertEqual(rc, 0)
        self.assertEqual(self.global_()['max_tokens'], 0)
        self.assertEqual(self.local(), {})

    def test_set_json_value(self):
        rc, _ = self._run(self._args(
            action='set', key='tools.deny', value='["run_command"]'))
        self.assertEqual(rc, 0)
        self.assertEqual(self.local()['tools.deny'], ['run_command'])

    def test_set_requires_value(self):
        rc, _ = self._run(self._args(action='set', key='temperature'))
        self.assertEqual(rc, 1)
        self.assertFalse(self.local_path.exists())

    def test_set_api_key_is_a_normal_key(self):
        rc, _ = self._run(self._args(action='set', key='api_key',
                                     value='cli-secret'))
        self.assertEqual(rc, 0)
        self.assertEqual(self.local()['api_key'], 'cli-secret')
        self.assertNotIn('api_key', self.global_())

    def test_unset_local(self):
        Config(path=str(self.project)).set('max_tokens', 2048)
        rc, _ = self._run(self._args(action='unset', key='max_tokens'))
        self.assertEqual(rc, 0)
        self.assertNotIn('max_tokens', self.local())
        fresh = Config(path=str(self.project))
        self.assertEqual(fresh.get('max_tokens'),
                         DEFAULT_CONFIG['max_tokens'])

    def test_reload_re_reads_disk(self):
        self.local_path.write_text('{"max_tokens": 4096}')
        rc, out = self._run(self._args(action='reload'))
        self.assertEqual(rc, 0)
        self.assertIn('Config reloaded from disk', out)
        self.assertEqual(Config(path=str(self.project)).get('max_tokens'), 4096)


if __name__ == '__main__':
    unittest.main()