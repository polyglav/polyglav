import unittest
from pathlib import Path

from tests.helpers import make_chat


PLAN = """## Goal
Add the token cache.

## Instructions and constraints
Keep the public API unchanged.

## Findings
- src/auth.py holds the flow.

## Decisions
- Use an in-memory cache.

## Steps
1. Add the cache.
2. Run the auth tests.

## Role and team split
| Stage | Role | Model class | Permission carve | Skills | Output |
|---|---|---|---|---|---|
| 1 | programmer | fast | edit allow | - | code |

## Verification
Run the auth tests.

## Open questions
None.

## Next
write programmer
"""


class TestPlanBookkeeping(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat._init_tooling()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _write(self, content=PLAN, **kwargs):
        args = {'content': content, **kwargs}
        return self.chat._tool_registry.execute('plan_write', args)

    def test_plan_write_creates_file_and_attaches(self):
        result = self._write(next_role='programmer', team='programming')
        self.assertIn('Plan saved:', result)
        path = Path(self.chat.config.local_path.parent.parent,
                    self.chat.current_session.plan)
        self.assertTrue(path.exists())
        self.assertIn(self.chat.current_session.session_id, path.name)
        self.assertTrue(path.name.startswith('plan_'))
        text = path.read_text()
        self.assertIn('session:', text)
        self.assertIn('next_role: programmer', text)
        self.assertIn('team: programming', text)
        self.assertIn('## Goal', text)

    def test_plan_write_requires_sections(self):
        result = self._write('## Goal\nOnly a goal.\n')
        self.assertTrue(result.startswith('Error:'))
        self.assertIn('Instructions and constraints', result)
        self.assertEqual(self.chat.current_session.plan, '')

    def test_plan_write_appends_revision(self):
        self._write()
        result = self._write('Tighten the cache size.')
        self.assertIn('Plan updated:', result)
        path = Path(self.chat.config.local_path.parent.parent,
                    self.chat.current_session.plan)
        text = path.read_text()
        self.assertIn('## Revision 1', text)
        self.assertIn('Tighten the cache size.', text)

    def test_plan_write_replace_rewrites(self):
        self._write()
        result = self._write(PLAN.replace('in-memory cache',
                                          'file-backed cache'),
                             replace=True)
        self.assertIn('Plan updated:', result)
        path = Path(self.chat.config.local_path.parent.parent,
                    self.chat.current_session.plan)
        text = path.read_text()
        self.assertNotIn('## Revision', text)
        self.assertIn('file-backed cache', text)

    def test_plan_context_injected(self):
        self._write()
        messages = self.chat._provider_messages()
        block = '\n'.join(m['content'] for m in messages
                          if m.get('role') == 'system')
        self.assertIn('Internal plan:', block)
        self.assertIn('## Goal', block)

    def test_plan_propagates_to_sub_engine(self):
        self._write()
        sub = self.chat._new_sub_engine('', task='do it')
        self.assertEqual(sub.current_session.plan,
                         self.chat.current_session.plan)

    def test_session_plan_round_trip(self):
        self._write()
        self.chat.sessions.save(self.chat.current_session)
        loaded = self.chat.sessions.read(
            self.chat.current_session.session_name)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.plan, self.chat.current_session.plan)

    def test_plan_write_visible_in_read(self):
        names = {tool['function']['name']
                 for tool in self.chat._tool_schema()}
        self.assertIn('plan_write', names)


if __name__ == '__main__':
    unittest.main()
