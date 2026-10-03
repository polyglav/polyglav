import unittest

from tests.helpers import make_chat
from tests.test_engine import make_engine


class TestAssistantRoot(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def test_bundled_assistant_definition(self):
        assistant = self.chat.roles.find('assistant')
        self.assertIsNotNone(assistant)
        self.assertIn('assistant', assistant.system_prompt.lower())
        self.assertIn('composer', assistant.system_prompt.lower())
        self.assertEqual(assistant.tags, ['management'])
        self.assertEqual(assistant.tool_permission, {})

    def test_repl_binds_assistant_by_default(self):
        self.chat._bind_assistant()
        self.assertEqual(self.chat.role, 'assistant')
        self.assertEqual(self.chat.current_session.role, 'assistant')
        prompt = self.chat.config.get('system_prompt')
        self.assertIn('single point of contact', prompt)
        messages = self.chat._provider_messages()
        system = ' '.join(m['content'] for m in messages
                          if m.get('role') == 'system')
        self.assertIn('single point of contact', system)

    def test_assistant_disabled(self):
        chat = make_chat({'assistant': False})
        try:
            chat._bind_assistant()
            self.assertEqual(chat.config.get('system_prompt'), '')
            self.assertEqual(chat.role, '')
        finally:
            chat._tmp.cleanup()

    def test_explicit_prompt_wins(self):
        chat = make_chat({'system_prompt': 'Custom root instructions.'})
        try:
            chat._bind_assistant()
            self.assertEqual(chat.config.get('system_prompt'),
                             'Custom root instructions.')
        finally:
            chat._tmp.cleanup()

    def test_assistant_role_rebind_applies_type(self):
        chat = make_chat({'assistant_role': 'composer'})
        try:
            chat._bind_assistant()
            self.assertEqual(chat.role, 'composer')
            self.assertEqual(chat.current_session.role, 'composer')
            self.assertIn('composer', chat.config.get('system_prompt').lower())
            permissions = chat.config.get('tool_permission')
            self.assertEqual(permissions['edit'], 'deny')
            self.assertEqual(permissions['catalog'], 'allow')
        finally:
            chat._tmp.cleanup()

    def test_unknown_assistant_role_is_noop(self):
        chat = make_chat({'assistant_role': 'ghost'})
        try:
            chat._bind_assistant()
            self.assertEqual(chat.config.get('system_prompt'), '')
            self.assertEqual(chat.role, '')
        finally:
            chat._tmp.cleanup()

    def test_assistant_can_delegate(self):
        self.chat.config.set('mode', 'write')
        self.chat._bind_assistant()
        self.chat._init_tooling()
        policy = self.chat._tool_policy
        self.assertEqual(
            policy.action('call', 'call', None,
                          {'role': 'composer', 'task': 't'}), 'allow')
        self.assertEqual(
            policy.action('catalog', 'catalog', None, {'action': 'list'}),
            'allow')

    def test_headless_engine_not_bound(self):
        engine = make_engine()
        try:
            self.assertEqual(engine.config.get('system_prompt'), '')
        finally:
            engine._tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
