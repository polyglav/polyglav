import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from polyglav.config import Config
from polyglav.eval import (EvalFixture, discover_fixtures, format_results,
                         redundant_count, run_fixture, run_suite,
                         select_fixtures, summarize, token_total,
                         verify_fixture)


class _Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir()
        self._prev = Config.GLOBAL_DIR
        Config.GLOBAL_DIR = self.home
        self.source = Config(path=self.tmp.name)

    def tearDown(self):
        Config.GLOBAL_DIR = self._prev
        self.tmp.cleanup()

    def _provider(self, rounds):
        def factory(**kwargs):
            p = MagicMock()
            p.chat.side_effect = rounds
            return p
        factory.DEFAULT_BASE_URL = 'https://fake.api.com'
        factory.DEFAULT_MODEL = 'fake-model'
        return patch('polyglav.providers.PROVIDERS', {'ollama': factory})


class TestVerifier(_Base):

    def test_no_verifier_passes(self):
        fixture = EvalFixture(id='x', task='t')
        self.assertTrue(verify_fixture(fixture, [], []))

    def test_exact(self):
        fixture = EvalFixture(id='x', task='t', verifier={'exact': ['a', 'b']})
        self.assertTrue(verify_fixture(fixture, ['a', 'b'], []))
        self.assertFalse(verify_fixture(fixture, ['b', 'a'], []))
        self.assertFalse(verify_fixture(fixture, ['a'], []))

    def test_must_include(self):
        fixture = EvalFixture(id='x', task='t',
                              verifier={'must_include': ['list_dir']})
        self.assertTrue(verify_fixture(fixture, ['glob', 'list_dir'], []))
        self.assertFalse(verify_fixture(fixture, ['glob'], []))

    def test_avoid(self):
        fixture = EvalFixture(id='x', task='t', verifier={'avoid': ['run_command']})
        self.assertTrue(verify_fixture(fixture, ['file_read'], []))
        self.assertFalse(verify_fixture(fixture, ['run_command'], []))

    def test_max_calls(self):
        fixture = EvalFixture(id='x', task='t', verifier={'max_calls': 2})
        self.assertTrue(verify_fixture(fixture, ['a', 'b'], []))
        self.assertFalse(verify_fixture(fixture, ['a', 'b', 'c'], []))

    def test_min_calls(self):
        fixture = EvalFixture(id='x', task='t', verifier={'min_calls': 2})
        self.assertTrue(verify_fixture(fixture, ['a', 'b'], []))
        self.assertFalse(verify_fixture(fixture, ['a'], []))

    def test_args(self):
        fixture = EvalFixture(id='x', task='t', verifier={
            'args': {'file_read': {'path': 'src/app.py'}}})
        trace = [{'name': 'file_read', 'arguments': {'path': 'src/app.py'}}]
        self.assertTrue(verify_fixture(fixture, ['file_read'], trace))
        bad = [{'name': 'file_read', 'arguments': {'path': 'other.py'}}]
        self.assertFalse(verify_fixture(fixture, ['file_read'], bad))


class TestMetrics(_Base):

    def test_redundant_count(self):
        trace = [
            {'name': 'grep', 'arguments': {'pattern': 'x'}},
            {'name': 'grep', 'arguments': {'pattern': 'x'}},
            {'name': 'grep', 'arguments': {'pattern': 'y'}},
            {'name': 'file_read', 'arguments': {'path': 'a'}},
        ]
        self.assertEqual(redundant_count(trace), 1)

    def test_redundant_ignores_arg_order(self):
        trace = [
            {'name': 'file_read', 'arguments': {'path': 'a', 'limit': 5}},
            {'name': 'file_read', 'arguments': {'limit': 5, 'path': 'a'}},
        ]
        self.assertEqual(redundant_count(trace), 1)

    def test_token_total(self):
        self.assertEqual(token_total(None), 0)
        self.assertEqual(token_total({}), 0)
        self.assertEqual(token_total({'total_tokens': 42}), 42)
        self.assertEqual(token_total({'prompt_tokens': 7, 'completion_tokens': 5}), 12)

    def test_summarize(self):
        results = [
            {'accuracy': 1, 'pass': True, 'calls': 2, 'redundant': 1,
             'errors': 0, 'tokens': 10},
            {'accuracy': 0, 'pass': False, 'calls': 1, 'redundant': 0,
             'errors': 2, 'tokens': 20},
        ]
        s = summarize(results)
        self.assertEqual(s['fixtures'], 2)
        self.assertEqual(s['accuracy'], 0.5)
        self.assertEqual(s['pass_rate'], 0.5)
        self.assertEqual(s['avg_calls'], 1.5)
        self.assertEqual(s['avg_redundant'], 0.5)
        self.assertEqual(s['errors'], 2)
        self.assertEqual(s['total_tokens'], 30)
        self.assertEqual(s['avg_tokens'], 15.0)


