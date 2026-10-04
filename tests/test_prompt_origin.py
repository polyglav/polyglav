import unittest

from polyglav.sessions import turns
from polyglav.sessions.render import prompt_origin, render_turn
from tests.helpers import make_chat, seed_roles


class TestPromptOrigin(unittest.TestCase):

    def test_user_part_default_has_no_origin(self):
        part = turns.user_part('hello')
        self.assertNotIn('origin', part)

    def test_user_part_records_role_origin(self):
        part = turns.user_part('task', origin='manager')
        self.assertEqual(part['origin'], 'manager')

    def test_add_user_records_origin(self):
        chat = make_chat()
        try:
            chat.current_session.add_user('task', origin='manager')
            part = chat.current_session.turns[-1]['parts'][0]
            self.assertEqual(part['origin'], 'manager')
        finally:
            chat._tmp.cleanup()

    def test_prompt_origin_labels(self):
        self.assertEqual(prompt_origin({}), 'User')
        self.assertEqual(prompt_origin({'origin': 'user'}), 'User')
        self.assertEqual(prompt_origin({'origin': 'manager'}), 'Manager')

    def test_render_uses_origin(self):
        turn = turns.new_turn(1)
        turns.add_part(turn, turns.user_part('do it', origin='manager'))
        turns.finish_turn(turn)
        self.assertIn('[manager]', render_turn(turn))

    def test_run_subagent_records_caller_origin(self):
        chat = make_chat()
        try:
            seed_roles(chat, 'writer')
            chat.provider.chat.side_effect = [
                [{'type': 'token', 'content': 'done'},
                 {'type': 'done', 'reason': 'stop'}],
            ]
            result = chat.run_subagent('writer', 'draft')
            session = chat.sessions.read(result.session)
            user = [p for t in session.turns for p in t.get('parts') or []
                    if p.get('type') == 'user']
            self.assertEqual(user[0]['origin'], 'root')
        finally:
            chat._tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
