import unittest
import tempfile
from pathlib import Path

from polyglav.tools.policy import ToolPolicy


class TestToolPolicy(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def policy(self, **kw):
        return ToolPolicy(worktree=self.root, **kw)

    def test_default_allow_inside_worktree(self):
        p = self.policy(permissions={'read': 'allow'})
        inside = self.root / 'file.txt'
        self.assertEqual(p.action('read_file', 'read', str(inside)), 'allow')

    def test_external_directory_escalates_to_ask(self):
        p = self.policy(permissions={'read': 'allow'})
        outside = self.root.parent / 'elsewhere' / 'file.txt'
        self.assertEqual(p.action('read_file', 'read', str(outside)), 'ask')

    def test_external_directory_without_path_stays_allow(self):
        p = self.policy(permissions={'read': 'allow'})
        self.assertEqual(p.action('read_file', 'read', None), 'allow')

    def test_deny_list_wins(self):
        p = self.policy(permissions={'read': 'allow'}, deny=['read_file'])
        self.assertEqual(p.action('read_file', 'read', str(self.root)), 'deny')

    def test_allow_list_whitelists(self):
        p = self.policy(permissions={'read': 'allow', 'list': 'allow'}, allow=['list_dir'])
        self.assertEqual(p.action('read_file', 'read', str(self.root)), 'deny')
        self.assertEqual(p.action('list_dir', 'list', str(self.root)), 'allow')

    def test_ask_permission_key(self):
        p = self.policy(permissions={'bash': 'ask'})
        self.assertEqual(p.action('run_command', 'bash'), 'ask')

    def test_unknown_permission_defaults_to_ask(self):
        p = self.policy(permissions={})
        self.assertEqual(p.action('some_tool', 'nope'), 'ask')

    def test_deny_never_escalates_to_ask(self):
        p = self.policy(permissions={'edit': 'deny'})
        outside = self.root.parent / 'elsewhere' / 'f.txt'
        self.assertEqual(p.action('write_file', 'edit', str(outside)), 'deny')

    def test_needs_confirm(self):
        p = self.policy(permissions={'bash': 'ask', 'edit': 'allow'})
        self.assertTrue(p.needs_confirm('run_command', 'bash'))
        self.assertFalse(p.needs_confirm('write_file', 'edit', str(self.root / 'f.txt')))
        self.assertTrue(p.needs_confirm(
            'write_file', 'edit', str(self.root.parent / 'f.txt')))

    def test_allowed(self):
        p = self.policy(permissions={}, deny=['run_command'])
        self.assertFalse(p.allowed('run_command'))
        self.assertTrue(p.allowed('read_file'))
        whitelist = self.policy(permissions={}, allow=['read_file'])
        self.assertTrue(whitelist.allowed('read_file'))
        self.assertFalse(whitelist.allowed('list_dir'))

    def test_allowed_with_permission_key_respects_category_deny(self):
        p = self.policy(permissions={'edit': 'deny', 'bash': 'deny'})
        self.assertFalse(p.allowed('write_file', 'edit'))
        self.assertFalse(p.allowed('run_command', 'bash'))
        self.assertTrue(p.allowed('read_file', 'read'))
        self.assertTrue(p.allowed('web_search', 'web'))

    def test_allowed_without_permission_key_ignores_category(self):
        p = self.policy(permissions={'edit': 'deny'})
        self.assertTrue(p.allowed('write_file'))

    def test_allowed_name_deny_beats_category_allow(self):
        p = self.policy(permissions={'edit': 'allow'}, deny=['write_file'])
        self.assertFalse(p.allowed('write_file', 'edit'))

    def test_relative_path_against_worktree(self):
        import os
        p = self.policy(permissions={'read': 'allow'})
        cwd = os.getcwd()
        try:
            os.chdir(self.root)
            self.assertEqual(p.action('read_file', 'read', 'file.txt'), 'allow')
        finally:
            os.chdir(cwd)

    def test_expands_user(self):
        import os
        home = Path(os.path.expanduser('~'))
        if home == self.root.resolve():
            self.skipTest('home equals worktree')
        p = self.policy(permissions={'read': 'allow'})
        self.assertEqual(p.action('read_file', 'read', '~/x.txt'), 'ask')

    def test_resolver_refines_action(self):
        p = self.policy(permissions={'delegate': 'ask'},
                        resolvers={'delegate': lambda args: 'allow'
                                   if args.get('role') == 'known' else 'deny'})
        self.assertEqual(p.action('delegate', 'delegate', args={'role': 'known'}),
                         'allow')
        self.assertEqual(p.action('delegate', 'delegate', args={'role': 'temp'}),
                         'deny')

    def test_resolver_ignored_without_args(self):
        p = self.policy(permissions={'delegate': 'ask'},
                        resolvers={'delegate': lambda args: 'allow'})
        self.assertEqual(p.action('delegate', 'delegate', args=None), 'ask')

    def test_resolver_does_not_override_deny_list(self):
        p = self.policy(permissions={}, deny=['delegate'],
                        resolvers={'delegate': lambda args: 'allow'})
        self.assertEqual(p.action('delegate', 'delegate',
                                  args={'role': 'known'}), 'deny')

    def test_resolver_ignores_invalid_value(self):
        p = self.policy(permissions={'delegate': 'ask'},
                        resolvers={'delegate': lambda args: 'bogus'})
        self.assertEqual(p.action('delegate', 'delegate',
                                  args={'role': 'x'}), 'ask')

    def test_allowed_ignores_resolver(self):
        p = self.policy(permissions={'delegate': 'ask'},
                        resolvers={'delegate': lambda args: 'deny'})
        self.assertTrue(p.allowed('delegate', 'delegate'))


if __name__ == '__main__':
    unittest.main()
