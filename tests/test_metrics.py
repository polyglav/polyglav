import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from polyglav.config import Config
from polyglav.metrics import (Evidence, MetricTask, Probe, cmd_metrics,
                              content_hash, discover_tasks, format_results,
                              match_evidence, probe_correct, run_task)


def _tool_round(name, path, usage=10):
    return [{
        'type': 'tool_calls',
        'usage': {'prompt_tokens': usage, 'completion_tokens': 2},
        'tool_calls': [{
            'id': 'call_1', 'type': 'function',
            'function': {'name': name,
                         'arguments': json.dumps({'path': path})},
        }],
    }]


def _answer(text, usage=10):
    return [
        {'type': 'token', 'content': text},
        {'type': 'done', 'reason': 'stop',
         'usage': {'prompt_tokens': usage, 'completion_tokens': 2}},
    ]


class TestModel(unittest.TestCase):

    def test_task_requires_id_and_prompt(self):
        with self.assertRaises(ValueError):
            MetricTask.from_dict({'id': 'x'})
        with self.assertRaises(ValueError):
            MetricTask.from_dict({'prompt': 'x'})

    def test_task_round_trips(self):
        task = MetricTask.from_dict({
            'id': 't', 'turns': ['a', 'b'],
            'evidence': [{'id': 'e1', 'needles': ['alpha']}],
            'probes': [{'id': 'p1', 'question': 'q',
                        'checkpoint': 'c1', 'canonical': ['a']}],
        })
        self.assertEqual(task.turns, ['a', 'b'])
        self.assertEqual(task.evidence[0].id, 'e1')
        self.assertEqual(task.probes[0].checkpoint, 'c1')

    def test_match_evidence(self):
        evidence = [Evidence('e1', ['alpha']), Evidence('e2', ['beta'])]
        self.assertEqual(match_evidence('ALPHA and beta', evidence),
                         ['e1', 'e2'])
        self.assertEqual(match_evidence('none', evidence), [])

    def test_content_hash(self):
        self.assertEqual(content_hash('x'), content_hash('x'))
        self.assertNotEqual(content_hash('x'), content_hash('y'))
        self.assertEqual(len(content_hash('x')), 12)

    def test_probe_correct(self):
        probe = Probe('p', 'q', canonical=['alpha', 'beta'])
        self.assertTrue(probe_correct('The ALPHA value', probe))
        self.assertFalse(probe_correct('gamma', probe))


