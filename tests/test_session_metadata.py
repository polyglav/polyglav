import unittest

from polyglav.sessions.manager import Session


class TestDerivedMetadata(unittest.TestCase):

    def test_title_is_first_user_prompt_collapsed(self):
        s = Session('s1')
        s.add_user('  Hello \n world  ')
        self.assertEqual(s.derived_title(), 'Hello world')

    def test_title_truncated_to_60(self):
        s = Session('s1')
        s.add_user('x' * 100)
        self.assertEqual(s.derived_title(), 'x' * 60)

    def test_title_skips_command_only_session(self):
        s = Session('s1')
        s.add_command('/help')
        self.assertEqual(s.derived_title(), '')

    def test_outcome_ok(self):
        s = Session('s1')
        s.add_user('hi')
        s.end_turn('ok')
        self.assertEqual(s.derived_outcome(), 'ok')

    def test_outcome_error_wins(self):
        s = Session('s1')
        s.add_user('a')
        s.end_turn('ok')
        s.add_user('b')
        s.end_turn('error')
        self.assertEqual(s.derived_outcome(), 'error')

    def test_idle_at_is_last_ended_turn(self):
        s = Session('s1')
        s.add_user('hi')
        s.end_turn('ok', ended_at='2026-01-02T00:00:00+00:00')
        self.assertEqual(s.derived_idle_at(), '2026-01-02T00:00:00+00:00')

    def test_idle_at_falls_back_to_updated_at(self):
        s = Session('s1')
        self.assertEqual(s.derived_idle_at(), s.updated_at)

    def test_derived_fields_not_stored(self):
        s = Session('s1')
        s.add_user('hi')
        s.end_turn('ok')
        d = s.to_dict()
        self.assertNotIn('title', d)
        self.assertNotIn('outcome', d)
        self.assertNotIn('idle_at', d)


if __name__ == '__main__':
    unittest.main()
