import unittest
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from polyglav.sessions import turns
from polyglav.sessions.manager import Session, SessionManager
from polyglav import get_version
from tests.helpers import make_chat


class TestSessionModel(unittest.TestCase):

    def test_to_dict_includes_tool_parts(self):
        s = Session('s1')
        s.add_user('hi')
        s.add_tool('web_search', {'query': 'x'})
        turns.finish_tool(s.turns[0]['parts'][-1], 'results here')
        d = s.to_dict()
        parts = d['turns'][0]['parts']
        self.assertEqual([p['type'] for p in parts], ['user', 'tool'])
        self.assertEqual(parts[1]['output'], 'results here')

    def test_end_turn_persists_telemetry(self):
        s = Session('s1')
        s.add_user('hi')
        s.end_turn('ok', usage={'prompt_tokens': 9}, context_tokens=11)
        turn = s.to_dict()['turns'][0]
        self.assertEqual(turn['usage'], {'prompt_tokens': 9})
        self.assertEqual(turn['context_tokens'], 11)

    def test_end_turn_persists_finish_reason(self):
        s = Session('s1')
        s.add_user('hi')
        s.end_turn('ok', finish_reason='stop')
        self.assertEqual(s.to_dict()['turns'][0]['finish_reason'], 'stop')

    def test_end_turn_omits_empty_finish_reason(self):
        s = Session('s1')
        s.add_user('hi')
        s.end_turn('ok')
        self.assertNotIn('finish_reason', s.to_dict()['turns'][0])

    def test_tool_part_stores_call_id_and_duration(self):
        s = Session('s1')
        s.add_user('hi')
        part = s.add_tool('web_search', {'query': 'x'}, call_id='call_abc')
        turns.finish_tool(part, 'result', duration=1.2)
        tool = s.to_dict()['turns'][0]['parts'][1]
        self.assertEqual(tool['call_id'], 'call_abc')
        self.assertEqual(tool['duration'], 1.2)

    def test_tool_part_omits_empty_call_id(self):
        s = Session('s1')
        s.add_user('hi')
        part = s.add_tool('web_search', {})
        turns.finish_tool(part, 'result')
        self.assertNotIn('call_id', s.to_dict()['turns'][0]['parts'][1])

    def test_max_chars_truncates_persisted_only(self):
        s = Session('s1')
        s.add_user('hi')
        part = s.add_tool('web_search', {})
        turns.finish_tool(part, 'x' * 100)
        d = s.to_dict(max_chars=20)
        tool = d['turns'][0]['parts'][1]
        self.assertTrue(tool['output'].startswith('x' * 20))
        self.assertIn('truncated from 100 chars', tool['output'])
        self.assertEqual(part['output'], 'x' * 100)

    def test_created_at_defaults_to_now(self):
        s = Session('s1')
        self.assertTrue(s.created_at)
        self.assertEqual(s.updated_at, s.created_at)

    def test_updated_at_bumped_on_turn(self):
        s = Session('s1', created_at='2026-01-01T00:00:00+00:00',
                    updated_at='2026-01-01T00:00:00+00:00')
        s.add_user('hi')
        self.assertEqual(s.created_at, '2026-01-01T00:00:00+00:00')
        self.assertNotEqual(s.updated_at, '2026-01-01T00:00:00+00:00')

    def test_metadata_in_to_dict(self):
        s = Session('s1')
        d = s.to_dict()
        self.assertIn('created_at', d)
        self.assertIn('updated_at', d)
        self.assertIn('turns', d)
        self.assertNotIn('messages', d)
        self.assertEqual(d['errors'], [])

    def test_role_defaults_empty_and_round_trips(self):
        s = Session('s1')
        self.assertEqual(s.role, '')
        s.role = 'assistant'
        d = s.to_dict()
        self.assertEqual(d['role'], 'assistant')
        self.assertEqual(Session.from_dict(d).role, 'assistant')

    def test_create_stamps_role(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            sm = SessionManager(Path(tmp.name))
            s = sm.create('writer_run', role='writer')
            self.assertEqual(s.role, 'writer')
            sm.save(s)
            self.assertEqual(sm.read('writer_run').role, 'writer')
        finally:
            tmp.cleanup()

    def test_version_defaults_empty_and_round_trips(self):
        s = Session('s1')
        self.assertEqual(s.version, '')
        s.version = '0.35.0'
        d = s.to_dict()
        self.assertEqual(d['version'], '0.35.0')
        self.assertEqual(Session.from_dict(d).version, '0.35.0')

    def test_create_stamps_version(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            sm = SessionManager(Path(tmp.name))
            s = sm.create('versioned_run')
            self.assertEqual(s.version, get_version())
            sm.save(s)
            self.assertEqual(sm.read('versioned_run').version, get_version())
        finally:
            tmp.cleanup()

    def test_missing_version_loads_empty(self):
        data = Session('s1').to_dict()
        del data['version']
        self.assertEqual(Session.from_dict(data).version, '')

    def test_mode_defaults_empty_and_round_trips(self):
        s = Session('s1')
        self.assertEqual(s.mode, '')
        s.mode = 'write'
        d = s.to_dict()
        self.assertEqual(d['mode'], 'write')
        self.assertEqual(Session.from_dict(d).mode, 'write')

    def test_missing_mode_loads_empty(self):
        data = Session('s1').to_dict()
        del data['mode']
        self.assertEqual(Session.from_dict(data).mode, '')

    def test_errors_round_trip(self):
        s = Session('s1')
        s.add_error(401, 'Unauthorized')
        d = s.to_dict()
        self.assertEqual(len(d['errors']), 1)
        self.assertEqual(d['errors'][0]['code'], 401)
        self.assertEqual(d['errors'][0]['message'], 'Unauthorized')
        s2 = Session.from_dict(d)
        self.assertEqual(s2.errors, d['errors'])

    def test_turn_index_and_status(self):
        s = Session('s1')
        s.add_user('a')
        s.end_turn('ok')
        s.add_user('b')
        self.assertEqual([t['index'] for t in s.turns], [1, 2])
        self.assertEqual(s.turns[0]['status'], 'ok')
        self.assertEqual(s.turns[1]['status'], 'running')
        self.assertTrue(s.turns[0]['started_at'])
        self.assertTrue(s.turns[0]['ended_at'])

    def test_turn_carries_meta(self):
        s = Session('s1')
        s.add_user('a', model='m', provider='p', mode='plan', reasoning='high')
        turn = s.turns[0]
        self.assertEqual(turn['model'], 'm')
        self.assertEqual(turn['provider'], 'p')
        self.assertEqual(turn['mode'], 'plan')
        self.assertEqual(turn['reasoning'], 'high')

    def test_permissions_persist_and_round_trip(self):
        s = Session('s1')
        s.add_permission('run_command', 'ask', 'granted', path='/tmp/x')
        s.add_permission('write_file', 'deny', 'denied', path='/tmp/a.md')
        d = s.to_dict()
        self.assertEqual(len(d['permissions']), 2)
        self.assertEqual(d['permissions'][0]['tool'], 'run_command')
        self.assertEqual(d['permissions'][0]['action'], 'ask')
        self.assertEqual(d['permissions'][0]['decision'], 'granted')
        self.assertEqual(d['permissions'][0]['path'], '/tmp/x')
        self.assertIn('timestamp', d['permissions'][0])
        s2 = Session.from_dict(d)
        self.assertEqual(s2.permissions, d['permissions'])

    def test_permission_without_path(self):
        s = Session('s1')
        s.add_permission('web_search', 'allow', 'granted')
        entry = s.permissions[0]
        self.assertNotIn('path', entry)

    def test_save_load_round_trip(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            sm = SessionManager(Path(tmp.name))
            s = sm.create('test_session')
            s.add_user('hi')
            part = s.add_tool('web_search', {'query': 'q'})
            turns.finish_tool(part, 'result')
            s.end_turn('ok')
            s.add_error(0, 'network')
            sm.save(s)
            loaded = sm.load('test_session')
            kinds = [p['type'] for p in loaded.turns[0]['parts']]
            self.assertEqual(kinds, ['user', 'tool'])
            self.assertEqual(loaded.turns[0]['parts'][1]['output'], 'result')
            self.assertEqual(loaded.errors, s.errors)
            self.assertEqual(loaded.created_at, s.created_at)
            self.assertEqual(loaded.updated_at, s.updated_at)
        finally:
            tmp.cleanup()

    def test_write_summary_creates_file(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            sm = SessionManager(Path(tmp.name))
            path = sm.write_summary('sess', 'BODY')
            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(), 'BODY\n')
            self.assertEqual(path.parent.name, 'summaries')
        finally:
            tmp.cleanup()

    def test_delete_removes_spill_dir(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            sm = SessionManager(Path(tmp.name) / '.polyglav' / 'sessions')
            s = sm.create('sess')
            sm.save(s)
            spill = sm.tmp_dir / 'sess' / '1_0.txt'
            spill.parent.mkdir(parents=True)
            spill.write_text('x')
            self.assertTrue(sm.delete('sess'))
            self.assertFalse(spill.parent.exists())
        finally:
            tmp.cleanup()

    def test_prune_tmp_removes_oldest_over_cap(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            sm = SessionManager(Path(tmp.name) / '.polyglav' / 'sessions')
            root = sm.tmp_dir / 'sess'
            root.mkdir(parents=True)
            old = root / 'old.txt'
            new = root / 'new.txt'
            old.write_text('a' * 60)
            new.write_text('b' * 60)
            os.utime(old, (1000, 1000))
            os.utime(new, (2000, 2000))
            sm.prune_tmp(60)
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())
        finally:
            tmp.cleanup()

    def test_prune_tmp_zero_is_unlimited(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            sm = SessionManager(Path(tmp.name) / '.polyglav' / 'sessions')
            root = sm.tmp_dir / 'sess'
            root.mkdir(parents=True)
            kept = root / 'a.txt'
            kept.write_text('x' * 100)
            sm.prune_tmp(0)
            self.assertTrue(kept.exists())
        finally:
            tmp.cleanup()

    def test_legacy_file_does_not_load(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            sm = SessionManager(Path(tmp.name))
            with open(sm.sessions_dir / 'legacy.json', 'w') as f:
                json.dump({'name': 'legacy',
                           'messages': [{'role': 'user', 'content': 'hi'}]}, f)
            self.assertIsNone(sm.read('legacy'))
            self.assertIsNone(sm.load('legacy'))
            self.assertIn('legacy', sm.list())
        finally:
            tmp.cleanup()

    def test_save_applies_max_chars_to_file(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            sm = SessionManager(Path(tmp.name))
            s = sm.create('cap')
            s.add_user('hi')
            part = s.add_tool('web_search', {})
            turns.finish_tool(part, 'x' * 50)
            sm.save(s, max_chars=10)
            with open(sm.sessions_dir / 'cap.json') as f:
                data = json.load(f)
            self.assertIn('truncated from 50 chars',
                          data['turns'][0]['parts'][1]['output'])
            self.assertEqual(part['output'], 'x' * 50)
        finally:
            tmp.cleanup()

    def test_to_dict_drops_listed_tool_content(self):
        s = Session('s1')
        s.add_user('hi')
        part = s.add_tool('fetch_page', {'url': 'x'})
        turns.finish_tool(part, 'huge page content' * 50)
        d = s.to_dict(drop_tools=['fetch_page'])
        tool = d['turns'][0]['parts'][1]
        self.assertIn('excluded from log', tool['output'])
        self.assertEqual(tool['dropped'],
                         {'reason': 'drop', 'original_chars': 850})
        self.assertEqual(part['output'], 'huge page content' * 50)

    def test_max_chars_records_dropped_provenance(self):
        s = Session('s1')
        s.add_user('hi')
        part = s.add_tool('web_search', {})
        turns.finish_tool(part, 'x' * 100)
        d = s.to_dict(max_chars=20)
        self.assertEqual(d['turns'][0]['parts'][1]['dropped'],
                         {'reason': 'max_chars', 'original_chars': 100})

    def test_to_dict_keeps_unlisted_tool_content(self):
        s = Session('s1')
        s.add_user('hi')
        part = s.add_tool('web_search', {})
        turns.finish_tool(part, 'search results')
        d = s.to_dict(drop_tools=['fetch_page'])
        tool = d['turns'][0]['parts'][1]
        self.assertEqual(tool['output'], 'search results')
        self.assertNotIn('dropped', tool)

    def test_spill_writes_dropped_output_and_ref(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            base = Path(tmp.name) / '.polyglav'
            s = Session('s1')
            s.add_user('hi')
            part = s.add_tool('fetch_page', {'url': 'x'})
            turns.finish_tool(part, 'full page body')
            calls = []

            def spill(name, text):
                path = base / 'tmp' / 's1' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                calls.append((name, text))
                return str(path.relative_to(base.parent))

            d = s.to_dict(drop_tools=['fetch_page'], spill=spill)
            tool = d['turns'][0]['parts'][1]
            self.assertEqual(tool['dropped']['ref'],
                             '.polyglav/tmp/s1/1_1.txt')
            self.assertEqual(calls, [('1_1.txt', 'full page body')])
            self.assertTrue((base / 'tmp' / 's1' / '1_1.txt').exists())
        finally:
            tmp.cleanup()

    def test_spill_for_capped_output(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            base = Path(tmp.name) / '.polyglav'
            s = Session('s1')
            s.add_user('hi')
            part = s.add_tool('web_search', {})
            turns.finish_tool(part, 'x' * 50)

            def spill(name, text):
                path = base / 'tmp' / 's1' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                return str(path.relative_to(base.parent))

            d = s.to_dict(max_chars=10, spill=spill)
            dropped = d['turns'][0]['parts'][1]['dropped']
            self.assertEqual(dropped['reason'], 'max_chars')
            self.assertEqual(dropped['ref'], '.polyglav/tmp/s1/1_1.txt')
            self.assertEqual((base / 'tmp' / 's1' / '1_1.txt').read_text(),
                             'x' * 50)
        finally:
            tmp.cleanup()

    def test_no_spill_ref_when_spill_is_none(self):
        s = Session('s1')
        s.add_user('hi')
        part = s.add_tool('fetch_page', {'url': 'x'})
        turns.finish_tool(part, 'page body')
        d = s.to_dict(drop_tools=['fetch_page'])
        self.assertNotIn('ref', d['turns'][0]['parts'][1]['dropped'])

    def test_existing_dropped_ref_is_reused_without_spill(self):
        s = Session('s1')
        s.add_user('hi')
        part = s.add_tool('fetch_page', {'url': 'x'})
        turns.finish_tool(part, 'page body')
        part['output'] = 'marker'
        part['dropped'] = {'reason': 'drop', 'original_chars': 9,
                           'ref': '.polyglav/tmp/s1/1_1.txt'}
        calls = []
        d = s.to_dict(drop_tools=['fetch_page'],
                      spill=lambda name, text: calls.append(name) or 'new')
        self.assertEqual(calls, [])
        dropped = d['turns'][0]['parts'][1]['dropped']
        self.assertEqual(dropped['ref'], '.polyglav/tmp/s1/1_1.txt')

    def test_read_does_not_switch_current(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            sm = SessionManager(Path(tmp.name))
            s = sm.create('alpha')
            s.add_user('hi')
            sm.save(s)
            sm.create('other')
            current = sm.current
            loaded = sm.read('alpha')
            self.assertEqual(loaded.session_name, 'alpha')
            self.assertIs(sm.current, current)
        finally:
            tmp.cleanup()


class TestSessionLogLoop(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _make_tool_call(self, name='web_search', args='{"query": "test"}'):
        return [{
            'id': 'call_test123',
            'type': 'function',
            'function': {'name': name, 'arguments': args},
        }]

    def _run(self):
        with patch('sys.stdout', new=io.StringIO()):
            self.chat._agent_loop()

    def _parts(self, kind):
        return [p for t in self.chat.current_session.turns
                for p in t.get('parts') or [] if p['type'] == kind]

    def _search_service(self):
        return self.chat._plugin_manager.service('search')

    def test_thinking_before_tool_call_persisted(self):
        self.chat.provider.chat.side_effect = [
            [
                {'type': 'thinking', 'content': 'I need to search.'},
                {'type': 'tool_calls', 'tool_calls': self._make_tool_call()},
            ],
            [
                {'type': 'token', 'content': 'Final.'},
                {'type': 'done', 'reason': 'stop'},
            ],
        ]
        with patch.object(self._search_service(), 'search', return_value=[
            {'title': 'T', 'url': 'http://x.com', 'snippet': 'S'}
        ]):
            self._run()
        thinking = self._parts('thinking')
        tools = self._parts('tool')
        self.assertEqual(thinking[0]['text'], 'I need to search.')
        self.assertEqual(tools[0]['name'], 'web_search')
        self.assertEqual(tools[0]['input'], {'query': 'test'})
        self.assertEqual(self._parts('text')[-1]['text'], 'Final.')

    def test_stop_reason_persisted_on_turn(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'token', 'content': 'Hi.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        self._run()
        self.assertEqual(self.chat.current_session.turns[0]['finish_reason'],
                         'stop')

    def test_tool_part_carries_call_id_and_duration(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._make_tool_call()}],
            [{'type': 'token', 'content': 'Final.'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        with patch.object(self._search_service(), 'search', return_value=[
            {'title': 'T', 'url': 'http://x.com', 'snippet': 'S'}
        ]):
            self._run()
        tool = self._parts('tool')[0]
        self.assertEqual(tool['call_id'], 'call_test123')
        self.assertIn('duration', tool)

    def test_auto_save_spills_when_enabled(self):
        self.chat.config.set('tools_output_spill', True)
        session = self.chat.current_session
        part = session.add_tool('fetch_page', {'url': 'x'})
        turns.finish_tool(part, 'page body')
        type(self.chat).session_auto_save(self.chat)
        base = self.chat.sessions.sessions_dir.parent
        path = base / 'tmp' / session.session_name / '1_0.txt'
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), 'page body')
        with open(self.chat.sessions.sessions_dir
                  / f'{session.session_name}.json') as f:
            data = json.load(f)
        dropped = data['turns'][0]['parts'][0]['dropped']
        self.assertEqual(
            dropped['ref'],
            f'.polyglav/tmp/{session.session_name}/1_0.txt')

    def test_tool_analysis_off_by_default(self):
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._make_tool_call()}],
            [{'type': 'token', 'content': 'Final.'}, {'type': 'done', 'reason': 'stop'}],
        ]
        with patch.object(self._search_service(), 'search', return_value=[
            {'title': 'T', 'url': 'http://x.com', 'snippet': 'S'}
        ]):
            self._run()
        self.chat.provider.chat_nonstreaming.assert_not_called()
        self.assertIsNone(self._parts('tool')[0]['analysis'])

    def test_tool_analysis_generates_insight_when_enabled(self):
        self.chat.config.set('tool_analysis', True)
        self.chat.provider.chat_nonstreaming.return_value = {
            'role': 'assistant',
            'content': 'Found pages about Python.',
            'tool_calls': None,
            'finish_reason': 'stop',
        }
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._make_tool_call()}],
            [{'type': 'token', 'content': 'Final.'}, {'type': 'done', 'reason': 'stop'}],
        ]
        with patch.object(self._search_service(), 'search', return_value=[
            {'title': 'T', 'url': 'http://x.com', 'snippet': 'S'}
        ]):
            self._run()
        self.chat.provider.chat_nonstreaming.assert_called_once()
        self.assertEqual(self._parts('tool')[0]['analysis'],
                         'Found pages about Python.')

    def test_tool_analysis_skipped_for_cancelled(self):
        self.chat.config.set('tool_analysis', True)
        self.chat._run_tool = unittest.mock.MagicMock(
            return_value='[cancelled] User declined the web_search call')
        self.chat.provider.chat.side_effect = [
            [{'type': 'tool_calls', 'tool_calls': self._make_tool_call()}],
            [{'type': 'token', 'content': 'Final.'}, {'type': 'done', 'reason': 'stop'}],
        ]
        self._run()
        self.chat.provider.chat_nonstreaming.assert_not_called()
        self.assertIsNone(self._parts('tool')[0]['analysis'])

    def test_session_new_stamps_current_role(self):
        self.chat.role = 'assistant'
        with patch('sys.stdout', new=io.StringIO()):
            self.chat.registry.dispatch('/session new role_test')
        self.assertEqual(self.chat.current_session.role, 'assistant')


class TestCompactSession(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat.config.set('mode', 'write')
        self.chat.config.apply('modes', {'read': {}, 'write': {}})

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _fill(self, count):
        for i in range(count):
            self.chat.current_session.add_user(f'msg {i}')
            self.chat.current_session.add_text(f'answer {i}')
            self.chat.current_session.end_turn('ok')

    def _summary(self, text='COMPACTED SUMMARY'):
        self.chat.provider.chat_nonstreaming.return_value = {
            'role': 'assistant', 'content': text,
            'tool_calls': None, 'finish_reason': 'stop',
        }

    def test_compact_keeps_all_turns_and_stamps_record(self):
        self._fill(6)
        self._summary()
        with patch('sys.stdout', new=io.StringIO()):
            self.chat.compact_session()
        self.chat.provider.chat_nonstreaming.assert_called_once()
        session = self.chat.current_session
        self.assertEqual(len(session.turns), 7)
        record = session.turns[-1]['parts'][0]
        self.assertEqual(record['type'], 'command')
        self.assertEqual(record['text'], '/compact')
        self.assertEqual(record['summary'], 'COMPACTED SUMMARY')
        self.assertEqual(record['compact_from'], 3)
        self.assertEqual(
            [p['text'] for t in session.turns[:6] for p in t['parts']],
            [c for i in range(6) for c in (f'msg {i}', f'answer {i}')])

    def test_provider_messages_uses_summary_and_boundary(self):
        self._fill(6)
        self._summary()
        with patch('sys.stdout', new=io.StringIO()):
            self.chat.compact_session()
        msgs = self.chat._provider_messages()
        self.assertEqual(msgs[0]['role'], 'system')
        self.assertIn('COMPACTED SUMMARY', msgs[0]['content'])
        self.assertEqual([m['content'] for m in msgs[1:]],
                         ['msg 2', 'answer 2', 'msg 3', 'answer 3',
                          'msg 4', 'answer 4', 'msg 5', 'answer 5'])

    def test_compact_nothing_when_no_history(self):
        with patch('sys.stdout', new=io.StringIO()):
            self.chat.compact_session()
        self.chat.provider.chat_nonstreaming.assert_not_called()

    def test_compact_failed_summary_keeps_context(self):
        self._fill(6)
        self._summary('')
        with patch('sys.stdout', new=io.StringIO()):
            self.chat.compact_session()
        self.assertEqual(len(self.chat.current_session.turns), 6)

    def test_compact_surfaces_provider_error(self):
        self._fill(6)
        self.chat.provider.chat_nonstreaming.return_value = {
            'error': {'code': 400, 'message': 'invalid role command'},
        }
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.compact_session()
        value = out.getvalue()
        self.assertIn('400', value)
        self.assertIn('invalid role command', value)
        self.assertIn('Compaction failed', value)
        self.assertEqual(len(self.chat.current_session.turns), 6)

    def test_compact_sanitizes_summarize_batch(self):
        self.chat.config.set('compact_keep', 1)
        session = self.chat.current_session
        session.add_command('/model foo')
        session.add_user('msg 0')
        part = session.add_tool('fetch_page', {'url': 'x'})
        turns.finish_tool(part, 'PAGE CONTENT')
        session.end_turn('ok')
        for i in (1, 2):
            session.add_user(f'msg {i}')
            session.add_text(f'answer {i}')
            session.end_turn('ok')
        self._summary('SUMMARY')
        with patch('sys.stdout', new=io.StringIO()):
            self.chat.compact_session()
        args = self.chat.provider.chat_nonstreaming.call_args[0][0]
        self.assertEqual(args[0]['role'], 'system')
        body = args[1:]
        self.assertTrue(all(m['role'] != 'command' for m in body))
        self.assertIn('[tool result] PAGE CONTENT',
                      [m['content'] for m in body])
        self.assertFalse(any('/model foo' in str(m.get('content'))
                             for m in body))

    def test_compact_prints_generated_summary(self):
        self._fill(6)
        self._summary('COMPACTED SUMMARY TEXT')
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.compact_session()
        value = out.getvalue()
        self.assertIn('Compacted -', value)
        self.assertIn('COMPACTED SUMMARY TEXT', value)

    def test_compact_writes_summary_file(self):
        self._fill(6)
        self._summary('COMPACTED SUMMARY')
        with patch('sys.stdout', new=io.StringIO()):
            self.chat.compact_session()
        path = (self.chat.sessions.sessions_dir.parent / 'summaries'
                / f'{self.chat.current_session.session_name}.md')
        self.assertTrue(path.exists())
        body = path.read_text()
        self.assertIn('COMPACTED SUMMARY', body)
        self.assertIn('Compact from turn: 3', body)

    def test_compact_without_history_writes_no_summary(self):
        with patch('sys.stdout', new=io.StringIO()):
            self.chat.compact_session()
        summaries = self.chat.sessions.sessions_dir.parent / 'summaries'
        self.assertFalse(summaries.exists())


class TestProviderMessages(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat()
        self.chat.config.set('mode', 'write')
        self.chat.config.apply('modes', {'read': {}, 'write': {}})

    def tearDown(self):
        self.chat._tmp.cleanup()

    def test_command_turns_filtered(self):
        session = self.chat.current_session
        session.add_user('hi')
        session.add_text('answer')
        session.end_turn('ok')
        session.add_command('/model foo')
        msgs = self.chat._provider_messages()
        self.assertEqual([m['role'] for m in msgs], ['user', 'assistant'])

    def test_command_with_summary_becomes_system_summary(self):
        session = self.chat.current_session
        session.add_user('hi')
        session.end_turn('ok')
        session.add_command('/compact', summary='THE SUMMARY', compact_from=2)
        msgs = self.chat._provider_messages()
        self.assertEqual(msgs[0]['role'], 'system')
        self.assertIn('THE SUMMARY', msgs[0]['content'])
        self.assertEqual(len(msgs), 1)

    def test_tool_part_reuses_stored_call_id(self):
        session = self.chat.current_session
        session.add_user('hi')
        part = session.add_tool('fetch_page', {'url': 'x'},
                                call_id='call_xyz')
        turns.finish_tool(part, 'page body')
        msgs = self.chat._provider_messages()
        self.assertEqual(msgs[1]['tool_calls'][0]['id'], 'call_xyz')
        self.assertEqual(msgs[2]['tool_call_id'], 'call_xyz')

    def test_tool_part_always_carries_its_call(self):
        session = self.chat.current_session
        session.add_user('hi')
        part = session.add_tool('fetch_page', {'url': 'x'})
        turns.finish_tool(part, 'page body')
        msgs = self.chat._provider_messages()
        self.assertEqual([m['role'] for m in msgs],
                         ['user', 'assistant', 'tool'])
        self.assertEqual(msgs[2]['content'], 'page body')
        self.assertEqual(msgs[1]['tool_calls'][0]['function']['name'],
                         'fetch_page')


if __name__ == '__main__':
    unittest.main()
