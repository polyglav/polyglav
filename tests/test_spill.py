import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from polyglav import spill
from polyglav.engine import Engine
from polyglav.sessions import turns
from polyglav.sessions.manager import SessionManager
from tests.helpers import make_chat


class TestSpill(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tmp.name) / '.polyglav' / 'sessions'
        self.sessions_dir.mkdir(parents=True)
        self.session = 'ses_test_abc123'

    def tearDown(self):
        spill.delete(self.session, [spill.temp_root()])
        self.tmp.cleanup()

    def test_temp_root_is_system_temp(self):
        root = spill.temp_root()
        self.assertEqual(root.name, 'polyglav')
        self.assertTrue(root.is_absolute())

    def test_write_and_resolve_absolute_ref(self):
        ref = spill.write(spill.temp_root(), self.session, 1, 2,
                          'full body', self.sessions_dir)
        path = Path(ref)
        self.assertTrue(path.is_absolute())
        self.assertEqual(path.read_text(), 'full body')
        self.assertEqual(spill.resolve(ref, self.sessions_dir), 'full body')

    def test_write_persistent_ref_is_worktree_relative(self):
        root = Path(self.tmp.name) / '.polyglav' / 'tmp'
        ref = spill.write(root, self.session, 3, 4, 'body', self.sessions_dir)
        self.assertEqual(ref, f'.polyglav/tmp/{self.session}/3_4.txt')
        self.assertEqual(spill.resolve(ref, self.sessions_dir), 'body')

    def test_prune_removes_oldest_files(self):
        root = Path(self.tmp.name) / 'spill'
        first = root / self.session / 'a.txt'
        first.parent.mkdir(parents=True)
        first.write_text('x' * 40)
        second = root / self.session / 'b.txt'
        second.write_text('y' * 40)
        os.utime(first, (1, 1))
        spill.prune(root, 50)
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())

    def test_engine_uses_temp_by_default(self):
        chat = make_chat()
        try:
            part = chat.current_session.add_tool('file_read', {})
            ref = chat._store_tool_output(part, 'body', 1, 0)
            self.assertTrue(Path(ref).is_absolute())
            self.assertIn('polyglav', Path(ref).parts)
            self.assertEqual(part['ref'], ref)
        finally:
            spill.delete(chat.current_session.session_name, [spill.temp_root()])
            chat._tmp.cleanup()

    def test_engine_persists_when_enabled(self):
        chat = make_chat()
        try:
            chat.config.set('tools_output_spill', True)
            part = chat.current_session.add_tool('file_read', {})
            ref = chat._store_tool_output(part, 'body', 1, 0)
            self.assertEqual(
                ref, f'.polyglav/tmp/{chat.current_session.session_name}/1_0.txt')
            self.assertEqual(chat.resolve_tool_ref(ref), 'body')
        finally:
            spill.delete(chat.current_session.session_name,
                         chat.tool_output_roots())
            chat._tmp.cleanup()

    def test_engine_uses_configured_dir(self):
        chat = make_chat()
        try:
            chat.config.set('tools_output_spill', True)
            chat.config.set('tools_output_dir', 'artifacts/tools')
            part = chat.current_session.add_tool('file_read', {})
            ref = chat._store_tool_output(part, 'body', 1, 0)
            self.assertEqual(
                ref, f'artifacts/tools/{chat.current_session.session_name}/1_0.txt')
            self.assertTrue(
                (chat.sessions.sessions_dir.parent.parent / ref).exists())
        finally:
            spill.delete(chat.current_session.session_name,
                         chat.tool_output_roots())
            chat._tmp.cleanup()

    def test_auto_save_writes_ref_and_dropped_marker(self):
        chat = make_chat()
        try:
            chat.config.set('tools_output_spill', True)
            part = chat.current_session.add_tool('fetch_page', {'url': 'x'})
            turns.finish_tool(part, 'page body')
            Engine.session_auto_save(chat)
            path = (chat.sessions.sessions_dir.parent / 'tmp'
                    / chat.current_session.session_name / '1_0.txt')
            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(), 'page body')
            with open(chat.sessions.sessions_dir
                      / f'{chat.current_session.session_name}.json') as f:
                data = json.load(f)
            tool = data['turns'][0]['parts'][0]
            self.assertEqual(tool['ref'],
                             f'.polyglav/tmp/{chat.current_session.session_name}/1_0.txt')
            self.assertEqual(tool['dropped']['ref'], tool['ref'])
            self.assertIn('full output:', tool['output'])
        finally:
            spill.delete(chat.current_session.session_name,
                         chat.tool_output_roots())
            chat._tmp.cleanup()

    def test_print_renders_stored_output(self):
        chat = make_chat()
        try:
            part = chat.current_session.add_tool('fetch_page', {})
            ref = chat._store_tool_output(part, 'full page body', 1, 0)
            turns.finish_tool(part, 'marker')
            part['dropped'] = {'reason': 'drop', 'ref': ref}
            from polyglav.sessions.render import render_turn
            turn = chat.current_session.turns[0]
            out = render_turn(turn, resolve=chat.resolve_tool_ref)
            self.assertIn('full page body', out)
        finally:
            spill.delete(chat.current_session.session_name, [spill.temp_root()])
            chat._tmp.cleanup()

    def test_delete_removes_spill_dirs(self):
        manager = SessionManager(self.sessions_dir)
        manager.create()
        manager.save()
        session = manager.current.session_name
        temp_dir = spill.temp_root() / session
        temp_dir.mkdir(parents=True)
        (temp_dir / '1_0.txt').write_text('x')
        persistent = self.sessions_dir.parent / 'tmp' / session
        persistent.mkdir(parents=True)
        (persistent / '1_0.txt').write_text('x')
        self.assertTrue(manager.delete(
            session, extra_dirs=[spill.temp_root(),
                                 self.sessions_dir.parent / 'tmp']))
        self.assertFalse(temp_dir.exists())
        self.assertFalse(persistent.exists())


if __name__ == '__main__':
    unittest.main()
