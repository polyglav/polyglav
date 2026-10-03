import json
import tempfile
import unittest
from pathlib import Path

from polyglav.config import Config
from polyglav.modes import (PROMPT_COLORS, instructions_file_section,
                          merge_policy, mode_color, mode_list, resolve_mode,
                          system_instruction, unknown_mode)


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

    def test_default_mode_is_read(self):
        config = make_config()
        try:
            mode, names = resolve_mode(config)
            self.assertEqual(mode.name, 'read')
            self.assertIn('write', names)
        finally:
            config._tmp.cleanup()

    def test_read_mode_resolves(self):
        config = make_config({'mode': 'read'})
        try:
            mode, _ = resolve_mode(config)
            self.assertEqual(mode.name, 'read')
            self.assertEqual(mode.permissions, {'edit': 'deny', 'bash': 'deny'})
            self.assertIn('read mode', mode.instruction)
        finally:
            config._tmp.cleanup()

    def test_unknown_mode_falls_back_to_read(self):
        config = make_config({'mode': 'nosuch'})
        try:
            mode, _ = resolve_mode(config)
            self.assertEqual(mode.name, 'read')
        finally:
            config._tmp.cleanup()

    def test_unknown_mode_reports_name(self):
        config = make_config({'mode': 'nosuch'})
        try:
            self.assertEqual(unknown_mode(config), 'nosuch')
            self.assertIsNone(unknown_mode(make_config()))
        finally:
            config._tmp.cleanup()

    def test_known_overridden_mode_spec(self):
        config = make_config({'mode': 'write',
                              'modes': {'write': {'system_prompt': 'Be bold.'}}})
        try:
            mode, names = resolve_mode(config)
            self.assertEqual(mode.name, 'write')
            self.assertEqual(mode.instruction, 'Be bold.')
            self.assertIn('write', names)
        finally:
            config._tmp.cleanup()

    def test_merge_policy_permission_override_wins(self):
        config = make_config({
            'mode': 'read',
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
            'mode': 'read',
            'tools.deny': ['web_search'],
        })
        try:
            _, allow, deny = merge_policy(config)
            self.assertIn('web_search', deny)
            self.assertEqual(deny, ['web_search'])
        finally:
            config._tmp.cleanup()

    def test_system_instruction_combines_prompt_and_mode(self):
        config = make_config({'system_prompt': 'You are helpful.', 'mode': 'read'})
        try:
            text = system_instruction(config)
            self.assertIn('You are helpful.', text)
            self.assertIn('read mode', text)
        finally:
            config._tmp.cleanup()

    def test_system_instruction_read_mode_default(self):
        config = make_config()
        try:
            self.assertIn('read mode', system_instruction(config))
        finally:
            config._tmp.cleanup()

    def test_mode_list_sorted(self):
        config = make_config({'modes': {'write': {}, 'read': {}}})
        try:
            specs = mode_list(config)
            self.assertEqual([s.name for s in specs], ['read', 'write'])
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


class TestModeColor(unittest.TestCase):

    def test_write_mode_is_orange(self):
        config = make_config({'mode': 'write'})
        try:
            mode, _ = resolve_mode(config)
            self.assertEqual(mode_color(mode), PROMPT_COLORS['orange'])
        finally:
            config._tmp.cleanup()

    def test_read_mode_is_cyan(self):
        config = make_config({'mode': 'read'})
        try:
            mode, _ = resolve_mode(config)
            self.assertEqual(mode_color(mode), PROMPT_COLORS['cyan'])
        finally:
            config._tmp.cleanup()

    def test_explicit_color_wins(self):
        config = make_config({
            'mode': 'write',
            'modes': {'write': {'tool_permission': {}, 'color': 'cyan'}},
        })
        try:
            mode, _ = resolve_mode(config)
            self.assertEqual(mode_color(mode), PROMPT_COLORS['cyan'])
        finally:
            config._tmp.cleanup()

    def test_read_only_mode_defaults_cyan(self):
        config = make_config({
            'mode': 'write',
            'modes': {'write': {'tool_permission': {'edit': 'deny',
                                                    'bash': 'deny'},
                                'color': ''}},
        })
        try:
            mode, _ = resolve_mode(config)
            self.assertEqual(mode_color(mode), PROMPT_COLORS['cyan'])
        finally:
            config._tmp.cleanup()

    def test_unknown_color_name_falls_back_by_posture(self):
        config = make_config({
            'mode': 'write',
            'modes': {'write': {'tool_permission': {'bash': 'deny'},
                                'color': 'magenta'}},
        })
        try:
            mode, _ = resolve_mode(config)
            self.assertEqual(mode_color(mode), PROMPT_COLORS['orange'])
        finally:
            config._tmp.cleanup()


if __name__ == '__main__':
    unittest.main()