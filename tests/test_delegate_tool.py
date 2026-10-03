import io
import json
import unittest
from unittest.mock import MagicMock, patch

from polyglav.teams import Team, TeamStage
from polyglav.tools.delegate import _clamped_stages, _team_action
from polyglav.roles import Role

from tests.helpers import make_chat


class TestTeamTool(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat.config.set('mode', 'write')
        self.chat._summarize = MagicMock(return_value='summary')
        self.sessions_dir = self.chat.config.local_path.parent / 'sessions'
        for name in ('researcher', 'writer'):
            self.chat.roles.put(
                Role(name=name, system_prompt=f'You are the {name}.'),
                scope='local')

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _result(self, content, status='ok'):
        return ({'type': 'token', 'content': content},
                {'type': 'done', 'reason': 'stop'})

    def _team(self, name='doc', *stages):
        self.chat.teams.put(
            Team(name=name, stages=list(stages)), scope='local')

    def _run(self, name='doc', task='write a report'):
        self.chat._init_tooling()
        return self.chat._run_tool('delegate', {'name': name, 'task': task})

    def test_registered_in_schema(self):
        schema = self.chat._init_tooling()
        names = [s['function']['name'] for s in schema]
        self.assertIn('delegate', names)
        entry = self.chat._tool_registry.info('delegate')
        self.assertEqual(entry['category'], 'delegate')
        self.assertEqual(entry['permission'], 'delegate')
        self.assertTrue(self.chat._tool_registry.loop_for('delegate'))
        self.assertIn('name', entry['parameters']['properties'])
        self.assertIn('task', entry['parameters']['properties'])

    def test_runs_pipeline_and_returns_final(self):
        self._team('doc', TeamStage(role='researcher'), TeamStage(role='writer'))
        self.chat.provider.chat.side_effect = [
            self._result('Research done.'), self._result('Draft done.'),
        ]
        out = self._run()
        self.assertIn('[delegate doc] Draft done.', out)
        self.assertEqual(self.chat.provider.chat.call_count, 2)
        self.assertEqual(len(self.chat.current_session.sub_sessions), 2)

    def test_team_offers_focus_on_last_stage(self):
        self._team('doc', TeamStage(role='writer'))
        self.chat.provider.chat.side_effect = [self._result('done')]
        out = self._run()
        self.assertIn('focus follows', out)
        self.assertIsNotNone(self.chat._pending_focus)

    def test_team_focus_off_leaves_focus_alone(self):
        self._team('doc', TeamStage(role='writer'))
        self.chat.config.set('focus_on_delegate', 'off')
        self.chat.provider.chat.side_effect = [self._result('done')]
        out = self._run()
        self.assertNotIn('focus follows', out)
        self.assertIsNone(self.chat._pending_focus)

    def test_unknown_team_errors(self):
        out = self._run(name='ghost')
        self.assertIn('Error: unknown team "ghost"', out)

    def test_team_without_stages_errors(self):
        self._team('empty')
        out = self._run(name='empty')
        self.assertIn('has no stages', out)

    def test_unknown_stage_type_errors(self):
        self._team('doc', TeamStage(role='ghost'))
        out = self._run()
        self.assertIn('Error: team "doc" failed', out)
        self.assertIn('Unknown role', out)

    def test_resolver_allows_known_team(self):
        self._team('doc', TeamStage(role='researcher'))
        self.assertEqual(_team_action(self.chat, {'name': 'doc'}), 'allow')

    def test_resolver_denies_stage_delegate_deny(self):
        self.chat.roles.put(Role(
            name='locked', system_prompt='x',
            tool_permission={'delegate': 'deny'}), scope='local')
        self._team('doc', TeamStage(role='locked'))
        self.assertEqual(_team_action(self.chat, {'name': 'doc'}), 'deny')
        out = self._run()
        self.assertIn('disabled by tool policy', out)

    def test_resolver_asks_for_stage_delegate_ask(self):
        self.chat.roles.put(Role(
            name='cautious', system_prompt='x',
            tool_permission={'delegate': 'ask'}), scope='local')
        self._team('doc', TeamStage(role='cautious'))
        self.assertEqual(_team_action(self.chat, {'name': 'doc'}), 'ask')
        self.chat.provider.chat.side_effect = [self._result('done')]
        with patch('builtins.input', return_value='n'):
            out = self._run()
        self.assertIn('[cancelled]', out)

    def test_clamped_stage_is_noted(self):
        chat = make_chat({
            'mode': 'write',
            'grant_permission': {'bash': 'deny', 'read': 'allow'},
            'tool_permission': {'ask': 'allow', 'read': 'allow', 'bash': 'ask'},
        })
        try:
            chat._summarize = MagicMock(return_value='summary')
            chat.roles.put(Role(
                name='impl', system_prompt='x',
                tool_permission={'bash': 'allow'}), scope='local')
            chat.teams.put(Team(
                name='doc', stages=[TeamStage(role='impl')]), scope='local')
            chat.provider.chat.side_effect = [
                ({'type': 'token', 'content': 'done'},
                 {'type': 'done', 'reason': 'stop'}),
            ]
            chat._init_tooling()
            out = chat._run_tool('delegate', {'name': 'doc', 'task': 't'})
            self.assertIn('reduced permissions for: impl', out)
        finally:
            chat._tmp.cleanup()

    def test_clamped_stages_helper(self):
        chat = make_chat({
            'grant_permission': {'bash': 'deny', 'read': 'allow'},
            'tool_permission': {'ask': 'allow', 'read': 'allow', 'bash': 'ask'},
        })
        try:
            chat.roles.put(Role(
                name='impl', system_prompt='x',
                tool_permission={'bash': 'allow'}), scope='local')
            chat.roles.put(Role(
                name='safe', system_prompt='x',
                tool_permission={'bash': 'deny'}), scope='local')
            team = Team(name='doc', stages=[
                TeamStage(role='impl'), TeamStage(role='safe')])
            self.assertEqual(_clamped_stages(chat, team), ['impl'])
        finally:
            chat._tmp.cleanup()

    def test_cycle_guard(self):
        self._team('doc', TeamStage(role='writer'))
        self.chat._team_stack = ['doc']
        result = self.chat.run_team(self.chat.teams.find('doc'), 'task')
        self.assertEqual(result.status, 'error')
        self.assertTrue(any(e.get('code') == 'team_cycle' for e in result.errors))
        self.assertIn('do not call the team tool',
                      result.errors[0]['message'])

    def test_resolver_denies_self_team_on_stack(self):
        self._team('doc', TeamStage(role='writer'))
        self.chat._team_stack = ['doc']
        self.assertEqual(_team_action(self.chat, {'name': 'doc'}), 'deny')

    def test_self_team_call_refused_on_stage(self):
        self._team('doc', TeamStage(role='writer'))
        self.chat._team_stack = ['doc']
        out = self._run()
        self.assertIn('disabled by tool policy', out)
        self.assertEqual(self.chat.provider.chat.call_count, 0)

    def test_stage_error_without_details_reports_status_and_session(self):
        from polyglav.engine import TurnResult
        self._team('doc', TeamStage(role='writer'))
        with patch.object(
                self.chat, '_run_team_stage',
                return_value=TurnResult(status='cancelled', session='sub_x')):
            out = self._run()
        self.assertIn('cancelled', out)
        self.assertIn('sub_x', out)
        self.assertNotIn('unknown error', out)

    def test_clamped_stage_failure_hints_ceiling(self):
        from polyglav.engine import TurnResult
        self.chat.config.apply('grant_permission', {'bash': 'deny'})
        self.chat.roles.put(Role(
            name='impl2', system_prompt='x',
            tool_permission={'bash': 'allow'}), scope='local')
        self._team('doc', TeamStage(role='impl2'))
        with patch.object(
                self.chat, '_run_team_stage',
                return_value=TurnResult(status='error',
                                        errors=[{'message': 'boom'}])):
            out = self._run()
        self.assertIn('boom', out)
        self.assertIn('reduced permissions for: impl2', out)
        self.assertIn('above the caller ceiling', out)

    def test_stage_brief_forbids_reentry(self):
        self._team('doc', TeamStage(role='writer'))
        team = self.chat.teams.find('doc')
        brief = self.chat._build_stage_brief(team, 'task', [], 0, '')
        self.assertIn('stage 1 of team "doc"', brief)
        self.assertIn('do not call the team tool', brief)

    def test_depth_guard(self):
        self._team('doc', TeamStage(role='writer'))
        self.chat._team_depth = self.chat.config.get('max_team_depth')
        result = self.chat.run_team(self.chat.teams.find('doc'), 'task')
        self.assertEqual(result.status, 'error')
        self.assertTrue(any(e.get('code') == 'team_depth' for e in result.errors))

    def test_depth_and_stack_propagate_to_subengine(self):
        self.chat._team_depth = 1
        self.chat._team_stack = ['doc']
        sub = self.chat._new_sub_engine('writer')
        self.assertEqual(sub._team_depth, 1)
        self.assertEqual(sub._team_stack, ['doc'])

    def test_agent_loop_runs_team_tool(self):
        self._team('doc', TeamStage(role='writer'))
        tool_call = [{
            'id': 'call_team001',
            'type': 'function',
            'function': {'name': 'delegate',
                         'arguments': json.dumps({'name': 'doc',
                                                  'task': 'write it'})},
        }]
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': tool_call}],
            self._result('Stage output.'),
            self._result('Final answer.'),
        ]
        with patch('sys.stdout', new=io.StringIO()):
            self.chat._agent_loop()
        self.assertEqual(self.chat.provider.chat.call_count, 3)
        tools = [p for t in self.chat.current_session.turns
                 for p in t.get('parts') or [] if p['type'] == 'tool']
        self.assertTrue(tools)
        self.assertIn('[delegate doc] Stage output.', tools[0]['output'])


if __name__ == '__main__':
    unittest.main()
