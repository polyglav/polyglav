import io
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from polyglav.sessions import turns
from polyglav.sessions.manager import Session
from tests.helpers import make_chat


def add_turn(session, user='hello', answer='hi', thinking=None, tools=None,
             status='ok', duration=None):
    session.add_user(user)
    if thinking:
        session.add_thinking(thinking)
    for name, args, output in (tools or []):
        part = session.add_tool(name, args)
        turns.finish_tool(part, output)
    if answer is not None:
        session.add_text(answer)
    session.end_turn(status)
    turn = session.turns[-1]
    if duration is not None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        turn['started_at'] = start.isoformat()
        turn['ended_at'] = (start + timedelta(seconds=duration)).isoformat()
    return turn


class TestHistoryCommand(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def _many(self, count):
        for i in range(1, count + 1):
            add_turn(self.chat.current_session, user=f'prompt {i}')

    def _saved(self, name, user='saved prompt'):
        s = Session(name)
        add_turn(s, user=user)
        self.chat.sessions.save(s)
        return s

    def test_default_lists_last_ten(self):
        self._many(12)
        out = self._dispatch('/history')
        self.assertIn('- 12 turns', out)
        self.assertIn('#12  [ok]', out)
        self.assertIn('#3 ', out)
        self.assertNotIn('#2 ', out)

    def test_all_lists_every_turn(self):
        self._many(12)
        out = self._dispatch('/history all')
        self.assertIn('#1 ', out)
        self.assertIn('#12 ', out)

    def test_limit_shows_last_n(self):
        self._many(12)
        out = self._dispatch('/history 3')
        self.assertIn('#10 ', out)
        self.assertIn('#11 ', out)
        self.assertIn('#12 ', out)
        self.assertNotIn('#9 ', out)

    def test_line_fields(self):
        add_turn(self.chat.current_session, user='hello world', duration=3.4,
                 tools=[('web_search', {'query': 'x'}, 'r1'),
                        ('file_read', {'path': 'a'}, 'r2')])
        out = self._dispatch('/history 1')
        self.assertIn('#1  [ok]  3.4s  2 tools  hello world', out)

    def test_single_tool_label(self):
        add_turn(self.chat.current_session,
                 tools=[('web_search', {'query': 'x'}, 'r')])
        out = self._dispatch('/history 1')
        self.assertIn('1 tool  ', out)

    def test_running_turn_has_no_duration(self):
        self.chat.current_session.add_user('live')
        out = self._dispatch('/history 1')
        self.assertIn('[running]  -  ', out)

    def test_command_turn_shows_command(self):
        self.chat.current_session.add_command('/model llama3.3')
        out = self._dispatch('/history 1')
        self.assertIn('/model llama3.3', out)

    def test_prompt_first_line_only(self):
        add_turn(self.chat.current_session, user='first line\nsecond line')
        out = self._dispatch('/history 1')
        self.assertIn('first line', out)
        self.assertNotIn('second line', out)

    def test_long_prompt_is_clipped(self):
        add_turn(self.chat.current_session, user='x' * 200)
        out = self._dispatch('/history 1')
        self.assertIn('x' * 80 + '...', out)
        self.assertNotIn('x' * 200, out)

    def test_thoughts_excerpt(self):
        add_turn(self.chat.current_session,
                 thinking='Thinking about the answer\nmore details')
        out = self._dispatch('/history 1 --thoughts')
        self.assertIn('Thinking about the answer', out)
        self.assertNotIn('more details', out)
        self.assertIn('\033[90m', out)

    def test_thoughts_all_prints_full_text(self):
        add_turn(self.chat.current_session,
                 thinking='first thought\nsecond thought')
        out = self._dispatch('/history 1 --thoughts all')
        self.assertIn('first thought', out)
        self.assertIn('second thought', out)

    def test_no_thoughts_by_default(self):
        add_turn(self.chat.current_session, thinking='hidden thought')
        out = self._dispatch('/history 1')
        self.assertNotIn('hidden thought', out)

    def test_run_session_target(self):
        self._saved('other', user='other prompt')
        add_turn(self.chat.current_session, user='current prompt')
        before = self.chat.current_session
        out = self._dispatch('/history --run session:other')
        self.assertIn('other - 1 turns', out)
        self.assertIn('other prompt', out)
        self.assertNotIn('current prompt', out)
        self.assertIs(self.chat.current_session, before)

    def test_run_bare_session_name(self):
        self._saved('other', user='other prompt')
        out = self._dispatch('/history --run other')
        self.assertIn('other - 1 turns', out)

    def test_run_id_uses_live_session(self):
        add_turn(self.chat.current_session, user='live run prompt')
        run_id = self.chat.current_run.id
        before = self.chat.current_session
        out = self._dispatch(f'/history --run #{run_id}')
        self.assertIn('live run prompt', out)
        self.assertIs(self.chat.current_session, before)

    def test_session_id_uses_live_session(self):
        add_turn(self.chat.current_session, user='coded prompt')
        out = self._dispatch(f'/history --run #{self.chat.current_run.session_id}')
        self.assertIn('coded prompt', out)

    def test_session_id_reads_saved_session(self):
        s = self.chat.sessions.create()
        add_turn(s, user='saved coded prompt')
        self.chat.sessions.save(s)
        out = self._dispatch(f'/history --run #{s.session_id}')
        self.assertIn('saved coded prompt', out)

    def test_run_id_falls_back_to_saved_session(self):
        run = self.chat.runs.start(role='', session='saved_run')
        self._saved('saved_run', user='saved run prompt')
        out = self._dispatch(f'/history --run #{run.id}')
        self.assertIn('saved_run - 1 turns', out)
        self.assertIn('saved run prompt', out)

    def test_run_role_uses_live_run(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'found'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self.chat.run_subagent('researcher', 'research prompt')
        before = self.chat.focus.active
        out = self._dispatch('/history --run researcher')
        self.assertIn('research prompt', out)
        self.assertIs(self.chat.focus.active, before)

    def test_run_role_falls_back_to_saved_session(self):
        self._saved('writer', user='writer prompt')
        out = self._dispatch('/history --run writer')
        self.assertIn('writer prompt', out)

    def test_run_does_not_switch_focus(self):
        add_turn(self.chat.current_session, user='root prompt')
        self._saved('other', user='other prompt')
        before = self.chat.focus.active
        self._dispatch('/history --run other')
        self.assertIs(self.chat.focus.active, before)

    def test_unknown_target(self):
        out = self._dispatch('/history --run nope')
        self.assertIn('Target not found: nope', out)

    def test_no_focus_manager_session_target(self):
        self._saved('other', user='other prompt')
        self.chat._focus = None
        out = self._dispatch('/history --run other')
        self.assertIn('other prompt', out)

    def test_unknown_positional(self):
        out = self._dispatch('/history foo')
        self.assertIn('Unknown argument: foo', out)

    def test_too_many_positionals(self):
        out = self._dispatch('/history 1 2')
        self.assertIn('Usage: /history', out)

    def test_missing_run_value(self):
        out = self._dispatch('/history --run')
        self.assertIn('Usage: /history', out)

    def test_empty_session_header(self):
        out = self._dispatch('/history')
        self.assertIn('- 0 turns', out)
        self.assertIn('/print <n> reprints a turn', out)

    def test_role_in_header(self):
        self.chat.current_session.role = 'assistant'
        add_turn(self.chat.current_session, user='hi')
        out = self._dispatch('/history')
        self.assertIn('- 1 turns [assistant]', out)


if __name__ == '__main__':
    unittest.main()
