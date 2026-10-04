import unittest
from pathlib import Path
import tempfile

from polyglav.engine import _review_passed
from polyglav.teams import Team, TeamRegistry, TeamStage
from polyglav.roles import Role

from tests.helpers import make_chat


class TestReviewPassed(unittest.TestCase):

    def test_pass_marker(self):
        self.assertTrue(_review_passed('VERDICT: PASS', 'VERDICT:'))
        self.assertTrue(_review_passed('verdict: pass', 'VERDICT:'))
        self.assertFalse(_review_passed('VERDICT: CHANGES', 'VERDICT:'))
        self.assertFalse(_review_passed('', 'VERDICT:'))
        self.assertFalse(_review_passed(None, 'VERDICT:'))

    def test_custom_marker(self):
        self.assertTrue(_review_passed('REVIEW: PASS', 'REVIEW:'))
        self.assertFalse(_review_passed('VERDICT: PASS', 'REVIEW:'))


class TestTeamLoop(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.sessions_dir = self.chat.config.local_path.parent / 'sessions'
        for name in ('researcher', 'writer', 'reviewer', 'referencer'):
            self.chat.roles.put(
                Role(name=name, system_prompt=f'You are the {name}.'),
                scope='local')

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _result(self, content):
        return ({'type': 'token', 'content': content},
                {'type': 'done', 'reason': 'stop'})

    def _team(self, *stages, loop=None):
        return Team(name='doc', stages=list(stages), loop=loop or {})

    def test_plan_resolves_names_and_indices(self):
        team = self._team(TeamStage(role='writer'), TeamStage(role='reviewer'),
                          loop={'from': 'writer', 'until': 'reviewer'})
        self.assertEqual(self.chat._team_loop_plan(team), (0, 1, 3, 'VERDICT:'))
        team.loop = {'from': 0, 'until': 1, 'max_iterations': 5,
                     'verdict': 'REVIEW:'}
        self.assertEqual(self.chat._team_loop_plan(team), (0, 1, 5, 'REVIEW:'))

    def test_plan_invalid_returns_none(self):
        team = self._team(TeamStage(role='writer'), loop={'from': 'ghost',
                                                          'until': 'writer'})
        self.assertIsNone(self.chat._team_loop_plan(team))
        self.assertIsNone(self.chat._team_loop_plan(
            self._team(TeamStage(role='writer'))))
        self.assertIsNone(self.chat._team_loop_plan(
            self._team(TeamStage(role='writer'), TeamStage(role='reviewer'),
                       loop={'from': 'reviewer', 'until': 'writer'})))

    def test_pass_on_first_iteration(self):
        team = self._team(TeamStage(role='writer'), TeamStage(role='reviewer'),
                          loop={'from': 'writer', 'until': 'reviewer'})
        self.chat.provider.chat.side_effect = [
            self._result('draft'), self._result('VERDICT: PASS'),
        ]
        result = self.chat.run_team(team, 'write it')
        self.assertEqual([s.content for s in result.stages],
                         ['draft', 'VERDICT: PASS'])
        self.assertEqual(result.content, 'VERDICT: PASS')
        self.assertEqual(result.status, 'ok')

    def test_changes_then_pass_iterates(self):
        team = self._team(TeamStage(role='writer'), TeamStage(role='reviewer'),
                          loop={'from': 'writer', 'until': 'reviewer'})
        self.chat.provider.chat.side_effect = [
            self._result('d1'),
            self._result('VERDICT: CHANGES\nfix the intro'),
            self._result('d2'),
            self._result('VERDICT: PASS'),
        ]
        result = self.chat.run_team(team, 'write it')
        self.assertEqual(len(result.stages), 4)
        writer_sessions = [result.stages[i].session for i in (0, 2)]
        self.assertNotEqual(writer_sessions[0], writer_sessions[1])
        second_brief = self.chat.provider.chat.call_args_list[2][0][0]
        user = [m for m in second_brief if m.get('role') == 'user'][-1]
        self.assertIn('Findings from the previous review', user['content'])
        self.assertIn('fix the intro', user['content'])

    def test_cap_reached_without_pass(self):
        team = self._team(TeamStage(role='writer'), TeamStage(role='reviewer'),
                          loop={'from': 'writer', 'until': 'reviewer',
                                'max_iterations': 2})
        self.chat.provider.chat.side_effect = [
            self._result('d1'), self._result('VERDICT: CHANGES'),
            self._result('d2'), self._result('VERDICT: CHANGES'),
        ]
        result = self.chat.run_team(team, 'write it')
        self.assertEqual(len(result.stages), 4)
        self.assertEqual(result.status, 'ok')

    def test_pre_and_post_stages_run_once(self):
        team = self._team(
            TeamStage(role='researcher'),
            TeamStage(role='writer'),
            TeamStage(role='reviewer'),
            TeamStage(role='referencer'),
            loop={'from': 'writer', 'until': 'reviewer'})
        self.chat.provider.chat.side_effect = [
            self._result('findings'),
            self._result('d1'),
            self._result('VERDICT: CHANGES\nadd a citation'),
            self._result('d2'),
            self._result('VERDICT: PASS'),
            self._result('bib done'),
        ]
        result = self.chat.run_team(team, 'write it')
        self.assertEqual(len(result.stages), 6)
        self.assertEqual(result.content, 'bib done')
        calls = [c[0][0] for c in self.chat.provider.chat.call_args_list]
        # the post-loop referencer sees the final producer result
        last_user = next(m for m in calls[-1] if m.get('role') == 'user')
        self.assertIn('d2', last_user['content'])

    def test_stage_error_stops_loop(self):
        team = self._team(TeamStage(role='writer'), TeamStage(role='reviewer'),
                          loop={'from': 'writer', 'until': 'reviewer'})
        self.chat.provider.chat.side_effect = [
            [{'type': 'error', 'code': 0, 'message': 'boom'}],
            self._result('never'),
        ]
        result = self.chat.run_team(team, 'write it')
        self.assertEqual(result.status, 'error')
        self.assertEqual(len(result.stages), 1)
        self.assertEqual(self.chat.provider.chat.call_count, 1)

    def test_loop_roundtrip(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            def registry():
                return TeamRegistry(
                    global_dir=Path(tmp.name),
                    local_path=Path(tmp.name) / '.polyglav' / 'teams.json')
            registry().put(Team(name='x', loop={'from': 'writer',
                                                'until': 'reviewer',
                                                'max_iterations': 4},
                                stages=[TeamStage(role='writer'),
                                        TeamStage(role='reviewer')]))
            team = registry().find('x')
            self.assertEqual(team.loop, {'from': 'writer', 'until': 'reviewer',
                                         'max_iterations': 4})
        finally:
            tmp.cleanup()

    def test_catalog_saves_loop(self):
        self.chat._init_tooling()
        self.chat._tool_registry.execute('catalog', {
            'action': 'save', 'kind': 'team', 'name': 'reviewed',
            'loop': {'from': 'writer', 'until': 'reviewer',
                     'max_iterations': 2},
            'stages': [{'role': 'writer'}, {'role': 'reviewer'}]})
        team = self.chat.teams.find('reviewed')
        self.assertEqual(team.loop.get('from'), 'writer')
        self.assertEqual(team.loop.get('max_iterations'), 2)


if __name__ == '__main__':
    unittest.main()
