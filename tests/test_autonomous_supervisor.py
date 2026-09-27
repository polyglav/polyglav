import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import polyglav.scheduler as scheduler_mod
from polyglav.asks import AskStore, inject_answer
from polyglav.config import Config
from polyglav.engine import Engine
from polyglav.jobs import Job
from polyglav.scheduler import JobScheduler
from polyglav.ui import HeadlessUI

from tests.test_jobs import _FakePM, _FakeReport


def _tool_calls(cid: str, name: str, args: dict) -> list[dict]:
    return [{'type': 'tool_calls', 'tool_calls': [{
        'id': cid, 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(args)}}]}]


def _final(text: str) -> list[dict]:
    return [{'type': 'token', 'content': text},
            {'type': 'done', 'reason': 'stop'}]


class TestAutonomousSupervisor(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        polyglav = self.base / '.polyglav'
        polyglav.mkdir(parents=True)
        (polyglav / 'config.json').write_text(json.dumps({
            'provider': 'ollama', 'model': 'm', 'base_url': 'https://x',
            'tool_calling': True, 'unattended': True, 'max_team_depth': 2,
            'grant_permission': {
                'bash': 'allow', 'edit': 'allow', 'read': 'allow',
                'list': 'allow', 'web': 'allow', 'ask': 'allow'},
        }))
        (polyglav / 'roles.json').write_text(json.dumps({
            'leader': {
                'system_prompt': 'You lead the team.',
                'tool_permission': {
                    'bash': 'deny', 'edit': 'allow', 'read': 'allow',
                    'list': 'allow', 'web': 'deny', 'ask': 'allow'},
                'grant_permission': {
                    'bash': 'allow', 'edit': 'allow', 'read': 'allow',
                    'list': 'allow', 'web': 'allow', 'ask': 'allow'},
                'ask_policy': {'permission': 'auto', 'direction': 'human'},
            },
            'worker': {
                'system_prompt': 'You do the work.',
                'tool_permission': {
                    'read': 'allow', 'bash': 'allow', 'ask': 'allow'},
            },
        }))
        (polyglav / 'teams.json').write_text(json.dumps({
            'dev': {'description': 'dev pipeline',
                    'stages': [{'role': 'worker'}]},
        }))
        self.config = Config(path=str(self.base))
        self.reporter = _FakeReport()
        self.scheduler = JobScheduler(self.config, verbose=False,
                                      plugin_manager=_FakePM(self.reporter))
        self.registry = self.scheduler.registry
        self.provider = MagicMock()
        self.provider.chat.side_effect = [
            _tool_calls('c1', 'team', {'name': 'dev', 'task': 'do it'}),
            _tool_calls('c2', 'ask', {'question': 'which port?'}),
            _final('stage done'),
            _final('final answer'),
        ]

        real_build = scheduler_mod._build_engine
        provider = self.provider

        def fake_build(config, job, verbose, stream=False, session_name=None):
            engine = real_build(config, job, verbose, stream, session_name)
            engine.provider = provider
            engine._summarize = MagicMock(return_value='summary')
            self.built_engine = engine
            return engine

        patcher = patch('polyglav.scheduler._build_engine',
                        side_effect=fake_build)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def _supervisor_job(self) -> Job:
        return Job('supervisor', {'interval': 86400}, prompt='lead the team',
                   role='leader', status='approved', session='job.supervisor')

    def test_loop_parks_ask_and_reports(self):
        job = self._supervisor_job()
        self.registry.put(job)
        with patch('builtins.input',
                   side_effect=AssertionError('stdin must not be touched')):
            run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'verified')
        self.assertEqual(len(self.reporter.payloads), 1)
        payload = self.reporter.payloads[0]
        self.assertEqual(payload['event'], 'job.run.completed')
        self.assertEqual(payload['status'], 'verified')
        parked = payload['parked_asks']
        self.assertEqual([a['id'] for a in parked], [1])
        self.assertEqual(parked[0]['kind'], 'direction')
        self.assertEqual(parked[0]['question'], 'which port?')
        store = AskStore(self.config.local_path.parent / 'asks.json')
        self.assertEqual(len(store.list('pending')), 1)

    def test_answer_injects_and_resumes(self):
        job = self._supervisor_job()
        self.registry.put(job)
        with patch('builtins.input',
                   side_effect=AssertionError('stdin must not be touched')):
            self.scheduler.run_job(job)
        store = AskStore(self.config.local_path.parent / 'asks.json')
        ask = store.list('pending')[0]
        store.answer(ask.id, 'use port 8080')
        self.assertTrue(inject_answer(store, ask))

        self.provider.chat.side_effect = [_final('resumed')]
        engine = Engine(Config(path=str(self.base)),
                        ui=HeadlessUI(auto='deny'), provider=self.provider)
        engine._summarize = MagicMock(return_value='summary')
        engine.load_or_create_session(ask.origin)
        engine.chat('continue')
        sent = self.provider.chat.call_args.args[0]
        self.assertTrue(any('use port 8080' in (m.get('content') or '')
                            for m in sent))

    def test_worker_grant_ceiling_allows_delegated_bash(self):
        job = self._supervisor_job()
        self.registry.put(job)
        with patch('builtins.input',
                   side_effect=AssertionError('stdin must not be touched')):
            self.scheduler.run_job(job)
        sub = self.built_engine._new_sub_engine('worker')
        self.assertEqual(sub.config.get('tool_permission').get('bash'),
                         'allow')


if __name__ == '__main__':
    unittest.main()