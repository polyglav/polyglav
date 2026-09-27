import unittest

from polyglav.runs import RunRegistry

from tests.helpers import make_chat


class TestRunRegistry(unittest.TestCase):

    def test_ids_are_sequential_from_one(self):
        reg = RunRegistry()
        a = reg.start(role='assistant', session='root')
        b = reg.start(role='writer', session='sub')
        self.assertEqual(a.id, 1)
        self.assertEqual(b.id, 2)
        self.assertEqual(len(reg), 2)

    def test_parent_child_tree_and_call_order(self):
        reg = RunRegistry()
        root = reg.start(role='assistant', session='root')
        child = reg.start(role='writer', session='child', parent=root.id)
        grand = reg.start(role='tester', session='grand', parent=child.id)
        self.assertIsNone(root.parent)
        self.assertEqual(child.parent, root.id)
        self.assertEqual(grand.parent, child.id)
        self.assertEqual(root.children, [child.id])
        self.assertEqual(child.children, [grand.id])
        self.assertEqual([r.id for r in reg.runs()], [root.id, child.id, grand.id])
        self.assertEqual([r.id for r in reg.children(root.id)], [child.id])

    def test_finish_sets_status_and_is_once(self):
        reg = RunRegistry()
        run = reg.start(role='writer', session='sub')
        self.assertEqual(run.status, 'running')
        self.assertEqual(run.ended_at, '')
        reg.finish(run.id, 'done')
        self.assertEqual(run.status, 'done')
        ended = run.ended_at
        self.assertTrue(ended)
        reg.finish(run.id, 'error')
        self.assertEqual(run.status, 'done')
        self.assertEqual(run.ended_at, ended)

    def test_task_recorded(self):
        reg = RunRegistry()
        run = reg.start(role='writer', session='sub', task='write the expose')
        self.assertEqual(run.task, 'write the expose')

    def test_unknown_run_is_none(self):
        reg = RunRegistry()
        self.assertIsNone(reg.get(99))
        self.assertIsNone(reg.finish(99))
        self.assertEqual(reg.children(99), [])


class TestEngineRuns(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def test_root_run_registered(self):
        self.assertEqual(self.chat.current_run.id, 1)
        self.assertIs(self.chat.runs.get(1), self.chat.current_run)
        self.assertEqual(self.chat.current_run.session, self.chat.current_session.session_name)
        self.assertIsNone(self.chat.current_run.parent)

    def test_bind_assistant_updates_run_role(self):
        self.chat._bind_assistant()
        self.assertEqual(self.chat.current_run.role, 'assistant')
        self.assertEqual(self.chat.current_session.role, 'assistant')

    def test_sub_engine_shares_registry_and_links_parent(self):
        sub = self.chat._new_sub_engine('writer', task='draft')
        self.assertIs(sub.runs, self.chat.runs)
        self.assertEqual(sub.current_run.parent, self.chat.current_run.id)
        self.assertEqual(sub.current_run.role, 'writer')
        self.assertEqual(sub.current_run.task, 'draft')
        self.assertIn(sub.current_run.id, self.chat.current_run.children)
        self.assertEqual(sub.current_run.session, sub.current_session.session_name)

    def test_run_subagent_finishes_child_run(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'Draft ready.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        result = self.chat.run_subagent('writer', 'draft it')
        self.assertEqual(result.status, 'ok')
        child = self.chat.runs.runs()[-1]
        self.assertEqual(child.role, 'writer')
        self.assertEqual(child.status, 'done')
        self.assertTrue(child.ended_at)

    def test_load_or_create_session_updates_run_session(self):
        self.chat.load_or_create_session('named_session')
        self.assertEqual(self.chat.current_run.session, 'named_session')


if __name__ == '__main__':
    unittest.main()
