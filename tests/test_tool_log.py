import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from polyglav import tool_log
from polyglav.sessions.manager import SessionManager
from polyglav.sessions import turns
from tests.helpers import make_chat


class TestToolLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = Path(self.tmp.name) / '.polyglav' / 'sessions'
        self.sessions.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_and_resolve(self):
        stored = tool_log.append(self.sessions, 's1', 1, 0, 'file_read', 'body')
        self.assertEqual(stored['bytes'], 4)
        self.assertEqual(stored['lines'], 1)
        self.assertEqual(stored['summary'], 'body')
        self.assertTrue(stored['ref'].endswith('.tools.log#L1-L4'))
        self.assertIn('body', tool_log.resolve(stored['ref'], self.sessions))

    def test_append_grows_by_line_range(self):
        first = tool_log.append(self.sessions, 's1', 1, 0, 'a', 'one')
        second = tool_log.append(self.sessions, 's1', 1, 1, 'b', 'two')
        self.assertIn('#L1-L4', first['ref'])
        self.assertIn('#L5-L8', second['ref'])
        self.assertEqual(tool_log.resolve(second['ref'], self.sessions).splitlines()[0],
                         '# turn 1 part 1 b' + tool_log.resolve(
                             second['ref'], self.sessions).splitlines()[0][len('# turn 1 part 1 b'):])

    def test_delete_removes_log(self):
        tool_log.append(self.sessions, 's1', 1, 0, 'a', 'one')
        manager = SessionManager(self.sessions)
        session = manager.create('s1')
        manager.save(session)
        self.assertTrue(manager.delete('s1'))
        self.assertFalse((self.sessions / 's1.tools.log').exists())

    def test_missing_ref(self):
        self.assertIsNone(tool_log.resolve(
            '.polyglav/sessions/missing.tools.log#L1-L2', self.sessions))

    def test_engine_stores_ref_and_summary(self):
        chat = make_chat()
        try:
            part = chat.current_session.add_tool('file_read', {})
            ref = chat._store_tool_output(part, 'line one\nline two', 1, 0,
                                          'file_read')
            self.assertTrue(ref.endswith('.tools.log#L1-L5'))
            self.assertEqual(part['summary'], 'line one')
            self.assertTrue(chat.resolve_tool_ref(ref).splitlines()[0].startswith(
                '# turn 1 part 0 file_read'))
        finally:
            chat._tmp.cleanup()

    def test_engine_skips_log_when_disabled(self):
        chat = make_chat({'tool_output_log': False})
        try:
            part = chat.current_session.add_tool('file_read', {})
            ref = chat._store_tool_output(part, 'body', 1, 0, 'file_read')
            self.assertEqual(ref, '')
            self.assertNotIn('ref', part)
        finally:
            chat._tmp.cleanup()

    def test_auto_save_keeps_summary_and_ref(self):
        chat = make_chat()
        try:
            session = chat.current_session
            part = session.add_tool('fetch_page', {'url': 'x'})
            turns.finish_tool(part, 'page body')
            chat._store_tool_output(part, 'page body', 1, 0, 'fetch_page')
            type(chat).session_auto_save(chat)
            with open(chat.sessions.sessions_dir / f'{session.session_name}.json') as f:
                data = json.load(f)
            tool = data['turns'][0]['parts'][0]
            self.assertEqual(tool['output'], 'page body')
            self.assertTrue(tool['ref'].endswith('.tools.log#L1-L4'))
        finally:
            chat._tmp.cleanup()

    def test_print_resolves_tool_log(self):
        chat = make_chat()
        try:
            part = chat.current_session.add_tool('fetch_page', {})
            ref = chat._store_tool_output(part, 'full page body', 1, 0,
                                          'fetch_page')
            turns.finish_tool(part, 'marker')
            path = (Path(__file__).resolve().parents[1] / 'plugins'
                    / 'polyglav-core-sessions' / 'src' / 'render.py')
            spec = importlib.util.spec_from_file_location(
                'polyglav_core_sessions_render_test', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            out = module.render_turn(chat.current_session.turns[0],
                                     resolve=chat.resolve_tool_ref)
            self.assertIn('full page body', out)
        finally:
            chat._tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
