import io
import json
import threading
import unittest
from unittest.mock import patch

from polyglav.asks import AskStore, inject_answer
from polyglav.roles import Role

from tests.helpers import make_chat
from tests.test_engine import make_engine


class TestAskStore(unittest.TestCase):

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'asks.json'

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_find_roundtrip(self):
        store = AskStore(self.path)
        ask = store.add('which port?', 'ses_1', context='ctx',
                        options=['a', 'b'], kind='direction')
        self.assertEqual(ask.id, 1)
        self.assertEqual(ask.origin, 'ses_1')
        self.assertEqual(ask.status, 'pending')
        got = store.find(1)
        self.assertIsNotNone(got)
        self.assertEqual(got.question, 'which port?')
        self.assertEqual(got.options, ['a', 'b'])

    def test_ids_increment(self):
        store = AskStore(self.path)
        self.assertEqual(store.add('q1', 's').id, 1)
        self.assertEqual(store.add('q2', 's').id, 2)

    def test_persists_across_instances(self):
        AskStore(self.path).add('q', 'ses_1')
        store = AskStore(self.path)
        got = store.find(1)
        self.assertIsNotNone(got)
        self.assertEqual(got.question, 'q')
        self.assertEqual(len(store.list()), 1)

    def test_list_status_filter(self):
        store = AskStore(self.path)
        store.add('q1', 's')
        store.answer(1, 'done')
        store.add('q2', 's')
        self.assertEqual([a.id for a in store.list('pending')], [2])
        self.assertEqual([a.id for a in store.list('answered')], [1])
        self.assertEqual(len(store.list()), 2)

    def test_answer_sets_fields(self):
        store = AskStore(self.path)
        store.add('q', 's')
        got = store.answer(1, '  use 8080  ')
        self.assertIsNotNone(got)
        self.assertEqual(got.status, 'answered')
        self.assertEqual(got.answer, 'use 8080')
        self.assertTrue(got.answered_at)
        self.assertIsNone(store.answer(2, 'x'))
        self.assertIsNone(store.answer(1, '   '))

    def test_inject_answer_adds_user_message(self):
        from polyglav.sessions.manager import SessionManager
        from pathlib import Path
        store = AskStore(self.path)
        sessions_dir = self.path.parent / 'sessions'
        manager = SessionManager(sessions_dir)
        manager.create('ses_1')
        manager.save()
        ask = store.add('which port?', 'ses_1')
        self.assertTrue(inject_answer(store, ask))
        session = manager.read('ses_1')
        contents = [p['text'] for t in session.turns
                    for p in t.get('parts') or [] if p['type'] == 'user']
        self.assertTrue(any('[answer to parked ask #1]' in c for c in contents))
        self.assertTrue(any('which port?' not in c for c in contents))

    def test_inject_answer_missing_session(self):
        store = AskStore(self.path)
        ask = store.add('q', 'gone_session')
        self.assertFalse(inject_answer(store, ask))


class TestParking(unittest.TestCase):

    def tearDown(self):
        if hasattr(self, '_engine'):
            self._engine._tmp.cleanup()

    def _no_input(self, *args):
        raise AssertionError('stdin must not be touched in unattended mode')

    def test_root_human_ask_parks_when_unattended(self):
        chat = make_chat({'unattended': True})
        try:
            chat._init_tooling()
            with patch('builtins.input', side_effect=self._no_input):
                out = chat._run_tool('ask', {'question': 'which port?'})
            self.assertIn('[parked]', out)
            asks = chat.asks.list()
            self.assertEqual(len(asks), 1)
            self.assertEqual(asks[0].origin, chat.current_session.session_name)
            self.assertEqual(asks[0].kind, 'direction')
        finally:
            chat._tmp.cleanup()

    def test_subagent_human_ask_parks_not_lead(self):
        chat = make_chat({'unattended': True})
        try:
            chat.roles.put(Role(name='w', system_prompt='Writer'),
                           scope='local')
            sub = chat._new_sub_engine('w')
            sub._init_tooling()
            with patch('builtins.input', side_effect=self._no_input):
                out = sub._run_tool('ask', {'question': 'which port?'})
            self.assertIn('[parked]', out)
            chat.provider.chat_nonstreaming.assert_not_called()
            asks = chat.asks.list()
            self.assertEqual(len(asks), 1)
            self.assertEqual(asks[0].origin, sub.current_session.session_name)
        finally:
            chat._tmp.cleanup()

    def test_lead_target_without_lead_parks_when_unattended(self):
        chat = make_chat({'unattended': True})
        try:
            chat._init_tooling()
            with patch('builtins.input', side_effect=self._no_input):
                out = chat._run_tool('ask', {'question': 'q', 'target': 'caller'})
            self.assertIn('[parked]', out)
            self.assertEqual(len(chat.asks.list()), 1)
        finally:
            chat._tmp.cleanup()

    def test_attended_human_ask_still_prompts(self):
        chat = make_chat()
        try:
            chat._init_tooling()
            with patch('builtins.input', return_value='use 8080'):
                out = chat._run_tool('ask', {'question': 'which port?'})
            self.assertEqual(out, 'use 8080')
            self.assertEqual(len(chat.asks.list()), 0)
        finally:
            chat._tmp.cleanup()

    def test_permission_human_route_parks_when_unattended(self):
        chat = make_chat({'unattended': True,
                          'ask_policy': {'permission': 'user'}})
        try:
            chat.roles.put(Role(name='w', system_prompt='Writer'),
                           scope='local')
            sub = chat._new_sub_engine('w')
            sub._init_tooling()
            with patch('builtins.input', side_effect=self._no_input):
                out = sub._run_tool('ask', {
                    'kind': 'permission', 'permission': 'read',
                    'question': 'may I read?'})
            self.assertIn('[parked]', out)
            asks = chat.asks.list()
            self.assertEqual(len(asks), 1)
            self.assertEqual(asks[0].kind, 'permission')
            self.assertEqual(asks[0].permission, 'read')
        finally:
            chat._tmp.cleanup()

    def test_permission_auto_route_still_lead_when_unattended(self):
        chat = make_chat({'unattended': True})
        try:
            chat.roles.put(Role(name='w', system_prompt='Writer'),
                           scope='local')
            chat.provider.chat_nonstreaming.return_value = {'content': 'yes'}
            sub = chat._new_sub_engine('w')
            sub._init_tooling()
            out = sub._run_tool('ask', {
                'kind': 'permission', 'permission': 'read',
                'question': 'may I read?'})
            self.assertIn('[granted]', out)
            chat.provider.chat_nonstreaming.assert_called_once()
            self.assertEqual(len(chat.asks.list()), 0)
        finally:
            chat._tmp.cleanup()

    def test_answer_resumes_session_context(self):
        chat = make_chat({'unattended': True})
        try:
            chat._init_tooling()
            with patch('builtins.input', side_effect=self._no_input):
                chat._run_tool('ask', {'question': 'which port?'})
            chat.sessions.save(chat.current_session)
            ask = chat.asks.list()[0]
            chat.asks.answer(ask.id, 'use 8080')
            inject_answer(chat.asks, ask)
            chat.load_or_create_session(ask.origin)
            texts = [m.get('content', '') for m in chat._provider_messages()]
            self.assertTrue(any('use 8080' in t for t in texts))
        finally:
            chat._tmp.cleanup()


