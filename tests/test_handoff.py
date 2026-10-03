import io
import json
import unittest
from unittest.mock import patch

from tests.helpers import make_chat


class TestHandoffTool(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat._init_tooling()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _handoff(self, target, done=False):
        return self.chat._run_tool('handoff', {'target': target, 'done': done})

    def _child(self, role_name='writer'):
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'Draft ready.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        res = self.chat.run_subagent(role_name, 'draft it')
        return self.chat.runs.get(res.run_id)

    def test_registered(self):
        self.assertIn('handoff', self.chat._tool_registry.names())
        self.assertEqual(self.chat._tool_registry.permission_for('handoff'), 'handoff')

    def test_handoff_to_run_id_sets_pending_and_pauses(self):
        child = self._child('writer')
        out = self._handoff(f'#{child.id}')
        self.assertTrue(out.startswith('[handoff]'))
        self.assertEqual(self.chat._pending_handoff['run'], child.id)
        self.assertEqual(self.chat.current_run.status, 'paused')

    def test_done_finishes_the_run(self):
        child = self._child('writer')
        self._handoff(f'#{child.id}', done=True)
        self.assertEqual(self.chat.current_run.status, 'done')
        self.assertTrue(self.chat.current_run.ended_at)

    def test_unknown_target_errors_without_pausing(self):
        out = self._handoff('ghost')
        self.assertTrue(out.startswith('Error'))
        self.assertEqual(self.chat.current_run.status, 'running')
        self.assertIsNone(self.chat._pending_handoff)

    def test_handoff_to_parent_from_child(self):
        child = self._child('writer')
        engine = self.chat.focus.enter(child.id)
        engine._init_tooling()
        out = engine._run_tool('handoff', {'target': 'parent'})
        self.assertTrue(out.startswith('[handoff]'))
        self.assertEqual(self.chat._pending_handoff['run'],
                         self.chat.current_run.id)
        self.assertEqual(engine.current_run.status, 'paused')
        self.assertEqual(self.chat.current_run.status, 'running')

    def test_handoff_to_session_id(self):
        session_id = self.chat.current_run.session_id
        out = self._handoff(f'#{session_id}')
        self.assertTrue(out.startswith('[handoff]'))
        self.assertEqual(self.chat._pending_handoff['run'],
                         self.chat.current_run.id)
        self.assertEqual(self.chat.current_run.status, 'paused')

    def test_handoff_to_child(self):
        child = self._child('writer')
        self._handoff('child')
        self.assertEqual(self.chat._pending_handoff['run'], child.id)

    def test_handoff_to_sibling(self):
        first = self._child('writer')
        second = self._child('editor')
        engine = self.chat.focus.enter(first.id)
        engine._init_tooling()
        out = engine._run_tool('handoff', {'target': 'sibling'})
        self.assertTrue(out.startswith('[handoff]'))
        self.assertEqual(self.chat._pending_handoff['run'], second.id)

    def test_handoff_to_root(self):
        child = self._child('writer')
        engine = self.chat.focus.enter(child.id)
        engine._init_tooling()
        engine._run_tool('handoff', {'target': 'root'})
        self.assertEqual(self.chat._pending_handoff['run'],
                         self.chat.current_run.id)

    def test_handoff_to_session_name(self):
        child = self._child('writer')
        out = self._handoff(child.session)
        self.assertTrue(out.startswith('[handoff]'))
        self.assertEqual(self.chat._pending_handoff['run'], child.id)

    def test_sub_agent_without_focus_errors(self):
        sub = self.chat._new_sub_engine('writer', task='draft')
        sub._init_tooling()
        out = sub._run_tool('handoff', {'target': 'parent'})
        self.assertTrue(out.startswith('Error'))
        self.assertIsNone(self.chat._pending_handoff)


class TestHandoffTurnStop(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def test_loop_stops_after_handoff(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': [
                {'id': 'call_1', 'type': 'function',
                 'function': {'name': 'handoff',
                              'arguments': json.dumps({'target': 'root'})}},
            ]}],
            [{'type': 'token', 'content': 'should not run'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        with patch('sys.stdout', new=io.StringIO()):
            self.chat._agent_loop()
        self.assertEqual(self.chat.provider.chat.call_count, 1)
        self.assertEqual(self.chat._pending_handoff['run'],
                         self.chat.current_run.id)


class TestHandoffApply(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _child(self, role_name='writer'):
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'Draft ready.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        res = self.chat.run_subagent(role_name, 'draft it')
        return self.chat.runs.get(res.run_id)

    def test_apply_focuses_run(self):
        child = self._child('writer')
        self.chat._pending_handoff = {'run': child.id}
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat._apply_handoff()
        self.assertEqual(self.chat.active().current_session.session_name,
                         child.session)
        self.assertIsNone(self.chat._pending_handoff)
        self.assertIn('Focused:', out.getvalue())

    def test_apply_root_run_resets(self):
        self._child('writer')
        self.chat._pending_handoff = {'run': self.chat.current_run.id}
        with patch('sys.stdout', new=io.StringIO()):
            self.chat._apply_handoff()
        self.assertIs(self.chat.active(), self.chat)

    def test_run_applies_pending_after_turn(self):
        self.chat.provider.chat.return_value = [
            {'type': 'tool_calls', 'tool_calls': [
                {'id': 'call_1', 'type': 'function',
                 'function': {'name': 'handoff',
                              'arguments': json.dumps({'target': 'root'})}},
            ]},
        ]
        with patch('sys.stdout', new=io.StringIO()):
            with patch('polyglav.chat.input', side_effect=['hi', EOFError]):
                with patch('polyglav.chat.readline'):
                    self.chat.run()
        self.assertIs(self.chat.active(), self.chat)


if __name__ == '__main__':
    unittest.main()
