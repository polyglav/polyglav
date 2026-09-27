import io
import json
import unittest
from unittest.mock import MagicMock, patch

from polyglav.engine import Engine, TeamRunResult
from polyglav.teams import Team, TeamStage
from polyglav.roles import Role

from tests.helpers import make_chat


class TestRunResume(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.sessions_dir = self.chat.config.local_path.parent / 'sessions'
        for name in ('researcher', 'writer'):
            self.chat.roles.put(
                Role(name=name, system_prompt=f'You are the {name}.'),
                scope='local')

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _result(self, content):
        return ({'type': 'token', 'content': content},
                {'type': 'done', 'reason': 'stop'})

    def _session(self, name):
        return json.loads((self.sessions_dir / f'{name}.json').read_text())

    def test_default_sessions_are_fresh(self):
        self.chat.provider.chat.side_effect = [
            self._result('a'), self._result('b'),
        ]
        r1 = self.chat.run_subagent('writer', 't1')
        r2 = self.chat.run_subagent('writer', 't2')
        self.assertNotEqual(r1.session, r2.session)
        self.assertTrue(r1.session.startswith('sub_'))

    def test_resume_by_run_id_reuses_session(self):
        self.chat.provider.chat.side_effect = [
            self._result('first'), self._result('second'),
        ]
        r1 = self.chat.run_subagent('writer', 'task one')
        r2 = self.chat.run_subagent('writer', 'task two',
                                    resume=f'#{r1.run_id}')
        self.assertEqual(r2.session, r1.session)
        self.assertEqual(r2.run_id, r1.run_id)
        users = [p['text'] for t in self._session(r1.session)['turns']
                 for p in t.get('parts') or [] if p['type'] == 'user']
        self.assertEqual(users, ['task one', 'task two'])

    def test_resume_by_session_name(self):
        self.chat.provider.chat.side_effect = [
            self._result('first'), self._result('second'),
        ]
        r1 = self.chat.run_subagent('writer', 'task one')
        r2 = self.chat.run_subagent('writer', 'task two', resume=r1.session)
        self.assertEqual(r2.session, r1.session)

    def test_resume_by_session_id(self):
        self.chat.provider.chat.side_effect = [
            self._result('first'), self._result('second'),
        ]
        r1 = self.chat.run_subagent('writer', 'task one')
        session = self.chat.sessions.read(r1.session)
        r2 = self.chat.run_subagent('writer', 'task two',
                                    resume=f'#{session.session_id}')
        self.assertEqual(r2.session, r1.session)

    def test_resume_unknown_raises(self):
        with self.assertRaises(ValueError):
            self.chat.run_subagent('writer', 't', resume='#zzzzzz')

    def test_context_new_ignores_resume(self):
        self.chat.provider.chat.side_effect = [
            self._result('first'), self._result('second'),
        ]
        r1 = self.chat.run_subagent('writer', 'task one')
        r2 = self.chat.run_subagent('writer', 'task two',
                                    resume=f'#{r1.run_id}', context='new')
        self.assertNotEqual(r2.session, r1.session)

    def test_context_compact_summarizes_first(self):
        self.chat.provider.chat.side_effect = [
            self._result('first'), self._result('second'),
        ]
        r1 = self.chat.run_subagent('writer', 'task one')
        with patch.object(Engine, 'compact_session', autospec=True) as compact:
            self.chat.run_subagent('writer', 'task two',
                                   resume=f'#{r1.run_id}', context='compact')
        compact.assert_called_once()

    def test_team_resume_seeds_first_stage(self):
        team = Team(name='doc', stages=[
            TeamStage(role='researcher'), TeamStage(role='writer')])
        self.chat.provider.chat.side_effect = [
            self._result('r1'), self._result('w1'),
            self._result('r2'), self._result('w2'),
        ]
        res1 = self.chat.run_team(team, 'task one')
        first = res1.stages[0]
        res2 = self.chat.run_team(team, 'task two',
                                  resume=f'#{first.run_id}')
        self.assertEqual(res2.stages[0].session, first.session)
        self.assertNotEqual(res2.stages[1].session, res1.stages[1].session)
        users = [p['text'] for t in self._session(first.session)['turns']
                 for p in t.get('parts') or [] if p['type'] == 'user']
        self.assertEqual(len(users), 2)

    def test_team_default_sessions_are_fresh(self):
        team = Team(name='cold', stages=[TeamStage(role='writer')])
        self.chat.provider.chat.side_effect = [
            self._result('a'), self._result('b'),
        ]
        res1 = self.chat.run_team(team, 'one')
        res2 = self.chat.run_team(team, 'two')
        self.assertNotEqual(res1.stages[0].session, res2.stages[0].session)

    def test_delegate_tool_forwards_resume(self):
        from types import SimpleNamespace
        self.chat.roles.put(
            Role(name='dev', system_prompt='Dev',
                      tool_permission={'delegate': 'allow'}), scope='local')
        with patch.object(self.chat, 'run_subagent', return_value=SimpleNamespace(
                status='ok', content='done', errors=[], session='sub_x',
                run_id=1, duration=0.0, usage=None)) as run:
            with patch('sys.stdout', new=io.StringIO()):
                self.chat._init_tooling()
                self.chat._tool_registry.execute(
                    'delegate', {'role': 'dev', 'task': 't',
                                 'resume': '#3', 'context': 'compact'})
        self.assertEqual(run.call_args.kwargs.get('resume'), '#3')
        self.assertEqual(run.call_args.kwargs.get('context'), 'compact')

    def test_team_tool_forwards_resume(self):
        with patch.object(self.chat, 'run_team',
                          return_value=TeamRunResult(name='writing',
                                                     status='ok')) as run:
            with patch('sys.stdout', new=io.StringIO()):
                self.chat._init_tooling()
                self.chat._tool_registry.execute(
                    'team', {'name': 'writing', 'task': 't',
                             'resume': '#4', 'context': 'new'})
        self.assertEqual(run.call_args.kwargs.get('resume'), '#4')
        self.assertEqual(run.call_args.kwargs.get('context'), 'new')

    def test_team_fields_roundtrip(self):
        from polyglav.teams import TeamRegistry
        import tempfile
        from pathlib import Path
        tmp = tempfile.TemporaryDirectory()
        try:
            reg = TeamRegistry(
                global_dir=Path(tmp.name),
                local_path=Path(tmp.name) / '.polyglav' / 'teams.json',
                bundled_path=Path(tmp.name) / 'none.json')
            reg.put(Team(name='x', stages=[TeamStage(role='w')]))
            fresh = TeamRegistry(
                global_dir=Path(tmp.name),
                local_path=Path(tmp.name) / '.polyglav' / 'teams.json',
                bundled_path=Path(tmp.name) / 'none.json')
            team = fresh.find('x')
            self.assertFalse(hasattr(team, 'warm_sessions'))
            self.assertFalse(hasattr(team.stages[0], 'session_key'))
        finally:
            tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