class TestAsksCommand(unittest.TestCase):

    def setUp(self):
        self.chat = make_chat({'unattended': True})
        self.chat._init_tooling()

    def tearDown(self):
        self.chat._tmp.cleanup()

    def _dispatch(self, line):
        out = io.StringIO()
        with patch('sys.stdout', new=out):
            self.chat.registry.dispatch(line)
        return out.getvalue()

    def _park_one(self, question='which port?'):
        with patch('builtins.input', side_effect=AssertionError('no stdin')):
            self.chat._run_tool('ask', {'question': question})
        self.chat.sessions.save(self.chat.current_session)
        return self.chat.asks.list()[0]

    def test_list_pending(self):
        self._park_one()
        out = self._dispatch('/asks')
        self.assertIn('#1', out)
        self.assertIn('which port?', out)
        out = self._dispatch('/asks list')
        self.assertIn('#1', out)

    def test_show(self):
        self._park_one()
        out = self._dispatch('/asks show 1')
        self.assertIn('#1', out)
        self.assertIn('which port?', out)
        self.assertIn('origin:', out)

    def test_answer_injects(self):
        self._park_one()
        out = self._dispatch('/asks answer 1 use 8080')
        self.assertIn('Answered ask #1', out)
        self.assertIn('resumed in session', out)
        ask = self.chat.asks.find(1)
        self.assertEqual(ask.status, 'answered')
        self.assertEqual(ask.answer, 'use 8080')
        contents = [p.get('text', '') for t in self.chat.current_session.turns
                    for p in t.get('parts') or [] if p['type'] == 'user']
        self.assertTrue(any('[answer to parked ask #1]' in c for c in contents))

    def test_unknown_id(self):
        out = self._dispatch('/asks answer 99 hi')
        self.assertIn('Ask not found: 99', out)

    def test_usage(self):
        out = self._dispatch('/asks answer')
        self.assertIn('Usage: /asks answer <id> <text>', out)


class TestAsksServer(unittest.TestCase):

    def setUp(self):
        from polyglav.server import HeadlessServer, ChatHandler
        self.engine = make_engine()
        self.engine.provider.chat.return_value = [
            {'type': 'token', 'content': 'ok'},
            {'type': 'done', 'reason': 'stop'},
        ]
        self.server = HeadlessServer(('127.0.0.1', 0), ChatHandler,
                                     engine=self.engine)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.engine._tmp.cleanup()

    def _get(self, path):
        from urllib.request import urlopen
        with urlopen(f'http://127.0.0.1:{self.port}{path}') as resp:
            return resp.status, json.loads(resp.read())

    def _post(self, path, body):
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        req = Request(f'http://127.0.0.1:{self.port}{path}',
                      data=json.dumps(body).encode('utf-8'),
                      headers={'Content-Type': 'application/json'},
                      method='POST')
        try:
            with urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())

    def test_get_asks(self):
        ask = self.engine.asks.add('which port?', 'api_session')
        status, data = self._get('/asks')
        self.assertEqual(status, 200)
        self.assertEqual(data['asks'][0]['id'], ask.id)
        self.assertEqual(data['asks'][0]['status'], 'pending')

    def test_answer_ask(self):
        self.engine.asks.add('which port?', 'api_session')
        status, data = self._post('/asks/1/answer', {'answer': 'use 8080'})
        self.assertEqual(status, 200)
        self.assertEqual(data['ask']['status'], 'answered')
        self.assertEqual(data['ask']['answer'], 'use 8080')
        self.assertEqual(data['session'], 'api_session')
        self.assertIn('--session-id api_session', data['resume'])

    def test_answer_unknown_ask(self):
        status, data = self._post('/asks/99/answer', {'answer': 'x'})
        self.assertEqual(status, 404)
        self.assertIn('not found', data['error'])

    def test_answer_missing_text(self):
        self.engine.asks.add('q', 's')
        status, data = self._post('/asks/1/answer', {})
        self.assertEqual(status, 400)
        self.assertIn('answer', data['error'])


if __name__ == '__main__':
    unittest.main()