class TestRunTask(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir()
        self._prev = Config.GLOBAL_DIR
        Config.GLOBAL_DIR = self.home
        self.source = Config(path=self.tmp.name)
        self.source.set('model', 'ollama/test-model')
        self.source.set('base_url', 'https://test.api.com')
        self.source.set('cost.rates', {'default': {'input': 1, 'output': 1}})

    def tearDown(self):
        Config.GLOBAL_DIR = self._prev
        self.tmp.cleanup()

    def _task(self, **kwargs):
        data = {
            'id': 't1',
            'prompt': 'Read a.txt and report alpha.',
            'files': {'a.txt': 'needle alpha is here\n'},
            'evidence': [{'id': 'e1', 'needles': ['needle alpha']}],
            'goal_evidence': ['e1'],
            'probes': [{'id': 'p1', 'question': 'What was alpha?',
                        'checkpoint': 'c1', 'canonical': ['alpha']}],
        }
        data.update(kwargs)
        return MetricTask.from_dict(data)

    def _provider(self, rounds):
        provider = MagicMock()
        provider.chat.side_effect = rounds
        return provider

    def test_single_run_records_tools_evidence_and_probe(self):
        provider = self._provider([
            _tool_round('file_read', 'a.txt'),
            _answer('alpha', 20),
            _answer('alpha', 30),
        ])
        record = run_task(self._task(), self.source, 'single', provider=provider)
        self.assertEqual(record.task_id, 't1')
        self.assertEqual(record.condition, 'single')
        self.assertEqual(record.tool_calls[0]['name'], 'file_read')
        self.assertEqual(record.tool_calls[0]['evidence_ids'], ['e1'])
        self.assertGreater(record.tool_calls[0]['result_tokens'], 0)
        self.assertEqual(record.probes[0]['correct'], True)
        self.assertEqual(record.probes[0]['checkpoint'], 'c1')
        self.assertEqual(record.probes[0]['after_turn'], 1)
        self.assertEqual(record.rounds[0]['status'], 'tool_calls')
        self.assertEqual(record.cost['input'], 60)
        self.assertAlmostEqual(record.cost['total'], 0.000066)
        self.assertTrue(any(
            block['evidence_ids'] == ['e1']
            for item in record.rounds
            for block in item['context_blocks']))

    def test_multi_run_uses_turn_probes(self):
        task = self._task(turns=['first', 'second'],
                          probes=[{'id': 'p1', 'question': 'q',
                                   'checkpoint': 'c1', 'canonical': ['two'],
                                   'at_turn': 2}])
        provider = self._provider([
            _answer('one', 10),
            _answer('two', 20),
            _answer('two', 30),
        ])
        record = run_task(task, self.source, 'multi', provider=provider)
        self.assertEqual(record.run_end['main_turns'], 2)
        self.assertEqual(record.probes[0]['after_turn'], 2)
        self.assertEqual(record.probes[0]['correct'], True)

    def test_compaction_is_recorded(self):
        task = self._task(
            turns=['first', 'second'],
            compact={'at': 1000, 'keep': 1, 'before': 3, 'window': 0},
            probes=[],
        )
        provider = self._provider([
            _answer('one', 100),
            _tool_round('list_dir', '.', usage=200000),
            _answer('two', 200100),
        ])
        provider.chat_nonstreaming.return_value = {
            'role': 'assistant', 'content': 'SUMMARY',
            'usage': {'prompt_tokens': 1000, 'completion_tokens': 10},
        }
        record = run_task(task, self.source, 'multi', provider=provider)
        self.assertEqual(len(record.compactions), 1)
        self.assertTrue(record.compactions[0]['auto'])
        self.assertEqual(record.compactions[0]['reason'], 'threshold')
        self.assertEqual(record.compactions[0]['usage']['prompt_tokens'], 1000)
        self.assertIn('context_before', record.compactions[0])
        self.assertEqual(record.run_end['status'], 'ok')

    def test_format_results(self):
        provider = self._provider([
            _answer('one', 10),
            _answer('one', 20),
        ])
        record = run_task(self._task(probes=[]), self.source, 'single',
                          provider=provider)
        text = format_results([record])
        self.assertIn('t1', text)
        self.assertIn('single', text)


class TestDiscovery(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / 'metrics'
        self.dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_discover_tasks(self):
        (self.dir / 'one.json').write_text(json.dumps({
            'id': 'one', 'prompt': 'do it'}))
        (self.dir / 'two.json').write_text(json.dumps({
            'prompt': 'no id'}))
        (self.dir / 'bad.json').write_text('{')
        tasks = discover_tasks(self.dir, None)
        self.assertEqual(sorted(tasks), ['one', 'two'])

    def test_cli_list(self):
        (self.dir / 'one.json').write_text(json.dumps({
            'id': 'one', 'prompt': 'do it',
            'description': 'first task'}))
        source = Config(path=self.tmp.name)
        with patch('polyglav.metrics.discover_metrics',
                   return_value=discover_tasks(self.dir, None)):
            out = io.StringIO()
            with patch('sys.stdout', new=out):
                code = cmd_metrics(types.SimpleNamespace(
                    action='list', path=self.tmp.name))
        self.assertEqual(code, 0)
        self.assertIn('one - first task', out.getvalue())


if __name__ == '__main__':
    unittest.main()
