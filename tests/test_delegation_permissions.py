import unittest
from unittest.mock import patch

from polyglav.modes import merge_policy
from polyglav.tools.policy import ToolPolicy
from polyglav.roles import (Role, clamp_action, resolve_grant_ceiling,
                          resolve_permissions)
from polyglav.tools.ask import _permission_scope

from tests.helpers import make_chat
from tests.test_engine import make_engine


class TestClampHelpers(unittest.TestCase):

    def test_clamp_action_orders_deny_ask_allow(self):
        self.assertEqual(clamp_action('allow', 'allow'), 'allow')
        self.assertEqual(clamp_action('allow', 'ask'), 'ask')
        self.assertEqual(clamp_action('allow', 'deny'), 'deny')
        self.assertEqual(clamp_action('ask', 'allow'), 'ask')
        self.assertEqual(clamp_action('deny', 'allow'), 'deny')

    def test_clamp_action_passes_through_non_actions(self):
        self.assertEqual(clamp_action([], 'allow'), [])
        self.assertEqual(clamp_action('allow', []), 'allow')

    def test_resolve_permissions_narrows_but_never_widens(self):
        parent_self = {'read': 'allow', 'edit': 'allow', 'bash': 'deny'}
        out = resolve_permissions(
            parent_self, {}, {'edit': 'deny', 'bash': 'allow'})
        self.assertEqual(out['edit'], 'deny')
        self.assertEqual(out['bash'], 'deny')
        self.assertEqual(out['read'], 'allow')

    def test_resolve_permissions_unknown_category_defaults_to_ask(self):
        out = resolve_permissions({'read': 'allow'}, {}, {'bash': 'allow'})
        self.assertEqual(out['bash'], 'ask')

    def test_resolve_permissions_grant_overlay_widens_cap(self):
        parent_self = {'bash': 'deny'}
        out = resolve_permissions(
            parent_self, {'bash': 'allow'}, {'bash': 'allow'})
        self.assertEqual(out['bash'], 'allow')

    def test_resolve_grant_ceiling_capped_by_parent(self):
        parent_self = {'bash': 'ask', 'edit': 'ask'}
        parent_grant = {'bash': 'ask', 'edit': 'deny'}
        self_perm = {'bash': 'deny', 'edit': 'deny'}
        ceiling = resolve_grant_ceiling(
            parent_self, parent_grant,
            {'bash': 'allow', 'edit': 'allow'}, self_perm)
        self.assertEqual(ceiling['bash'], 'ask')
        self.assertEqual(ceiling['edit'], 'deny')

    def test_resolve_grant_ceiling_defaults_to_self(self):
        ceiling = resolve_grant_ceiling(
            {'bash': 'allow'}, {}, {}, {'bash': 'deny'})
        self.assertEqual(ceiling, {'bash': 'deny'})


class TestPolicyGrants(unittest.TestCase):

    def test_grant_once_is_consumed(self):
        policy = ToolPolicy({'bash': 'deny'})
        self.assertEqual(policy.action('run_command', 'bash'), 'deny')
        policy.grant('run_command', 'bash', scope='once')
        self.assertEqual(policy.action('run_command', 'bash'), 'allow')
        policy.consume('run_command', 'bash')
        self.assertEqual(policy.action('run_command', 'bash'), 'deny')

    def test_grant_always_persists_across_consumption(self):
        policy = ToolPolicy({'bash': 'deny'})
        policy.grant('run_command', 'bash', scope='always')
        policy.consume('run_command', 'bash')
        self.assertEqual(policy.action('run_command', 'bash'), 'allow')

    def test_category_grant_matches_any_tool_in_category(self):
        policy = ToolPolicy({'bash': 'deny'})
        policy.grant('', 'bash', scope='once')
        self.assertEqual(policy.action('run_command', 'bash'), 'allow')
        self.assertEqual(policy.action('other_bash_tool', 'bash'), 'allow')
        self.assertEqual(policy.action('file_read', 'read'), 'ask')

    def test_tool_grant_does_not_match_other_tools(self):
        policy = ToolPolicy({'bash': 'deny'})
        policy.grant('run_command', 'bash', scope='once')
        self.assertEqual(policy.action('run_command', 'bash'), 'allow')
        self.assertEqual(policy.action('other_bash_tool', 'bash'), 'deny')


