import io
import unittest
from pathlib import Path
from unittest.mock import patch

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


class TestPlanCommands(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat._init_tooling()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def _write(self):
        return self.chat._tool_registry.execute(
            'plan_write', {'content': PLAN, 'next_role': 'programmer'})

    def test_plan_without_a_plan(self):
        self.assertIn('No plan for this session', self._dispatch('/plan'))

    def test_plan_shows_current(self):
        self._write()
        output = self._dispatch('/plan')
        self.assertIn('plan_', output)
        self.assertIn('## Goal', output)

    def test_plans_lists_and_shows(self):
        self._write()
        output = self._dispatch('/plans')
        self.assertIn('plan_', output)
        self.assertIn('<-- attached', output)
        stem = Path(self.chat.current_session.plan).stem
        output = self._dispatch(f'/plans {stem}')
        self.assertIn('## Goal', output)

    def test_plan_off_detaches(self):
        self._write()
        self.assertIn('Plan detached', self._dispatch('/plan off'))
        self.assertEqual(self.chat.current_session.plan, '')

    def test_plan_use_attaches(self):
        plans = Path(self.chat.config.local_path.parent.parent,
                     '.polyglav', 'plans')
        plans.mkdir(parents=True, exist_ok=True)
        path = plans / 'plan_custom.md'
        path.write_text('## Goal\nCustom.\n')
        output = self._dispatch('/plan use .polyglav/plans/plan_custom.md')
        self.assertIn('Plan attached', output)
        self.assertTrue(self.chat.current_session.plan.endswith(
            'plan_custom.md'))

    def test_plans_empty(self):
        self.assertIn('No stored plans', self._dispatch('/plans'))

    def test_plan_unknown(self):
        self.assertIn('Plan not found', self._dispatch('/plans nope'))


if __name__ == '__main__':
    unittest.main()
