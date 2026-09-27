import io
import unittest
from pathlib import Path
from unittest.mock import patch

from polyglav import memory
from polyglav.roles import Role

from tests.helpers import make_chat


class TestMemoryModule(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.worktree = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_path_under_memory_dir(self):
        path = memory.memory_path(self.worktree, 'role', 'writer')
        self.assertEqual(path, (self.worktree / '.polyglav' / 'memory' / 'roles'
                                / 'writer.md').resolve())

    def test_read_write_round_trip(self):
        memory.write_memory(self.worktree, 'team', 'doc', 'team facts')
        self.assertEqual(memory.read_memory(self.worktree, 'team', 'doc'),
                         'team facts')

    def test_missing_returns_empty(self):
        self.assertEqual(memory.read_memory(self.worktree, 'job', 'nope'), '')

    def test_legacy_job_fallback(self):
        legacy = self.worktree / '.polyglav' / 'jobs' / 'keep.memory.md'
        legacy.parent.mkdir(parents=True)
        legacy.write_text('legacy job notes')
        self.assertEqual(memory.read_memory(self.worktree, 'job', 'keep'),
                         'legacy job notes')

    def test_legacy_team_fallback(self):
        legacy = self.worktree / '.polyglav' / 'teams' / 'doc' / 'memory.md'
        legacy.parent.mkdir(parents=True)
        legacy.write_text('legacy team notes')
        self.assertEqual(memory.read_memory(self.worktree, 'team', 'doc'),
                         'legacy team notes')

    def test_enabled_global_and_scope(self):
        cfg = {'memory': True, 'memory_scopes': {'role': False, 'team': True}}
        self.assertFalse(memory.memory_enabled(cfg, 'role'))
        self.assertTrue(memory.memory_enabled(cfg, 'team'))
        self.assertFalse(memory.memory_enabled({'memory': False}, 'role'))
        self.assertTrue(memory.memory_enabled({}, 'role'))

    def test_cap_memory(self):
        cfg = {'memory_max_chars': 10}
        capped = memory.cap_memory('one two three four', cfg)
        self.assertTrue(capped.startswith('one two'))
        self.assertIn('truncated', capped)


class TestRoleMemory(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.worktree = self.chat.config.local_path.parent.parent
        self.chat.roles.put(
            Role(name='writer', system_prompt='You are the writer.'),
            scope='local')

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _result(self, content):
        return ({'type': 'token', 'content': content},
                {'type': 'done', 'reason': 'stop'})

    def test_role_memory_injected_into_sub_prompt(self):
        memory.write_memory(self.worktree, 'role', 'writer', 'likes short cuts')
        sub = self.chat._new_sub_engine('writer')
        prompt = sub.config.get('system_prompt')
        self.assertIn('You are the writer.', prompt)
        self.assertIn('## Role memory', prompt)
        self.assertIn('likes short cuts', prompt)

    def test_role_memory_scope_disabled_skips_injection(self):
        self.chat.config.set('memory_scopes', {'role': False, 'team': True,
                                               'job': True})
        memory.write_memory(self.worktree, 'role', 'writer', 'secret')
        sub = self.chat._new_sub_engine('writer')
        self.assertNotIn('secret', sub.config.get('system_prompt'))

    def test_role_memory_written_after_run(self):
        self.chat.provider.chat.side_effect = [self._result('done')]
        self.chat.provider.chat_nonstreaming.return_value = {
            'content': 'writer prefers markdown'}
        self.chat.run_subagent('writer', 'draft it')
        self.assertEqual(
            memory.read_memory(self.worktree, 'role', 'writer'),
            'writer prefers markdown')

    def test_role_memory_disabled_skips_write(self):
        self.chat.config.set('memory', False)
        self.chat.provider.chat.side_effect = [self._result('done')]
        self.chat.run_subagent('writer', 'draft it')
        self.assertEqual(memory.read_memory(self.worktree, 'role', 'writer'), '')

    def test_memorize_writes_scope(self):
        self.chat.current_session.add_user('remember this')
        self.chat._summarize = lambda msgs: 'condensed run'
        out = self.chat.memorize('role', 'writer')
        self.assertIn('Wrote role memory', out)
        self.assertEqual(
            memory.read_memory(self.worktree, 'role', 'writer'), 'condensed run')

    def test_memorize_command(self):
        self.chat.current_session.add_user('remember this')
        self.chat._summarize = lambda msgs: 'command summary'
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch('/memorize role writer')
        self.assertIn('Wrote role memory', out.getvalue())

    def test_team_memory_uses_shared_dir(self):
        from polyglav.teams import team_memory_path, write_team_memory
        write_team_memory(self.worktree, 'doc', 'shared team note')
        path = team_memory_path(self.worktree, 'doc')
        self.assertEqual(path, (self.worktree / '.polyglav' / 'memory' / 'teams'
                                / 'doc.md').resolve())
        self.assertEqual(path.read_text().strip(), 'shared team note')


if __name__ == '__main__':
    unittest.main()