class TestNoEscalation(unittest.TestCase):

    def _permissions(self, engine):
        engine._init_tooling()
        return merge_policy(engine.config)[0]

    def test_grant_ceiling_read_mode_denies_write(self):
        chat = make_chat()
        try:
            self.assertEqual(chat._grant()['bash'], 'deny')
            self.assertEqual(chat._grant()['edit'], 'deny')
        finally:
            chat._tmp.cleanup()

    def test_grant_ceiling_write_mode_allows_write(self):
        chat = make_chat({'mode': 'write'})
        try:
            self.assertEqual(chat._grant()['bash'], 'allow')
            self.assertEqual(chat._grant()['edit'], 'allow')
            self.assertEqual(chat._grant()['read'], 'allow')
        finally:
            chat._tmp.cleanup()

    def test_role_grant_narrows_write_ceiling(self):
        chat = make_chat({'mode': 'write', 'grant_permission': {'bash': 'ask'}})
        try:
            self.assertEqual(chat._grant()['bash'], 'ask')
            self.assertEqual(chat._grant()['edit'], 'allow')
        finally:
            chat._tmp.cleanup()

    def test_type_cannot_widen_above_grant_ceiling(self):
        chat = make_chat({
            'grant_permission': {'bash': 'deny', 'read': 'allow'},
            'tool_permission': {'ask': 'allow', 'read': 'allow', 'bash': 'deny'},
        })
        try:
            chat.roles.put(Role(name='impl', tool_permission={'bash': 'allow'}),
                           scope='local')
            sub = chat._new_sub_engine('impl')
            self.assertEqual(self._permissions(sub)['bash'], 'deny')
        finally:
            chat._tmp.cleanup()

    def test_type_widens_when_grant_ceiling_allows(self):
        chat = make_chat({'mode': 'write',
                          'grant_permission': {'read': 'allow', 'bash': 'allow'}})
        try:
            chat.roles.put(Role(name='impl', tool_permission={'bash': 'allow'}),
                           scope='local')
            sub = chat._new_sub_engine('impl')
            self.assertEqual(self._permissions(sub)['bash'], 'allow')
        finally:
            chat._tmp.cleanup()

    def test_supervisor_grants_bash_but_cannot_use_it(self):
        chat = make_chat({'mode': 'write',
                          'grant_permission': {'read': 'allow', 'bash': 'allow',
                                               'edit': 'allow'}})
        try:
            chat.roles.put(Role(
                name='supervisor',
                tool_permission={'read': 'allow', 'bash': 'deny', 'edit': 'deny'},
                grant_permission={'read': 'allow', 'bash': 'allow',
                                  'edit': 'allow'}), scope='local')
            chat.roles.put(Role(
                name='impl',
                tool_permission={'read': 'allow', 'bash': 'allow',
                                 'edit': 'allow'}), scope='local')
            sup = chat._new_sub_engine('supervisor')
            self.assertEqual(self._permissions(sup)['bash'], 'deny')
            self.assertEqual(sup._grant()['bash'], 'allow')
            worker = sup._new_sub_engine('impl')
            self.assertEqual(self._permissions(worker)['bash'], 'allow')
        finally:
            chat._tmp.cleanup()

    def test_oneshot_grant_does_not_propagate_to_child(self):
        chat = make_chat({'mode': 'write', 'grant_permission': {'read': 'allow', 'bash': 'allow'}})
        try:
            chat.roles.put(Role(
                name='supervisor',
                tool_permission={'bash': 'deny'},
                grant_permission={'bash': 'allow'}), scope='local')
            chat.roles.put(Role(name='worker', tool_permission={'bash': 'deny'}),
                           scope='local')
            sup = chat._new_sub_engine('supervisor')
            sup._init_tooling()
            sup.grant_permission('bash', 'bash', scope='always', origin='user')
            child = sup._new_sub_engine('worker')
            child._init_tooling()
            self.assertFalse(child._tool_policy.has_grant('run_command', 'bash'))
        finally:
            chat._tmp.cleanup()


