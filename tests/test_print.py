import io
import unittest
from unittest.mock import patch

from polyglav.sessions import turns
from polyglav.sessions.manager import Session
from tests.helpers import make_chat


def add_turn(session, user='hello', answer='hi', thinking=None, tools=None,
             **meta):
    session.add_user(user, **meta)
    if thinking:
        session.add_thinking(thinking)
    for name, args, output in (tools or []):
        part = session.add_tool(name, args)
        turns.finish_tool(part, output)
    if answer is not None:
        session.add_text(answer)
    session.end_turn('ok')
    return session.turns[-1]


class TestPrintCommand(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def _saved(self, name, user='saved prompt'):
        s = Session(name)
        add_turn(s, user=user)
        self.chat.sessions.save(s)
        return s

    def test_print_whole_turn(self):
        add_turn(self.chat.current_session, user='the prompt',
                 thinking='a thought', tools=[('web_search', {'query': 'x'}, 'res')],
                 model='llama3.2', provider='ollama', mode='build',
                 reasoning='auto')
        out = self._dispatch('/print 1')
        self.assertIn('#1  [ok]', out)
        self.assertIn('model:     llama3.2', out)
        self.assertIn('[user]', out)
        self.assertIn('the prompt', out)
        self.assertIn('[thinking]', out)
        self.assertIn('a thought', out)
        self.assertIn('[tool: web_search]', out)
        self.assertIn('"query": "x"', out)
        self.assertIn('res', out)
        self.assertIn('[assistant]', out)

    def test_command_turn_shows_empty_metadata(self):
        self.chat.current_session.add_command('/help')
        out = self._dispatch('/print 1')
        self.assertIn('[command]', out)
        self.assertIn('/help', out)
        self.assertIn('model:     -', out)
        self.assertIn('reasoning: -', out)

    def test_print_one_part(self):
        add_turn(self.chat.current_session, user='p1', answer='a1',
                 thinking='t1')
        out = self._dispatch('/print 1.2')
        self.assertIn('[thinking]', out)
        self.assertIn('t1', out)
        self.assertNotIn('[user]', out)
        self.assertNotIn('[assistant]', out)

    def test_print_hash_prefix(self):
        add_turn(self.chat.current_session, user='prompt')
        out = self._dispatch('/print #1')
        self.assertIn('prompt', out)

    def test_part_out_of_range(self):
        add_turn(self.chat.current_session, user='prompt')
        out = self._dispatch('/print 1.9')
        self.assertIn('Turn 1 has no part 9 (1-2)', out)

    def test_unknown_turn(self):
        out = self._dispatch('/print 5')
        self.assertIn('Turn not found: 5', out)

    def test_cap_uses_config(self):
        self.chat.config.set('print_max_chars', 5)
        add_turn(self.chat.current_session, user='prompt',
                 tools=[('web_search', {'query': 'x'}, 'y' * 40)])
        out = self._dispatch('/print 1')
        self.assertIn('(35 more chars, use --full)', out)

    def test_full_disables_cap(self):
        self.chat.config.set('print_max_chars', 5)
        add_turn(self.chat.current_session, user='prompt',
                 tools=[('web_search', {'query': 'x'}, 'y' * 40)])
        out = self._dispatch('/print 1 --full')
        self.assertIn('y' * 40, out)
        self.assertNotIn('more chars', out)

    def test_run_session_target(self):
        self._saved('other', user='other prompt')
        add_turn(self.chat.current_session, user='current prompt')
        before = self.chat.current_session
        out = self._dispatch('/print 1 --run session:other')
        self.assertIn('other prompt', out)
        self.assertNotIn('current prompt', out)
        self.assertIs(self.chat.current_session, before)

    def test_run_bare_session_name(self):
        self._saved('other', user='other prompt')
        out = self._dispatch('/print 1 --run other')
        self.assertIn('other prompt', out)

    def test_run_role_live_run(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'found'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self.chat.run_subagent('researcher', 'researcher prompt')
        before = self.chat.focus.active
        out = self._dispatch('/print 1 --run researcher')
        self.assertIn('researcher prompt', out)
        self.assertIs(self.chat.focus.active, before)

    def test_run_role_falls_back_to_saved(self):
        self._saved('writer', user='writer prompt')
        out = self._dispatch('/print 1 --run writer')
        self.assertIn('writer prompt', out)

    def test_session_id_uses_live_session(self):
        add_turn(self.chat.current_session, user='coded prompt')
        out = self._dispatch(f'/print 1 --run #{self.chat.current_run.session_id}')
        self.assertIn('coded prompt', out)

    def test_run_id_uses_live_session(self):
        add_turn(self.chat.current_session, user='live prompt')
        out = self._dispatch(f'/print 1 --run #{self.chat.current_run.id}')
        self.assertIn('live prompt', out)

    def test_run_unknown_target(self):
        out = self._dispatch('/print 1 --run nope')
        self.assertIn('Target not found: nope', out)

    def test_usage_without_spec(self):
        out = self._dispatch('/print')
        self.assertIn('Usage: /print', out)

    def test_usage_too_many_positionals(self):
        out = self._dispatch('/print 1 2')
        self.assertIn('Usage: /print', out)

    def test_usage_missing_run_value(self):
        out = self._dispatch('/print 1 --run')
        self.assertIn('Usage: /print', out)

    def test_invalid_turn_spec(self):
        out = self._dispatch('/print foo')
        self.assertIn('Invalid turn: foo', out)

    def test_invalid_part_spec(self):
        out = self._dispatch('/print 1.x')
        self.assertIn('Invalid part: 1.x', out)


if __name__ == '__main__':
    unittest.main()