class TestRunFixture(_Base):

    def test_run_fixture_metrics(self):
        fixture = EvalFixture(
            id='t1', task='List the project directory.',
            files={'a.txt': 'x'},
            expected=['list_dir'],
            verifier={'exact': ['list_dir']},
        )
        rounds = [
            [{'type': 'tool_calls', 'tool_calls': [
                {'id': 'c1', 'type': 'function',
                 'function': {'name': 'list_dir',
                              'arguments': json.dumps({'path': '.'})}},
            ]}],
            [{'type': 'token', 'content': 'done'},
             {'type': 'done', 'reason': 'stop',
              'usage': {'prompt_tokens': 7, 'completion_tokens': 3}}],
        ]
        with self._provider(rounds):
            metrics = run_fixture(fixture, source=self.source)
        self.assertEqual(metrics['names'], ['list_dir'])
        self.assertEqual(metrics['accuracy'], 1)
        self.assertTrue(metrics['pass'])
        self.assertEqual(metrics['calls'], 1)
        self.assertEqual(metrics['redundant'], 0)
        self.assertEqual(metrics['errors'], 0)
        self.assertEqual(metrics['tokens'], 10)
        self.assertEqual(metrics['status'], 'ok')

    def test_run_fixture_counts_tool_errors(self):
        fixture = EvalFixture(
            id='t2', task='Read the file nope.txt.',
            expected=['file_read'],
        )
        rounds = [
            [{'type': 'tool_calls', 'tool_calls': [
                {'id': 'c1', 'type': 'function',
                 'function': {'name': 'file_read',
                              'arguments': json.dumps({'path': 'nope.txt'})}},
            ]}],
            [{'type': 'token', 'content': 'ok'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        with self._provider(rounds):
            metrics = run_fixture(fixture, source=self.source)
        self.assertEqual(metrics['calls'], 1)
        self.assertEqual(metrics['errors'], 1)

    def test_run_fixture_counts_redundant(self):
        fixture = EvalFixture(id='t3', task='Read both files.',
                              verifier={'must_include': ['file_read']})
        rounds = [
            [{'type': 'tool_calls', 'tool_calls': [
                {'id': 'c1', 'type': 'function',
                 'function': {'name': 'file_read',
                              'arguments': json.dumps({'path': 'a.txt'})}},
                {'id': 'c2', 'type': 'function',
                 'function': {'name': 'file_read',
                              'arguments': json.dumps({'path': 'a.txt'})}},
            ]}],
            [{'type': 'token', 'content': 'ok'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        with self._provider(rounds):
            metrics = run_fixture(fixture, source=self.source)
        self.assertEqual(metrics['calls'], 2)
        self.assertEqual(metrics['redundant'], 1)

    def test_run_fixture_restores_cwd(self):
        before = Path.cwd()
        fixture = EvalFixture(id='t4', task='List the directory.',
                              files={'a.txt': 'x'})
        rounds = [
            [{'type': 'tool_calls', 'tool_calls': [
                {'id': 'c1', 'type': 'function',
                 'function': {'name': 'list_dir',
                              'arguments': json.dumps({'path': '.'})}},
            ]}],
            [{'type': 'token', 'content': 'ok'},
             {'type': 'done', 'reason': 'stop'}],
        ]
        with self._provider(rounds):
            run_fixture(fixture, source=self.source)
        self.assertEqual(Path.cwd(), before)

    def test_run_suite_aggregates(self):
        fixture = EvalFixture(
            id='t5', task='List the directory.',
            files={'a.txt': 'x'},
            expected=['list_dir'],
            verifier={'exact': ['list_dir']},
        )
        rounds = [
            [{'type': 'tool_calls', 'tool_calls': [
                {'id': 'c1', 'type': 'function',
                 'function': {'name': 'list_dir',
                              'arguments': json.dumps({'path': '.'})}},
            ]}],
            [{'type': 'token', 'content': 'ok'},
             {'type': 'done', 'reason': 'stop',
              'usage': {'prompt_tokens': 4, 'completion_tokens': 1}}],
        ]
        with self._provider(rounds):
            results, summary = run_suite({'t5': fixture}, self.source)
        self.assertEqual(len(results), 1)
        self.assertEqual(summary['accuracy'], 1.0)
        self.assertEqual(summary['total_tokens'], 5)


class TestDiscovery(_Base):

    def _write(self, directory, name, **data):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(json.dumps(data))

    def test_discover_from_local_dir(self):
        local = self.source.local_path.parent / 'eval'
        self._write(local, 'a.json', task='t1', description='A')
        self._write(local, 'b.json', task='t2')
        fixtures = discover_fixtures(local_dir=local)
        self.assertEqual(set(fixtures), {'a', 'b'})
        self.assertEqual(fixtures['a'].id, 'a')

    def test_discover_local_overrides_global(self):
        local = self.source.local_path.parent / 'eval'
        global_ = self.home / '.config' / 'polyglav' / 'eval'
        self._write(local, 'a.json', task='local task')
        self._write(global_, 'a.json', task='global task')
        self._write(global_, 'g.json', task='only global')
        fixtures = discover_fixtures(local_dir=local, global_dir=global_)
        self.assertEqual(fixtures['a'].task, 'local task')
        self.assertEqual(fixtures['g'].task, 'only global')

    def test_discover_plugin_hook(self):
        class _PM:
            def register_fixtures(self, fixtures):
                fixtures.update({
                    'plug-a': {'task': 'from plugin', 'expected': ['file_read']},
                    'plug-b': {'task': 'broken'},
                })
        fixtures = discover_fixtures(plugin_manager=_PM())
        self.assertEqual(set(fixtures), {'plug-a', 'plug-b'})
        self.assertEqual(fixtures['plug-a'].expected, ['file_read'])

    def test_discover_plugin_behind_local(self):
        local = self.source.local_path.parent / 'eval'
        self._write(local, 'plug-a.json', task='local override')

        class _PM:
            def register_fixtures(self, fixtures):
                fixtures.update({'plug-a': {'task': 'from plugin'}})
        fixtures = discover_fixtures(local_dir=local, plugin_manager=_PM())
        self.assertEqual(fixtures['plug-a'].task, 'local override')

    def test_discover_ignores_bad_files(self):
        local = self.source.local_path.parent / 'eval'
        local.mkdir(parents=True, exist_ok=True)
        (local / 'bad.json').write_text('not json')
        (local / 'missing.json').write_text(json.dumps({'description': 'no task'}))
        fixtures = discover_fixtures(local_dir=local)
        self.assertEqual(fixtures, {})

    def test_select_fixtures(self):
        fixtures = {'aaa': EvalFixture(id='aaa', task='t'),
                    'bbb': EvalFixture(id='bbb', task='t')}
        self.assertEqual(set(select_fixtures(fixtures, None)), {'aaa', 'bbb'})
        self.assertEqual(set(select_fixtures(fixtures, 'aa')), {'aaa'})
        self.assertEqual(select_fixtures(fixtures, 'zz'), {})

    def test_format_results(self):
        results = [{'id': 't', 'accuracy': 1, 'pass': True, 'calls': 1,
                    'redundant': 0, 'errors': 0, 'tokens': 5, 'status': 'ok'}]
        summary = summarize(results)
        out = format_results(results, summary)
        self.assertIn('accuracy 1.00', out)
        self.assertIn('pass 1.00', out)
        self.assertIn('tokens 5', out)


if __name__ == '__main__':
    unittest.main()