class TestAskPermission(unittest.TestCase):

    def _worker(self, chat, ask_policy=None):
        chat.roles.put(Role(
            name='worker',
            tool_permission={'bash': 'deny'},
            ask_policy=ask_policy or {}), scope='local')
        sub = chat._new_sub_engine('worker')
        sub._init_tooling()
        return sub

    def test_auto_route_grants_once_via_lead(self):
        chat = make_chat({'mode': 'write', 'grant_permission': {'read': 'allow', 'bash': 'allow'}})
        try:
            chat.provider.chat_nonstreaming.return_value = {'content': 'yes - needed'}
            sub = self._worker(chat)
            out = sub._run_tool('ask', {
                'question': 'may I run a command?',
                'kind': 'permission', 'permission': 'bash'})
            self.assertIn('[granted]', out)
            grant = sub._tool_policy.grant_for('run_command', 'bash')
            self.assertIsNotNone(grant)
            self.assertEqual(grant['scope'], 'once')
        finally:
            chat._tmp.cleanup()

    def test_auto_route_denies_when_lead_says_no(self):
        chat = make_chat({'mode': 'write', 'grant_permission': {'read': 'allow', 'bash': 'allow'}})
        try:
            chat.provider.chat_nonstreaming.return_value = {'content': 'no'}
            sub = self._worker(chat)
            out = sub._run_tool('ask', {
                'question': 'q', 'kind': 'permission', 'permission': 'bash'})
            self.assertIn('[denied]', out)
            self.assertFalse(sub._tool_policy.has_grant('run_command', 'bash'))
        finally:
            chat._tmp.cleanup()

    def test_auto_route_never_grants_always(self):
        chat = make_chat({'mode': 'write', 'grant_permission': {'read': 'allow', 'bash': 'allow'}})
        try:
            chat.provider.chat_nonstreaming.return_value = {'content': 'yes always'}
            sub = self._worker(chat)
            sub._run_tool('ask', {
                'question': 'q', 'kind': 'permission', 'permission': 'bash'})
            grant = sub._tool_policy.grant_for('run_command', 'bash')
            self.assertEqual(grant['scope'], 'once')
        finally:
            chat._tmp.cleanup()

    def test_category_ask_grants_whole_category(self):
        chat = make_chat({'mode': 'write',
                          'grant_permission': {'read': 'allow', 'edit': 'allow'}})
        try:
            chat.roles.put(Role(name='worker', tool_permission={'edit': 'ask'},
                                ask_policy={'permission': 'caller'}), scope='local')
            sub = chat._new_sub_engine('worker')
            sub._init_tooling()
            chat.provider.chat_nonstreaming.return_value = {'content': 'yes'}
            out = sub._run_tool('ask', {
                'question': 'q', 'kind': 'permission', 'permission': 'edit'})
            self.assertIn('[granted]', out)
            grant = sub._tool_policy.grant_for('file_write', 'edit')
            self.assertIsNotNone(grant)
            self.assertEqual(grant['name'], '')
            target = str(chat.config.local_path.parent.parent / 'notes.txt')
            result = sub._run_tool('file_write', {'path': target, 'content': 'hi'})
            self.assertFalse(result.startswith('Error'))
        finally:
            chat._tmp.cleanup()

    def test_tool_ask_grants_only_that_tool(self):
        chat = make_chat({'mode': 'write',
                          'grant_permission': {'read': 'allow', 'edit': 'allow'}})
        try:
            chat.roles.put(Role(name='worker', tool_permission={'edit': 'ask'},
                                ask_policy={'permission': 'caller'}), scope='local')
            sub = chat._new_sub_engine('worker')
            sub._init_tooling()
            chat.provider.chat_nonstreaming.return_value = {'content': 'yes'}
            out = sub._run_tool('ask', {
                'question': 'q', 'kind': 'permission', 'permission': 'file_write'})
            self.assertIn('[granted]', out)
            grant = sub._tool_policy.grant_for('file_write', 'edit')
            self.assertIsNotNone(grant)
            self.assertEqual(grant['name'], 'file_write')
            self.assertIsNone(sub._tool_policy.grant_for('file_edit', 'edit'))
        finally:
            chat._tmp.cleanup()

    def test_denied_above_ceiling(self):
        chat = make_chat({'mode': 'write',
                          'grant_permission': {'bash': 'deny', 'read': 'allow'}})
        try:
            sub = self._worker(chat)
            out = sub._run_tool('ask', {
                'question': 'q', 'kind': 'permission', 'permission': 'bash'})
            self.assertIn('[denied]', out)
            self.assertIn('ceiling', out)
        finally:
            chat._tmp.cleanup()

    def test_grants_disabled_by_policy(self):
        chat = make_chat({'mode': 'write', 'grant_permission': {'read': 'allow', 'bash': 'allow'}})
        try:
            sub = self._worker(chat, ask_policy={'permission': 'deny'})
            out = sub._run_tool('ask', {
                'question': 'q', 'kind': 'permission', 'permission': 'bash'})
            self.assertIn('[denied]', out)
            self.assertIn('disabled', out)
        finally:
            chat._tmp.cleanup()

    def test_human_route_grants_once(self):
        chat = make_chat({'mode': 'write', 'grant_permission': {'read': 'allow', 'bash': 'allow'}})
        try:
            sub = self._worker(chat, ask_policy={'permission': 'user'})
            with patch('builtins.input', return_value='yes'):
                out = sub._run_tool('ask', {
                    'question': 'q', 'kind': 'permission', 'permission': 'bash'})
            self.assertIn('once', out)
            grant = sub._tool_policy.grant_for('run_command', 'bash')
            self.assertEqual(grant['scope'], 'once')
            sub._tool_policy.consume('run_command', 'bash')
            self.assertFalse(sub._tool_policy.has_grant('run_command', 'bash'))
        finally:
            chat._tmp.cleanup()

    def test_human_route_grants_always_and_reuses(self):
        chat = make_chat({'mode': 'write', 'grant_permission': {'read': 'allow', 'bash': 'allow'}})
        try:
            sub = self._worker(chat, ask_policy={'permission': 'user'})
            with patch('builtins.input', return_value='yes always'):
                out = sub._run_tool('ask', {
                    'question': 'q', 'kind': 'permission', 'permission': 'bash'})
            self.assertIn('always', out)
            sub._tool_policy.consume('run_command', 'bash')
            self.assertTrue(sub._tool_policy.has_grant('run_command', 'bash'))
        finally:
            chat._tmp.cleanup()

    def test_human_route_declined(self):
        chat = make_chat({'mode': 'write', 'grant_permission': {'read': 'allow', 'bash': 'allow'}})
        try:
            sub = self._worker(chat, ask_policy={'permission': 'user'})
            with patch('builtins.input', return_value='no'):
                out = sub._run_tool('ask', {
                    'question': 'q', 'kind': 'permission', 'permission': 'bash'})
            self.assertIn('[denied]', out)
            self.assertFalse(sub._tool_policy.has_grant('run_command', 'bash'))
        finally:
            chat._tmp.cleanup()

    def test_human_route_numbered_approve_grants_once(self):
        chat = make_chat({'mode': 'write', 'grant_permission': {'read': 'allow', 'bash': 'allow'}})
        try:
            sub = self._worker(chat, ask_policy={'permission': 'user'})
            with patch('builtins.input', return_value='1'):
                out = sub._run_tool('ask', {
                    'question': 'q', 'kind': 'permission', 'permission': 'bash'})
            self.assertIn('[granted]', out)
            self.assertIn('once', out)
            self.assertTrue(sub._tool_policy.has_grant('run_command', 'bash'))
        finally:
            chat._tmp.cleanup()

    def test_human_route_numbered_approve_always(self):
        chat = make_chat({'mode': 'write', 'grant_permission': {'read': 'allow', 'bash': 'allow'}})
        try:
            sub = self._worker(chat, ask_policy={'permission': 'user'})
            with patch('builtins.input', return_value='2'):
                out = sub._run_tool('ask', {
                    'question': 'q', 'kind': 'permission', 'permission': 'bash'})
            self.assertIn('[granted]', out)
            self.assertIn('always', out)
        finally:
            chat._tmp.cleanup()

    def test_human_route_numbered_deny(self):
        chat = make_chat({'mode': 'write', 'grant_permission': {'read': 'allow', 'bash': 'allow'}})
        try:
            sub = self._worker(chat, ask_policy={'permission': 'user'})
            with patch('builtins.input', return_value='3'):
                out = sub._run_tool('ask', {
                    'question': 'q', 'kind': 'permission', 'permission': 'bash'})
            self.assertIn('[denied]', out)
            self.assertFalse(sub._tool_policy.has_grant('run_command', 'bash'))
        finally:
            chat._tmp.cleanup()

    def test_human_route_approve_phrase_grants(self):
        chat = make_chat({'mode': 'write', 'grant_permission': {'read': 'allow', 'bash': 'allow'}})
        try:
            sub = self._worker(chat, ask_policy={'permission': 'user'})
            with patch('builtins.input', return_value='Approve bash for this run'):
                out = sub._run_tool('ask', {
                    'question': 'q', 'kind': 'permission', 'permission': 'bash'})
            self.assertIn('[granted]', out)
        finally:
            chat._tmp.cleanup()

    def test_direction_ask_defaults_to_caller(self):
        chat = make_chat()
        try:
            sub = self._worker(chat)
            chat.provider.chat_nonstreaming.return_value = {
                'content': 'caller answer'}
            out = sub._run_tool('ask', {'question': 'which option?'})
            self.assertEqual(out, 'caller answer')
            chat.provider.chat_nonstreaming.assert_called_once()
        finally:
            chat._tmp.cleanup()

    def test_direction_ask_policy_user_prompts(self):
        chat = make_chat()
        try:
            sub = self._worker(chat, ask_policy={'direction': 'user'})
            with patch('builtins.input', return_value='user answer'):
                out = sub._run_tool('ask', {'question': 'which option?'})
            self.assertEqual(out, 'user answer')
            chat.provider.chat_nonstreaming.assert_not_called()
        finally:
            chat._tmp.cleanup()

    def test_direction_ask_policy_caller(self):
        chat = make_chat()
        try:
            sub = self._worker(chat, ask_policy={'direction': 'caller'})
            chat.provider.chat_nonstreaming.return_value = {
                'content': 'caller answer'}
            out = sub._run_tool('ask', {'question': 'which option?'})
            self.assertEqual(out, 'caller answer')
        finally:
            chat._tmp.cleanup()


