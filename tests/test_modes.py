import json
import tempfile
import unittest
from pathlib import Path

from polyglav.config import Config
from polyglav.modes import (instructions_file_section, merge_policy, mode_list,
                          resolve_mode, system_instruction)


def make_config(data: dict | None = None) -> Config:
    tmp = tempfile.TemporaryDirectory()
    config_dir = Path(tmp.name) / '.polyglav'
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_dir / 'config.json', 'w') as f:
        json.dump(data or {}, f)
    config = Config(path=tmp.name)
    config._tmp = tmp
    return config


class TestModes(unittest.TestCase):

    def test_default_mode_is_build(self):
        config = make_config()
        try:
            mode, names = resolve_mode(config)
            self.assertEqual(mode.name, 'build')
            self.assertIn('plan', names)
        finally:
            config._tmp.cleanup()

    def test_plan_mode_resolves(self):
        config = make_config({'mode': 'plan'})
        try:
            mode, _ = resolve_mode(config)
            self.assertEqual(mode.name, 'plan')
            self.assertEqual(mode.permissions, {'edit': 'deny', 'bash': 'deny'})
            self.assertIn('plan mode', mode.instruction)
        finally:
            config._tmp.cleanup()

    def test_unknown_mode_falls_back_to_build(self):
        config = make_config({'mode': 'nosuch'})
        try:
            mode, _ = resolve_mode(config)
            self.assertEqual(mode.name, 'build')
        finally:
            config._tmp.cleanup()

    def test_custom_mode_from_config(self):
        config = make_config({
            'mode': 'review',
            'modes': {
                'review': {
                    'system_prompt': 'You review code only.',
                    'tool_permission': {'bash': 'deny'},
                    'tools.deny': ['write_file'],
                },
            },
        })
        try:
            mode, names = resolve_mode(config)
            self.assertEqual(mode.name, 'review')
            self.assertEqual(mode.instruction, 'You review code only.')
            self.assertEqual(mode.permissions, {'bash': 'deny'})
            self.assertEqual(mode.deny, ['write_file'])
            self.assertIn('review', names)
        finally:
            config._tmp.cleanup()

    def test_merge_policy_permission_override_wins(self):
        config = make_config({
            'mode': 'plan',
            'tool_permission': {'edit': 'allow', 'read': 'allow'},
        })
        try:
            permissions, allow, deny = merge_policy(config)
            self.assertEqual(permissions['edit'], 'deny')
            self.assertEqual(permissions['bash'], 'deny')
            self.assertEqual(permissions['read'], 'allow')
        finally:
            config._tmp.cleanup()

    def test_merge_policy_deny_appends(self):
        config = make_config({
            'mode': 'plan',
            'tools.deny': ['web_search'],
        })
        try:
            _, allow, deny = merge_policy(config)
            self.assertIn('web_search', deny)
            self.assertEqual(deny, ['web_search'])
        finally:
            config._tmp.cleanup()

    def test_merge_policy_mode_deny_joins_base(self):
        config = make_config({
            'modes': {
                'review': {'tools.deny': ['write_file']},
            },
            'tools.deny': ['web_search'],
            'mode': 'review',
        })
        try:
            _, _, deny = merge_policy(config)
            self.assertEqual(sorted(deny), ['web_search', 'write_file'])
        finally:
            config._tmp.cleanup()

    def test_merge_policy_allow_replaces_when_mode_sets(self):
        config = make_config({
            'modes': {
                'review': {'tools.allow': ['read_file', 'grep']},
            },
            'tools.allow': ['list_dir'],
            'mode': 'review',
        })
        try:
            _, allow, _ = merge_policy(config)
            self.assertEqual(sorted(allow), ['grep', 'read_file'])
        finally:
            config._tmp.cleanup()

    def test_merge_policy_base_allow_kept_without_mode_allow(self):
        config = make_config({'tools.allow': ['list_dir']})
        try:
            _, allow, _ = merge_policy(config)
            self.assertEqual(allow, ['list_dir'])
        finally:
            config._tmp.cleanup()

    def test_system_instruction_combines_prompt_and_mode(self):
        config = make_config({'system_prompt': 'You are helpful.', 'mode': 'plan'})
        try:
            text = system_instruction(config)
            self.assertIn('You are helpful.', text)
            self.assertIn('plan mode', text)
        finally:
            config._tmp.cleanup()

    def test_system_instruction_empty_when_unset(self):
        config = make_config()
        try:
            self.assertEqual(system_instruction(config), '')
        finally:
            config._tmp.cleanup()

    def test_mode_list_sorted(self):
        config = make_config({'modes': {'zeta': {}, 'alpha': {}}})
        try:
            specs = mode_list(config)
            self.assertEqual([s.name for s in specs],
                             ['alpha', 'build', 'plan', 'zeta'])
        finally:
            config._tmp.cleanup()

    def test_instructions_file_section_loads_worktree_file(self):
        config = make_config({'project_instructions': 'AGENTS.md'})
        try:
            (config.local_path.parent.parent / 'AGENTS.md').write_text(
                '# Conventions\n\nUse stdlib only.\n')
            text = instructions_file_section(config)
            self.assertIn('Project instructions (AGENTS.md)', text)
            self.assertIn('Use stdlib only.', text)
        finally:
            config._tmp.cleanup()

    def test_instructions_file_section_absent_file_returns_empty(self):
        config = make_config({'project_instructions': 'MISSING.md'})
        try:
            self.assertEqual(instructions_file_section(config), '')
        finally:
            config._tmp.cleanup()

    def test_instructions_file_section_disabled_when_unset(self):
        config = make_config({'project_instructions': ''})
        try:
            self.assertEqual(instructions_file_section(config), '')
        finally:
            config._tmp.cleanup()

    def test_instructions_file_section_default_is_agents_md(self):
        config = make_config()
        try:
            (config.local_path.parent.parent / 'AGENTS.md').write_text('# Hi\n')
            self.assertIn('Project instructions (AGENTS.md)',
                          instructions_file_section(config))
        finally:
            config._tmp.cleanup()

    def test_instructions_file_section_truncates_large(self):
        config = make_config()
        try:
            (config.local_path.parent.parent / 'AGENTS.md').write_text(
                'x\n' * 50000)
            text = instructions_file_section(config, max_chars=1000)
            self.assertIn('... (truncated)', text)
            self.assertLess(len(text), 2000)
        finally:
            config._tmp.cleanup()


if __name__ == '__main__':
    unittest.main()