import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from polyglav.teams import Team, TeamRegistry, TeamStage, team_memory_path
from polyglav.roles import Role

from tests.helpers import make_chat


class TestTeamRun(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.chat = make_chat()
        self.worktree = self.chat.config.local_path.parent.parent
        self.sessions_dir = self.chat.config.local_path.parent / 'sessions'
        for name in ('researcher', 'writer'):
            self.chat.roles.put(
                Role(name=name, system_prompt=f'You are the {name}.'),
                scope='local')

    def tearDown(self):
        self.chat._tmp.cleanup()
        self.tmp.cleanup()

    def _result(self, content, status='ok'):
        return {'type': 'token', 'content': content}, {'type': 'done', 'reason': 'stop'}

    def _team(self, *stages):
        return Team(name='doc', stages=list(stages))

    def test_brief_builds_task_and_hints(self):
        team = self._team(
            TeamStage(role='researcher', task_hint='gather sources'))
        brief = self.chat._build_stage_brief(team, 'write about X', [], 0, '')
        self.assertIn('Team: doc', brief)
        self.assertIn('Original task:\nwrite about X', brief)
        self.assertIn('gather sources', brief)
        self.assertNotIn('Team memory', brief)

    def test_brief_includes_prior_results_and_handoff(self):
        team = self._team(
            TeamStage(role='researcher',
                      handoff_note='pass the findings to the writer'),
            TeamStage(role='writer', task_hint='write it up'))
        prior = [MagicMock(content='Findings: a, b', session='sub_one')]
        brief = self.chat._build_stage_brief(team, 'task', prior, 1, '')
        self.assertIn('## Stage 1 result (sub_one):\nFindings: a, b', brief)
        self.assertIn('Stage 2 handoff from researcher: pass the findings '
                      'to the writer', brief)
        self.assertIn('write it up', brief)

    def test_brief_includes_team_memory(self):
        team = self._team(TeamStage(role='writer'))
        brief = self.chat._build_stage_brief(team, 'task', [], 0,
                                             'earlier notes')
        self.assertIn('## Team memory\nearlier notes', brief)

    def test_brief_truncates_long_prior_results(self):
        team = self._team(TeamStage(role='researcher'), TeamStage(role='writer'))
        prior = [MagicMock(content='word ' * 2000, session='sub_one')]
        brief = self.chat._build_stage_brief(team, 'task', prior, 1, '',
                                             prior_cap=500)
        self.assertIn('... (truncated)', brief)
        self.assertLessEqual(len(brief), 1500)

    def test_run_team_sequential_stages(self):
        self.chat.provider.chat.side_effect = [
            self._result('Research done.'), self._result('Draft done.'),
        ]
        result = self.chat.run_team(
            self._team(TeamStage(role='researcher'), TeamStage(role='writer')),
            'write a report')
        self.assertEqual(result.status, 'ok')
        self.assertEqual([r.content for r in result.stages],
                         ['Research done.', 'Draft done.'])
        self.assertEqual(result.content, 'Draft done.')
        self.assertEqual([r.session for r in result.stages],
                         [self.chat.current_session.sub_sessions[0],
                          self.chat.current_session.sub_sessions[1]])
        for i, res in enumerate(result.stages):
            data = json.loads((self.sessions_dir / f'{res.session}.json').read_text())
            self.assertEqual(data['parent_id'], self.chat.current_session.session_name)
            expected = self.chat._build_stage_brief(
                self._team(TeamStage(role='researcher'), TeamStage(role='writer')),
                'write a report', result.stages[:i], i, '')
            self.assertEqual(data['turns'][0]['parts'][0]['text'], expected)

    def test_team_stages_inherit_caller_mode(self):
        self.chat.config.apply('mode', 'read')
        self.chat.provider.chat.side_effect = [
            self._result('a'), self._result('b'),
        ]
        self.chat.run_team(self._team(
            TeamStage(role='researcher'),
            TeamStage(role='writer', mode='write')), 'task')
        subs = sorted(self.sessions_dir.glob('sub_*.json'))
        self.assertEqual(len(subs), 2)
        modes = sorted(
            json.loads(f.read_text())['turns'][-1]['mode'] for f in subs)
        self.assertEqual(modes, ['read', 'read'])

    def test_run_team_stage_and_task_skills(self):
        from polyglav.skills import Skill
        self.chat.skills.put(Skill(name='stage-skill', content='Stage skill body.'))
        self.chat.skills.put(Skill(name='task-skill', content='Task skill body.'))
        self.chat.skills.put(Skill(name='base-skill', content='Base skill body.'))
        self.chat.roles.put(
            Role(name='writer', system_prompt='You are the writer.',
                      skills=['base-skill']), scope='local')
        self.chat.provider.chat.side_effect = [self._result('done')]
        self.chat.run_team(
            self._team(TeamStage(role='writer', skills=['stage-skill'])),
            'task', skills=['task-skill'])
        messages = self.chat.provider.chat.call_args[0][0]
        system = next(m for m in messages if m.get('role') == 'system')
        self.assertIn('Base skill body.', system['content'])
        self.assertIn('Stage skill body.', system['content'])
        self.assertIn('Task skill body.', system['content'])

    def test_run_team_stops_on_failure(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'error', 'code': 0, 'message': 'boom'}],
            self._result('never reached'),
        ]
        result = self.chat.run_team(
            self._team(TeamStage(role='researcher'), TeamStage(role='writer')),
            'task')
        self.assertEqual(result.status, 'error')
        self.assertEqual(len(result.stages), 1)
        self.assertEqual(result.stages[0].status, 'error')
        self.assertEqual(self.chat.provider.chat.call_count, 1)

    def test_run_team_unknown_type_stops(self):
        self.chat.provider.chat.side_effect = [
            self._result('ok'), self._result('ok'),
        ]
        result = self.chat.run_team(
            self._team(TeamStage(role='researcher'), TeamStage(role='ghost')),
            'task')
        self.assertEqual(result.status, 'error')
        self.assertEqual(len(result.stages), 1)
        self.assertEqual(self.chat.provider.chat.call_count, 1)
        self.assertTrue(any('Unknown role' in str(e.get('message', ''))
                            for e in result.errors))

    def test_run_team_no_stages(self):
        result = self.chat.run_team(Team(name='empty'), 'task')
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.stages, [])
        self.assertIsNone(result.content)

    def test_memory_written_after_run(self):
        self.chat.provider.chat.side_effect = [
            self._result('done for real'),
        ]
        with patch.object(self.chat, '_summarize',
                          return_value='team memory summary'):
            result = self.chat.run_team(self._team(TeamStage(role='writer')), 'task')
        self.assertTrue(result.memory)
        memory_path = team_memory_path(self.worktree, 'doc')
        self.assertEqual(Path(result.memory), memory_path)
        self.assertEqual(memory_path.read_text().strip(), 'team memory summary')

    def test_memory_seeded_from_prior(self):
        from polyglav.teams import write_team_memory
        write_team_memory(self.worktree, 'doc', 'prior notes')
        seen = []
        self.chat.provider.chat.side_effect = [self._result('again done')]

        def _summarize(msgs):
            seen.append(msgs)
            return 'new summary'
        with patch.object(self.chat, '_summarize', side_effect=_summarize):
            self.chat.run_team(self._team(TeamStage(role='writer')), 'task')
        text = team_memory_path(self.worktree, 'doc').read_text()
        self.assertEqual(text, 'new summary')
        self.assertTrue(any('prior notes' in (m.get('content') or '')
                            for m in seen[0]))

    def test_memory_fallback_without_summarize(self):
        self.chat.provider.chat.side_effect = [self._result('fallback done')]
        with patch.object(self.chat, '_summarize', return_value=None):
            result = self.chat.run_team(self._team(TeamStage(role='writer')), 'task')
        self.assertTrue(result.memory)
        text = team_memory_path(self.worktree, 'doc').read_text()
        self.assertIn('Team doc run:', text)
        self.assertIn('fallback done', text)


class TestTeamRunCommand(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.chat = make_chat()
        self.chat.roles.put(
            Role(name='writer', system_prompt='You are the writer.'),
            scope='local')

    def tearDown(self):
        self.chat._tmp.cleanup()
        self.tmp.cleanup()

    def _team(self, arg=''):
        with patch('sys.stdout', new=io.StringIO()) as buf:
            self.chat.registry.dispatch('/teams ' + arg)
        return buf.getvalue()

    def _result(self, content):
        return ({'type': 'token', 'content': content},
                {'type': 'done', 'reason': 'stop'})

    def test_run_output(self):
        self.chat.provider.chat.side_effect = [
            self._result(f'stage {i} done') for i in range(4)
        ]
        out = self._team('run writing write the report')
        self.assertIn('Running team writing (4 stages)', out)
        self.assertIn('researcher', out)
        self.assertIn('ok', out)
        self.assertIn('stage 3 done', out)

    def test_run_unknown_team(self):
        out = self._team('run nope do something')
        self.assertIn('Team not found: nope', out)

    def test_run_usage(self):
        out = self._team('run')
        self.assertIn('Usage: /teams run <name> <task>', out)


if __name__ == '__main__':
    unittest.main()