class TestPermissionScope(unittest.TestCase):

    def test_approve_phrases(self):
        for answer in ('y', 'yes', 'yes always', 'Approve once',
                       'Approve bash for this run', '1'):
            self.assertIn(_permission_scope(answer), ('once', 'always'))

    def test_always_wins(self):
        self.assertEqual(_permission_scope('yes always'), 'always')
        self.assertEqual(_permission_scope('Approve always'), 'always')
        self.assertEqual(_permission_scope('2'), 'always')

    def test_deny_phrases(self):
        for answer in ('n', 'no', 'deny', 'Decline', 'reject', '3'):
            self.assertEqual(_permission_scope(answer), 'deny')

    def test_ambiguous_is_none(self):
        self.assertEqual(_permission_scope('maybe later'), 'none')
        self.assertEqual(_permission_scope(''), 'none')


class TestGrantLifecycle(unittest.TestCase):

    def test_granted_tool_appears_then_is_consumed(self):
        engine = make_engine({'mode': 'write',
                              'tool_permission': {'bash': 'deny'}})
        try:
            engine._init_tooling()
            names = [s['function']['name'] for s in engine._tool_schema()]
            self.assertNotIn('run_command', names)
            engine.grant_permission('run_command', 'bash', scope='once',
                                    origin='user')
            names = [s['function']['name'] for s in engine._tool_schema()]
            self.assertIn('run_command', names)
            out = engine._run_tool('run_command', {'command': 'echo hi'})
            self.assertNotIn('disabled by tool policy', out)
            names = [s['function']['name'] for s in engine._tool_schema()]
            self.assertNotIn('run_command', names)
        finally:
            engine._tmp.cleanup()

    def test_grant_use_is_audited(self):
        engine = make_engine({'mode': 'write',
                              'tool_permission': {'bash': 'deny'}})
        try:
            engine._init_tooling()
            engine.grant_permission('run_command', 'bash', scope='once',
                                    origin='user')
            engine._run_tool('run_command', {'command': 'echo hi'})
            grants = [p for p in engine.current_session.permissions
                      if p.get('action') == 'grant']
            self.assertTrue(any(p.get('scope') == 'once' for p in grants))
            self.assertTrue(any(p.get('granted_by') == 'user' for p in grants))
        finally:
            engine._tmp.cleanup()

    def test_always_grant_survives_multiple_uses(self):
        engine = make_engine({'tool_permission': {'bash': 'deny'}})
        try:
            engine._init_tooling()
            engine.grant_permission('run_command', 'bash', scope='always',
                                    origin='user')
            engine._run_tool('run_command', {'command': 'echo one'})
            engine._run_tool('run_command', {'command': 'echo two'})
            self.assertTrue(engine._tool_policy.has_grant('run_command', 'bash'))
        finally:
            engine._tmp.cleanup()

    def test_ask_tool_schema_exposes_kind_and_permission(self):
        engine = make_engine()
        try:
            engine._init_tooling()
            params = engine._tool_registry.info('ask')['parameters']['properties']
            self.assertIn('kind', params)
            self.assertIn('permission', params)
            self.assertEqual(params['kind']['enum'], ['permission', 'direction'])
        finally:
            engine._tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
