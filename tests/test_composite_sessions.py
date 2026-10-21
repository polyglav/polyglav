import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from polyglav.sessions import turns

from tests.helpers import make_chat


class TestCompositeSessions(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.root = self.chat.current_session
        self.root.add_user('root prompt')
        self.root.add_part(turns.text_part('root answer'))
        self.root.end_turn('ok')
        for i in (1, 2):
            child = self.chat.sessions.create(f'sub_test{i}', role='writer')
            child.parent_id = self.root.session_name
            child.add_user(f'child {i} prompt')
            child.add_part(turns.text_part(f'child {i} answer'))
            child.end_turn('ok')
            self.chat.sessions.save(child)
            self.root.sub_sessions.append(child.session_name)
        self.chat.sessions.save(self.root)

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with redirect_stdout(out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def test_tree_includes_root_and_children(self):
        nodes = self.chat.sessions.tree(self.root.session_name)
        self.assertEqual([depth for depth, _ in nodes], [0, 1, 1])
        names = [session.session_name for _, session in nodes]
        self.assertEqual(names[0], self.root.session_name)
        self.assertIn('sub_test1', names)
        self.assertIn('sub_test2', names)

    def test_sessions_list_hides_sub_runs(self):
        out = self._dispatch('/sessions list')
        self.assertIn(self.root.session_name, out)
        self.assertNotIn('sub_test1', out)
        self.assertNotIn('sub_test2', out)

    def test_history_tree_lists_children(self):
        out = self._dispatch('/history --tree')
        self.assertIn(self.root.session_name, out)
        self.assertIn('sub_test1', out)
        self.assertIn('sub_test2', out)
        self.assertIn('child 1 prompt', out)

    def test_print_tree_renders_children(self):
        out = self._dispatch('/print --tree')
        self.assertIn(f'# Session: {self.root.session_name}', out)
        self.assertIn('# Session: sub_test1', out)
        self.assertIn('child 1 answer', out)
        self.assertIn('child 2 answer', out)

    def test_export_tree_json_includes_children(self):
        out = self._dispatch(
            f'/sessions export {self.root.session_name} --tree --json -')
        data = json.loads(out)
        self.assertEqual(len(data['sessions']), 3)
        names = [item['info']['session_name'] for item in data['sessions']]
        self.assertIn('sub_test1', names)


if __name__ == '__main__':
    unittest.main()
