import io
import unittest
from unittest.mock import MagicMock, patch

from polyglav.chat import MAIN_PROMPT, _prompt_text
from polyglav.focus import FocusManager

from tests.helpers import make_chat, seed_roles


class TestFocusManager(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        seed_roles(self.chat, 'writer', 'editor')
        self.focus = self.chat.focus

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _child(self, role_name='writer'):
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'Draft ready.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        res = self.chat.run_subagent(role_name, 'draft it')
        return self.chat.runs.get(res.run_id)

    def test_starts_at_root(self):
        self.assertIs(self.focus.active, self.chat)
        self.assertTrue(self.focus.is_root())
        self.assertEqual(self.focus.stack(), [self.chat.current_run.id])

    def test_enter_attaches_to_run_session_and_role(self):
        child = self._child('writer')
        engine = self.focus.enter(child.id)
        self.assertIs(self.focus.active, engine)
        self.assertFalse(self.focus.is_root())
        self.assertEqual(engine.role, 'writer')
        self.assertEqual(engine.current_session.session_name, child.session)
        self.assertIs(engine._ui, self.chat._ui)
        self.assertIs(self.chat._ui._loop, engine)

    def test_reenter_returns_same_engine(self):
        child = self._child('writer')
        first = self.focus.enter(child.id)
        second = self.focus.enter(child.id)
        self.assertIs(first, second)
        self.assertEqual(self.focus.stack(), [self.chat.current_run.id, child.id])

    def test_back_walks_the_stack(self):
        writer = self._child('writer')
        editor = self._child('editor')
        self.focus.enter(writer.id)
        self.focus.enter(editor.id)
        self.assertIs(self.focus.back().current_run, writer)
        self.assertIs(self.focus.back(), self.chat)
        self.assertTrue(self.focus.is_root())
        self.assertIs(self.chat._ui._loop, self.chat)

    def test_focus_root_run_resets(self):
        child = self._child('writer')
        self.focus.enter(child.id)
        self.assertIs(self.focus.enter(self.chat.current_run.id), self.chat)
        self.assertTrue(self.focus.is_root())

    def test_unknown_run_raises(self):
        with self.assertRaises(ValueError):
            self.focus.enter(999)

    def test_engines_lists_root_and_children(self):
        child = self._child('writer')
        engines = self.focus.engines()
        self.assertEqual(engines[0], self.chat)
        self.assertIn(self.chat.runs.engine_for(child.id), engines)

    def test_run_engine_resumes_saved_run(self):
        child = self._child('writer')
        self.chat.runs._engines.pop(child.id, None)
        engine = self.chat.run_engine(child, ui=self.chat._ui)
        self.assertEqual(engine.role, 'writer')
        self.assertEqual(engine.current_session.session_name, child.session)
        self.assertEqual(child.status, 'running')

    def test_focus_session_resumes_saved(self):
        child = self._child('writer')
        self.chat.runs._engines.pop(child.id, None)
        engine = self.focus.focus_session(child.session)
        self.assertEqual(engine.current_session.session_name, child.session)


class TestFocusRouting(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        seed_roles(self.chat, 'writer', 'editor')

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _run(self, lines):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            with patch('polyglav.chat.input', side_effect=lines):
                with patch('polyglav.chat.readline'):
                    self.chat.run()
        return out.getvalue()

    def _child(self, role_name='writer'):
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'Draft ready.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        res = self.chat.run_subagent(role_name, 'draft it')
        return self.chat.runs.get(res.run_id)

    def test_turn_routes_to_active_engine(self):
        child = self._child()
        engine = self.chat.focus.enter(child.id)
        engine.chat = MagicMock()
        self.chat.chat = MagicMock()
        self._run(['hello', EOFError])
        engine.chat.assert_called_once_with('hello')
        self.chat.chat.assert_not_called()

    def test_command_routes_to_active_registry(self):
        child = self._child()
        engine = self.chat.focus.enter(child.id)
        engine.registry = MagicMock()
        self.chat.registry = MagicMock()
        self._run(['/sessions list', EOFError])
        engine.registry.dispatch.assert_called_once_with('/sessions list')
        self.chat.registry.dispatch.assert_not_called()

    def test_prompt_shows_role_when_enabled(self):
        self.assertEqual(self.chat._prompt(), MAIN_PROMPT)
        self.chat.config.set('prompt_role', True)
        self.assertEqual(self.chat._prompt(), MAIN_PROMPT)
        child = self._child()
        self.chat.focus.enter(child.id)
        prompt = self.chat._prompt()
        self.assertIn('writer >>>', prompt)
        self.assertIn('\033[0m', prompt)
        self.assertNotIn('\033[1;36m', prompt)
        self.assertNotIn('\033[1;38;5;208m', prompt)

    def test_prompt_role_off_hides_label(self):
        self.chat.config.set('prompt_role', False)
        child = self._child()
        self.chat.focus.enter(child.id)
        self.assertEqual(self.chat._prompt(), MAIN_PROMPT)

    def test_prompt_role_on_by_default(self):
        child = self._child()
        self.chat.focus.enter(child.id)
        self.assertIn('writer >>>', self.chat._prompt())

    def test_prompt_color_tracks_mode(self):
        self.assertIn('\033[1;36m', self.chat._prompt())
        self.assertIn('\033[1;36m', self.chat._cont_prompt())
        self.chat.config.set('mode', 'write')
        self.assertIn('\033[1;38;5;208m', self.chat._prompt())
        self.assertIn('\033[1;38;5;208m', self.chat._cont_prompt())

    def test_prompt_text_libedit_reset_after_label(self):
        with patch('polyglav.chat.readline') as rl:
            rl.__doc__ = 'libedit readline'
            text = _prompt_text('\033[1;36m', '>>>')
        self.assertLess(text.index('\033[1;36m'), text.index('>>>'))
        self.assertLess(text.index('>>>'), text.index('\033[0m'))
        self.assertNotIn('\001\033[0m\002', text)

    def test_prompt_text_gnu_brackets_reset(self):
        with patch('polyglav.chat.readline') as rl:
            rl.__doc__ = 'GNU readline'
            text = _prompt_text('\033[1;36m', '>>>')
        self.assertIn('\001\033[0m\002', text)


class TestFocusCommand(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        seed_roles(self.chat, 'writer', 'editor')

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def _draft(self, role_name='writer'):
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'Draft ready.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        return self.chat.run_subagent(role_name, 'draft it')

    def test_show_run_tree_and_log(self):
        self._draft('writer')
        out = self._dispatch('/focus')
        self.assertIn('Focused:', out)
        self.assertIn('Runs:', out)
        self.assertIn('Log:', out)
        self.assertIn('writer', out)

    def test_focus_by_run_id_attaches(self):
        res = self._draft('writer')
        child = self.chat.runs.get(res.run_id)
        out = self._dispatch(f'/focus #{child.id}')
        self.assertEqual(self.chat.active().role, 'writer')
        self.assertEqual(self.chat.active().current_session.session_name,
                         child.session)
        self.assertIn('Focused:', out)

    def test_focus_back_returns(self):
        res = self._draft('writer')
        self._dispatch(f'/focus #{res.run_id}')
        out = self._dispatch('/focus back')
        self.assertIs(self.chat.active(), self.chat)
        self.assertIn('Focused:', out)

    def test_focus_by_root_id_resets(self):
        res = self._draft('writer')
        self._dispatch(f'/focus #{res.run_id}')
        self._dispatch('/focus #1')
        self.assertIs(self.chat.active(), self.chat)

    def test_focus_by_session_id_resets(self):
        res = self._draft('writer')
        self._dispatch(f'/focus #{res.run_id}')
        self._dispatch(f'/focus #{self.chat.current_run.session_id}')
        self.assertIs(self.chat.active(), self.chat)

    def test_focus_by_numeric_session_id(self):
        run = self.chat.runs.start(role='writer', session='sub_num',
                                   session_id='123456')
        self._dispatch('/focus #123456')
        self.assertEqual(self.chat.active().current_run.id, run.id)

    def test_focus_by_session_selects_run(self):
        res = self._draft('writer')
        self._dispatch('/focus root')
        self._dispatch(f'/focus session:{res.session}')
        self.assertEqual(self.chat.active().role, 'writer')

    def test_focus_child_and_parent(self):
        res = self._draft('writer')
        self._dispatch(f'/focus #{res.run_id}')
        self._dispatch('/focus parent')
        self.assertIs(self.chat.active(), self.chat)
        self._dispatch('/focus child')
        self.assertEqual(self.chat.active().role, 'writer')

    def test_focus_sibling(self):
        first = self._draft('writer')
        self._draft('editor')
        self._dispatch(f'/focus #{first.run_id}')
        self._dispatch('/focus sibling')
        self.assertEqual(self.chat.active().role, 'editor')

    def test_focus_next_and_prev(self):
        self._draft('writer')
        self._draft('editor')
        self._dispatch('/focus root')
        self._dispatch('/focus next')
        self.assertEqual(self.chat.active().role, 'writer')
        self._dispatch('/focus prev')
        self.assertIs(self.chat.active(), self.chat)

    def test_focus_role_is_no_longer_a_target(self):
        out = self._dispatch('/focus writer')
        self.assertIn('not found', out)

    def test_focus_unknown_target(self):
        out = self._dispatch('/focus ghost')
        self.assertIn('not found', out)

    def test_focus_absent_manager(self):
        from polyglav.commands.builtins import _focus_manager
        self.assertIsNone(_focus_manager(object()))


if __name__ == '__main__':
    unittest.main()
