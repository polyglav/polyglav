import io
import json
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from polyglav.config import Config
from polyglav.engine import TurnResult
from polyglav.sessions import turns as session_turns
from polyglav.jobs import (Job, JobRun, JobRegistry, compute_next_run, ensure_task_file,
                         next_run, parse_cron_field, parse_dt, read_memory,
                         render_list, render_show, render_status, describe_schedule,
                         system_prompt_for, validate_schedule, write_memory)
from polyglav.scheduler import JobScheduler

TZ = timezone.utc
BASE = datetime(2026, 8, 26, 10, 0, tzinfo=TZ)


def _turn(text):
    turn = session_turns.new_turn(1)
    session_turns.add_part(turn, session_turns.user_part(text))
    return turn


def _iso(dt):
    return dt.isoformat(timespec='seconds')


class TestCronField(unittest.TestCase):
    def test_wildcard(self):
        self.assertEqual(parse_cron_field('*', 0, 59), set(range(0, 60)))

    def test_step(self):
        self.assertEqual(parse_cron_field('*/15', 0, 59), {0, 15, 30, 45})

    def test_range(self):
        self.assertEqual(parse_cron_field('5-8', 0, 59), {5, 6, 7, 8})

    def test_range_step(self):
        self.assertEqual(parse_cron_field('5-20/5', 0, 59), {5, 10, 15, 20})

    def test_list(self):
        self.assertEqual(parse_cron_field('1,3,5', 1, 31), {1, 3, 5})

    def test_single(self):
        self.assertEqual(parse_cron_field('30', 0, 59), {30})

    def test_out_of_range(self):
        with self.assertRaises(ValueError):
            parse_cron_field('60', 0, 59)
        with self.assertRaises(ValueError):
            parse_cron_field('0', 1, 31)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_cron_field('xyz', 0, 59)
        with self.assertRaises(ValueError):
            parse_cron_field('*/0', 0, 59)


class TestNextRun(unittest.TestCase):
    def test_every_minute(self):
        self.assertEqual(next_run('* * * * *', BASE), BASE + timedelta(minutes=1))

    def test_minute_step(self):
        self.assertEqual(next_run('*/5 * * * *', BASE),
                         datetime(2026, 8, 26, 10, 5, tzinfo=TZ))
        self.assertEqual(next_run('*/5 * * * *', datetime(2026, 8, 26, 10, 2, tzinfo=TZ)),
                         datetime(2026, 8, 26, 10, 5, tzinfo=TZ))

    def test_rolls_to_next_hour(self):
        self.assertEqual(next_run('30 2 * * *', BASE),
                         datetime(2026, 8, 27, 2, 30, tzinfo=TZ))

    def test_hour_minute_rollover(self):
        self.assertEqual(next_run('0 9 * * *', datetime(2026, 8, 26, 9, 0, tzinfo=TZ)),
                         datetime(2026, 8, 27, 9, 0, tzinfo=TZ))

    def test_weekday(self):
        # 2026-08-26 is a Wednesday; next Monday is 2026-08-31
        self.assertEqual(next_run('0 9 * * 1', BASE),
                         datetime(2026, 8, 31, 9, 0, tzinfo=TZ))

    def test_weekday_7_is_sunday(self):
        self.assertEqual(next_run('0 9 * * 7', BASE),
                         datetime(2026, 8, 30, 9, 0, tzinfo=TZ))

    def test_dom_list(self):
        self.assertEqual(next_run('0 9 1,15 * *', BASE),
                         datetime(2026, 9, 1, 9, 0, tzinfo=TZ))

    def test_month_roll(self):
        self.assertEqual(next_run('0 0 1 2 *', BASE),
                         datetime(2027, 2, 1, 0, 0, tzinfo=TZ))

    def test_leap_day(self):
        self.assertEqual(next_run('0 0 29 2 *', BASE),
                         datetime(2028, 2, 29, 0, 0, tzinfo=TZ))

    def test_both_day_fields_are_restrictive(self):
        # AND semantics: the 15th that is also a Monday next occurs 2027-02-15
        self.assertEqual(next_run('0 9 15 * 1', datetime(2026, 8, 26, tzinfo=TZ)),
                         datetime(2027, 2, 15, 9, 0, tzinfo=TZ))

    def test_bad_arity(self):
        with self.assertRaises(ValueError):
            next_run('* * *', BASE)
        with self.assertRaises(ValueError):
            next_run('* * * * ', BASE)


class TestParseDt(unittest.TestCase):
    def test_zulu(self):
        self.assertEqual(parse_dt('2026-08-27T02:00:00Z'),
                         datetime(2026, 8, 27, 2, 0, tzinfo=TZ))

    def test_naive_becomes_utc(self):
        self.assertEqual(parse_dt('2026-08-27T02:00:00'),
                         datetime(2026, 8, 27, 2, 0, tzinfo=TZ))

    def test_offset(self):
        self.assertEqual(parse_dt('2026-08-27T04:00:00+02:00'),
                         datetime(2026, 8, 27, 2, 0, tzinfo=TZ))

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_dt('not-a-date')


class TestComputeNextRun(unittest.TestCase):
    def test_interval(self):
        job = Job('x', {'interval': 3600})
        self.assertEqual(compute_next_run(job, BASE), BASE + timedelta(seconds=3600))

    def test_interval_clamped_to_minimum(self):
        job = Job('x', {'interval': 5})
        self.assertEqual(compute_next_run(job, BASE), BASE + timedelta(seconds=60))

    def test_at_future(self):
        job = Job('x', {'at': '2026-08-27T02:00:00Z'})
        self.assertEqual(compute_next_run(job, BASE),
                         datetime(2026, 8, 27, 2, 0, tzinfo=TZ))

    def test_at_past_returns_none(self):
        job = Job('x', {'at': '2026-08-01T02:00:00Z'})
        self.assertIsNone(compute_next_run(job, BASE))

    def test_cron(self):
        job = Job('x', {'cron': '30 2 * * *'})
        self.assertEqual(compute_next_run(job, BASE),
                         datetime(2026, 8, 27, 2, 30, tzinfo=TZ))

    def test_unscheduled(self):
        self.assertIsNone(compute_next_run(Job('x', {}), BASE))


class TestValidateSchedule(unittest.TestCase):
    def test_accepts_all_forms(self):
        validate_schedule({'cron': '0 2 * * *'})
        validate_schedule({'interval': 3600})
        validate_schedule({'at': '2026-08-27T02:00:00Z'})

    def test_bad_cron(self):
        with self.assertRaises(ValueError):
            validate_schedule({'cron': 'not cron'})

    def test_bad_at(self):
        with self.assertRaises(ValueError):
            validate_schedule({'at': 'nope'})

    def test_no_schedule(self):
        with self.assertRaises(ValueError):
            validate_schedule({})


class TestJobModel(unittest.TestCase):
    def test_runnable_gate(self):
        proposed = Job('a', {'interval': 60})
        self.assertFalse(proposed.runnable())
        approved = Job('a', {'interval': 60}, status='approved')
        self.assertTrue(approved.runnable())
        approved.enabled = False
        self.assertFalse(approved.runnable())
        self.assertTrue(Job('a', {'interval': 60}, status='verified').runnable())
        self.assertTrue(Job('a', {'interval': 60}, status='failed').runnable())
        self.assertFalse(Job('a', {'interval': 60}, status='disabled').runnable())

    def test_ready_to_run_respects_require_approval(self):
        job = Job('a', {'interval': 60}, status='approved', require_approval=True)
        self.assertFalse(job.ready_to_run())
        job.approval_pending = True
        self.assertTrue(job.ready_to_run())
        job.status = 'waiting_approval'
        self.assertFalse(job.ready_to_run())

    def test_round_trip_carries_new_fields(self):
        job = Job('a', {'interval': 60}, status='waiting_approval',
                  require_approval=True, approval_pending=True,
                  created_at='2026-08-26T08:00:00+00:00')
        restored = Job.from_dict(job.to_dict())
        self.assertEqual(restored.status, 'waiting_approval')
        self.assertTrue(restored.require_approval)
        self.assertTrue(restored.approval_pending)
        self.assertEqual(restored.created_at, '2026-08-26T08:00:00+00:00')

    def test_round_trip_carries_task_file(self):
        job = Job('a', {'interval': 60}, task_file='tasks/a.md')
        self.assertEqual(Job.from_dict(job.to_dict()).task_file, 'tasks/a.md')

    def test_round_trip_carries_approve_model(self):
        job = Job('a', {'interval': 60}, approve_model=True)
        self.assertTrue(Job.from_dict(job.to_dict()).approve_model)

    def test_round_trip_with_history(self):
        job = Job(
            'nightly', {'cron': '0 2 * * *'}, prompt='summarize logs',
            session='ops.nightly', mode='plan', role='editor',
            retries=5, backoff=120.0, enabled=True, status='verified',
            next_run_at=_iso(BASE), last_run_at=_iso(BASE - timedelta(hours=24)),
            history=[JobRun(started_at=_iso(BASE), finished_at=_iso(BASE),
                            status='verified', duration=12.5, session='ops.nightly',
                            attempt=1)],
        )
        restored = Job.from_dict(job.to_dict())
        self.assertEqual(restored, job)
        self.assertEqual(restored.history[0].status, 'verified')

    def test_from_dict_defaults(self):
        job = Job.from_dict({'name': 'x', 'schedule': {'interval': 60}})
        self.assertEqual(job.status, 'proposed')
        self.assertEqual(job.retries, 3)
        self.assertEqual(job.history, [])


class TestJobRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'jobs.json'

    def tearDown(self):
        self.tmp.cleanup()

    def test_put_round_trip(self):
        registry = JobRegistry(self.path)
        registry.put(Job('a', {'interval': 60}, prompt='p', status='approved'))
        registry.put(Job('b', {'cron': '0 2 * * *'}))
        re_opened = JobRegistry(self.path)
        self.assertEqual([j.name for j in re_opened.all()], ['a', 'b'])
        self.assertEqual(re_opened.find('a').prompt, 'p')
        self.assertEqual(re_opened.find('a').status, 'approved')

    def test_remove(self):
        registry = JobRegistry(self.path)
        registry.put(Job('a', {'interval': 60}))
        self.assertTrue(registry.remove('a'))
        self.assertFalse(registry.remove('a'))
        self.assertEqual(registry.all(), [])

    def test_missing_file_is_empty(self):
        registry = JobRegistry(Path(self.tmp.name) / 'does-not-exist.json')
        self.assertEqual(registry.all(), [])

    def test_corrupt_file_is_tolerated(self):
        self.path.write_text('{not json')
        registry = JobRegistry(self.path)
        self.assertEqual(registry.all(), [])


class ScriptedEngine:
    def __init__(self, outcomes, session='job.x'):
        self.outcomes = list(outcomes)
        self.current_session = SimpleNamespace(session_name=session)
        self.prompts = []

    def chat(self, prompt):
        self.prompts.append(prompt)
        if not self.outcomes:
            return TurnResult(status='ok', content='', session=self.current_session.session_name)
        return self.outcomes.pop(0)


def _config(tmp) -> Config:
    base = Path(tmp.name)
    (base / '.polyglav').mkdir(parents=True, exist_ok=True)
    (base / '.polyglav' / 'config.json').write_text(json.dumps({
        'provider': 'ollama', 'model': 'm', 'base_url': 'https://test.api.com'}))
    return Config(path=str(base))


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = _config(self.tmp)
        self.registry = JobRegistry(self.config.local_path.parent / 'jobs.json')
        self.scheduler = JobScheduler(self.config, verbose=False)
        self.scheduler.registry = self.registry

    def tearDown(self):
        self.tmp.cleanup()

    def _patch_engine(self, outcomes):
        patcher = patch('polyglav.scheduler._build_engine', return_value=ScriptedEngine(outcomes))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_success_marks_verified(self):
        self._patch_engine([
            TurnResult(status='ok', content='done', duration=1.0, session='job.a'),
        ])
        job = Job('a', {'interval': 3600}, prompt='work', status='approved')
        self.registry.put(job)
        run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'verified')
        self.assertEqual(job.status, 'verified')
        self.assertEqual(len(job.history), 1)
        self.assertTrue(job.next_run_at)

    def test_truncated_counts_as_verified(self):
        self._patch_engine([
            TurnResult(status='truncated', content='partial', duration=1.0, session='job.a'),
        ])
        job = Job('a', {'interval': 60}, prompt='work', status='approved')
        run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'verified')

    def test_retries_then_succeeds(self):
        engine = [ScriptedEngine([
            TurnResult(status='error', errors=[{'message': 'boom'}], duration=1.0,
                       session='job.a'),
            TurnResult(status='ok', content='recovered', duration=1.0, session='job.a'),
        ])]
        patcher = patch('polyglav.scheduler._build_engine',
                        side_effect=lambda *a, **k: engine[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        job = Job('a', {'interval': 60}, prompt='work', status='approved',
                  retries=3, backoff=0)
        run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'verified')
        self.assertEqual(len(job.history), 2)
        self.assertIn('Retry', engine[0].prompts[1])

    def test_failure_after_retries_marks_failed(self):
        engine = ScriptedEngine([
            TurnResult(status='error', errors=[{'message': 'x'}], duration=0.5,
                       session='job.a'),
        ] + [TurnResult(status='error', errors=[{'message': 'x'}], duration=0.5,
                        session='job.a')] * 10)
        patcher = patch('polyglav.scheduler._build_engine',
                        return_value=engine)
        patcher.start()
        self.addCleanup(patcher.stop)
        job = Job('a', {'interval': 60}, prompt='work', status='approved',
                  retries=2, backoff=0)
        run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'failed')
        self.assertEqual(job.status, 'failed')
        self.assertEqual(len(job.history), 3)
        self.assertIn('x', run.reason)
        self.assertTrue(job.next_run_at)

    def test_unknown_type_fails_immediately(self):
        job = Job('a', {'interval': 60}, prompt='work', role='ghost',
                  status='approved')
        self.registry.put(job)
        run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'failed')
        self.assertIn('Unknown role', run.reason)
        self.assertEqual(job.status, 'failed')

    def test_build_engine_injects_type_skills(self):
        from pathlib import Path as _Path
        from polyglav.scheduler import _build_engine
        base = _Path(self.tmp.name)
        types = {
            'researcher': {'name': 'researcher',
                           'system_prompt': 'You are the researcher.',
                           'skills': ['finders']}}
        (base / '.polyglav' / 'roles.json').write_text(json.dumps(types))
        skills_dir = base / '.polyglav' / 'skills'
        skills_dir.mkdir(parents=True)
        (skills_dir / 'finders.md').write_text('Find sources and evaluate them.')
        job = Job('r', {'interval': 3600}, prompt='work', role='researcher')
        engine = _build_engine(self.config, job, verbose=False)
        prompt = engine.config.get('system_prompt')
        self.assertIn('You are the researcher.', prompt)
        self.assertIn('## Skills', prompt)
        self.assertIn('### finders', prompt)
        self.assertIn('Find sources and evaluate them.', prompt)

    def test_build_engine_skips_missing_type_skills(self):
        from pathlib import Path as _Path
        from polyglav.scheduler import _build_engine
        base = _Path(self.tmp.name)
        types = {'x': {'name': 'x', 'system_prompt': 'prompt',
                          'skills': ['nosuch']}}
        (base / '.polyglav' / 'roles.json').write_text(json.dumps(types))
        job = Job('x', {'interval': 3600}, prompt='work', role='x')
        engine = _build_engine(self.config, job, verbose=False)
        prompt = engine.config.get('system_prompt')
        self.assertIn('prompt', prompt)
        self.assertNotIn('## Skills', prompt)

    def test_timeout_records_failure(self):
        class HungEngine:
            def __init__(self):
                self.current_session = SimpleNamespace(session_name='job.t')
                self.prompts = []

            def chat(self, prompt):
                self.prompts.append(prompt)
                time.sleep(5)
                return TurnResult(status='ok', content='late', session='job.t')

        hung = HungEngine()
        with patch('polyglav.scheduler._build_engine', return_value=hung):
            job = Job('t', {'interval': 60}, prompt='work', status='approved',
                      retries=0, backoff=0, timeout=1)
            run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'failed')
        self.assertIn('timeout', run.reason)
        self.assertEqual(job.status, 'failed')

    def test_at_job_disables_after_first_run(self):
        self._patch_engine([
            TurnResult(status='ok', content='one shot', duration=0.5, session='job.a'),
        ])
        job = Job('a', {'at': '2026-08-27T02:00:00Z'}, prompt='once', status='approved')
        run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'verified')
        self.assertFalse(job.enabled)
        self.assertEqual(job.next_run_at, '')

    def test_tick_runs_due_approved_only(self):
        ok_engine = ScriptedEngine([TurnResult(status='ok', content='r', duration=0.1,
                                               session='job.ok')])
        patcher = patch('polyglav.scheduler._build_engine', return_value=ok_engine)
        patcher.start()
        self.addCleanup(patcher.stop)
        due = Job('due', {'interval': 60}, prompt='p', status='approved')
        due.next_run_at = _iso(BASE - timedelta(minutes=1))
        proposed = Job('prop', {'interval': 60}, prompt='p', status='proposed')
        disabled = Job('off', {'interval': 60}, prompt='p', status='approved',
                       enabled=False)
        for j in (due, proposed, disabled):
            self.registry.put(j)
        self.scheduler.tick(BASE)
        self.assertEqual(due.status, 'verified')
        self.assertEqual(proposed.status, 'proposed')
        self.assertEqual(disabled.status, 'approved')

    def test_tick_skips_future_jobs(self):
        engine = ScriptedEngine([TurnResult(status='ok', content='r', duration=0.1,
                                            session='job.f')])
        with patch('polyglav.scheduler._build_engine', return_value=engine):
            future = Job('f', {'interval': 3600}, prompt='p', status='approved')
            future.next_run_at = _iso(BASE + timedelta(hours=2))
            self.registry.put(future)
            self.scheduler.tick(BASE)
        self.assertEqual(future.status, 'approved')
        self.assertEqual(future.history, [])

    def test_manual_run_of_proposed_job_allowed(self):
        self._patch_engine([
            TurnResult(status='ok', content='manual', duration=1.0, session='job.m'),
        ])
        job = Job('m', {'interval': 3600}, prompt='once', status='proposed')
        self.registry.put(job)
        run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'verified')
        self.assertEqual(job.status, 'verified')
        self.assertTrue(job.runnable())  # a manual run acts as approval

    def test_require_approval_parks_after_run(self):
        self._patch_engine([
            TurnResult(status='ok', content='done', duration=0.5, session='job.r'),
        ])
        job = Job('r', {'interval': 60}, prompt='work', status='approved',
                  require_approval=True, approval_pending=True)
        self.registry.put(job)
        run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'verified')
        self.assertEqual(job.status, 'waiting_approval')
        self.assertFalse(job.approval_pending)
        self.assertFalse(job.ready_to_run())

    def test_require_approval_parks_until_next_approve(self):
        engine = ScriptedEngine([
            TurnResult(status='ok', content='a', duration=0.1, session='job.a')])
        with patch('polyglav.scheduler._build_engine', return_value=engine):
            job = Job('a', {'interval': 60}, prompt='p', status='approved',
                      require_approval=True, approval_pending=True)
            job.next_run_at = _iso(BASE - timedelta(minutes=1))
            self.registry.put(job)
            self.scheduler.tick(BASE)
            self.assertEqual(job.status, 'waiting_approval')
            self.assertEqual(len(job.history), 1)
            self.scheduler.tick(BASE + timedelta(minutes=5))
            self.assertEqual(len(job.history), 1)
            job.status = 'approved'
            job.approval_pending = True
            job.next_run_at = _iso(BASE + timedelta(minutes=5))
            self.scheduler.tick(BASE + timedelta(minutes=6))
            self.assertEqual(len(job.history), 2)
            self.assertEqual(job.status, 'waiting_approval')

    def test_run_content_captured(self):
        self._patch_engine([
            TurnResult(status='ok', content='hello from the job', duration=0.2,
                       session='job.rc'),
        ])
        job = Job('rc', {'interval': 60}, prompt='p', status='approved')
        self.registry.put(job)
        run = self.scheduler.run_job(job)
        self.assertEqual(run.content, 'hello from the job')

    def test_missing_task_file_fails_run(self):
        job = Job('t', {'interval': 60}, prompt='p', status='approved',
                  task_file='tasks/missing.md')
        self.registry.put(job)
        run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'failed')
        self.assertIn('task file not found', run.reason)
        self.assertEqual(job.status, 'failed')

    def test_system_prompt_composes_task_file(self):
        worktree = Path(self.tmp.name)
        job = Job('doc', {'interval': 60}, prompt='',
                  task_file='.polyglav/jobs/doc.md')
        ensure_task_file(worktree, job)
        text = system_prompt_for(job, worktree)
        self.assertIn('## Job task', text)
        self.assertIn('# doc', text)

    def test_system_prompt_links_file_edits(self):
        worktree = Path(self.tmp.name)
        path = worktree / '.polyglav' / 'jobs' / 'doc.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# First task')
        job = Job('doc', {'interval': 60}, prompt='', task_file='.polyglav/jobs/doc.md')
        self.assertIn('First task', system_prompt_for(job, worktree))
        path.write_text('# Second task')
        self.assertIn('Second task', system_prompt_for(job, worktree))
        self.assertNotIn('First task', system_prompt_for(job, worktree))

    def test_system_prompt_defaults_when_no_task(self):
        worktree = Path(self.tmp.name)
        job = Job('plain', {'interval': 60}, prompt='p', status='approved')
        text = system_prompt_for(job, worktree)
        self.assertIn('recurring autonomous job', text)

    def test_memory_written_after_run(self):
        self._patch_engine([
            TurnResult(status='ok', content='wrote 3 files', duration=0.2,
                       session='job.mm'),
        ])
        job = Job('mm', {'interval': 60}, prompt='p', status='approved')
        self.registry.put(job)
        run = self.scheduler.run_job(job)
        memory = read_memory(Path(self.tmp.name), job)
        self.assertEqual(run.status, 'verified')
        self.assertIn('verified', memory)
        self.assertIn('wrote 3 files', memory)

    def test_memory_uses_summarize_when_available(self):
        eng = ScriptedEngine([
            TurnResult(status='ok', content='raw output', duration=0.2,
                       session='job.sd')])
        eng.current_session.turns = [_turn('run one')]
        eng.seen = None

        def _summarize(msgs):
            eng.seen = msgs
            return 'compiled memory summary'
        eng._summarize = _summarize
        with patch('polyglav.scheduler._build_engine', return_value=eng):
            job = Job('sd', {'interval': 60}, prompt='p', status='approved')
            self.scheduler.run_job(job)
        memory = read_memory(Path(self.tmp.name), job)
        self.assertEqual(memory, 'compiled memory summary')

    def test_memory_seeds_next_run_summarize(self):
        eng = ScriptedEngine([
            TurnResult(status='ok', content='run two', duration=0.2,
                       session='job.seed')])
        eng.current_session.turns = [_turn('run two')]
        eng.seen = None

        def _summarize(msgs):
            eng.seen = msgs
            return 'second summary'
        eng._summarize = _summarize
        worktree = Path(self.tmp.name)
        write_memory(worktree, Job('seed', {'interval': 60}), 'first summary')
        with patch('polyglav.scheduler._build_engine', return_value=eng):
            job = Job('seed', {'interval': 60}, prompt='p', status='approved')
            self.scheduler.run_job(job)
        self.assertTrue(any(
            'Previous run memory' in (m.get('content') or '') for m in eng.seen))
        self.assertEqual(read_memory(worktree, job), 'second summary')

    def test_memory_recorded_when_engine_cannot_start(self):
        job = Job('boom', {'interval': 60}, prompt='p', role='ghost',
                  status='approved')
        self.registry.put(job)
        self.scheduler.run_job(job)
        memory = read_memory(Path(self.tmp.name), job)
        self.assertIn('Unknown role', memory)

    def test_memory_injected_into_system_prompt(self):
        worktree = Path(self.tmp.name)
        job = Job('mmo', {'interval': 60}, prompt='p', status='approved')
        write_memory(worktree, job, 'earlier runs produced report-v3.md')
        text = system_prompt_for(job, worktree)
        self.assertIn('## Run memory', text)
        self.assertIn('report-v3.md', text)
        fresh = Job('fresh', {'interval': 60}, prompt='p', status='approved')
        self.assertNotIn('## Run memory', system_prompt_for(fresh, worktree))

    def test_per_run_session_files_differ(self):
        calls = []

        def fake_build(config, job, verbose, stream=False, session_name=None):
            calls.append(session_name)
            session_dir = config.local_path.parent / 'sessions'
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / f'{session_name}.json').write_text('{}')
            return ScriptedEngine([TurnResult(status='ok', content='x',
                                              duration=0.1, session=session_name)])
        with patch('polyglav.scheduler._build_engine', side_effect=fake_build):
            job = Job('nightly', {'interval': 60}, prompt='p', status='approved')
            self.registry.put(job)
            self.scheduler.run_job(job)
            self.scheduler.run_job(job)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0], calls[1])
        for session in calls:
            self.assertRegex(session, r'job_\d{8}_\d{6}_[0-9a-z]{6}')

    def test_explicit_session_stays_stable(self):
        calls = []

        def fake_build(config, job, verbose, stream=False, session_name=None):
            calls.append(session_name)
            return ScriptedEngine([TurnResult(status='ok', content='x',
                                              duration=0.1, session=session_name)])
        with patch('polyglav.scheduler._build_engine', side_effect=fake_build):
            job = Job('stable', {'interval': 60}, prompt='p', status='approved',
                      session='myjobby')
            self.registry.put(job)
            self.scheduler.run_job(job)
            self.scheduler.run_job(job)
        self.assertEqual(calls, ['myjobby', 'myjobby'])

    def test_fresh_job_session_dedupes_collision(self):
        from polyglav import scheduler
        from datetime import datetime
        sessions_dir = self.config.local_path.parent / 'sessions'
        sessions_dir.mkdir(parents=True, exist_ok=True)
        when = datetime(2026, 8, 26, 10, 30, 5)
        (sessions_dir / 'job_fixed.json').write_text('{}')
        with patch('polyglav.scheduler.job_session_name',
                   side_effect=['job_fixed', 'job_free']):
            name = scheduler._fresh_job_session(sessions_dir, 'nightly', when)
        self.assertEqual(name, 'job_free')

    def test_job_session_name_format(self):
        from polyglav.jobs import job_session_name
        from datetime import datetime
        when = datetime(2026, 8, 26, 10, 30, 5)
        name = job_session_name('nightly report', when)
        self.assertTrue(name.startswith('job_20260826_103005_'))
        self.assertEqual(len(name.rsplit('_', 1)[1]), 6)
        self.assertNotEqual(job_session_name('a', when),
                            job_session_name('b', when))


class _FakeReport:
    def __init__(self):
        self.payloads = []
        self.configs = []

    def report(self, payload, config):
        self.payloads.append(payload)
        self.configs.append(config)


class _FakePM:
    def __init__(self, service=None):
        self._service = service

    def service(self, name):
        return self._service if name == 'report' else None


class TestSchedulerReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = _config(self.tmp)
        self.registry = JobRegistry(self.config.local_path.parent / 'jobs.json')
        self.reporter = _FakeReport()
        self.scheduler = JobScheduler(self.config, verbose=False,
                                      plugin_manager=_FakePM(self.reporter))
        self.scheduler.registry = self.registry

    def tearDown(self):
        self.tmp.cleanup()

    def _patch_engine(self, outcomes):
        patcher = patch('polyglav.scheduler._build_engine',
                        return_value=ScriptedEngine(outcomes))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_report_on_verified_run(self):
        self._patch_engine([
            TurnResult(status='ok', content='done', duration=1.5, session='job.a'),
        ])
        job = Job('a', {'interval': 3600}, prompt='work', status='approved')
        self.registry.put(job)
        self.scheduler.run_job(job)
        self.assertEqual(len(self.reporter.payloads), 1)
        payload = self.reporter.payloads[0]
        self.assertEqual(payload['event'], 'job.run.completed')
        self.assertEqual(payload['job'], 'a')
        self.assertEqual(payload['status'], 'verified')
        self.assertEqual(payload['duration'], 1.5)
        self.assertEqual(payload['session'], 'job.a')
        self.assertTrue(payload['started_at'])
        self.assertTrue(payload['finished_at'])
        self.assertIn('worktree', payload)
        self.assertIn('memory', payload)
        self.assertIs(self.reporter.configs[0], self.config)

    def test_report_on_failed_run(self):
        self._patch_engine([
            TurnResult(status='error', errors=[{'message': 'boom'}],
                       duration=2.0, session='job.a'),
        ])
        job = Job('a', {'interval': 60}, prompt='work', status='approved',
                  retries=0)
        self.registry.put(job)
        self.scheduler.run_job(job)
        self.assertEqual(len(self.reporter.payloads), 1)
        self.assertEqual(self.reporter.payloads[0]['status'], 'failed')
        self.assertIn('boom', self.reporter.payloads[0]['reason'])

    def test_report_on_build_failure(self):
        patcher = patch('polyglav.scheduler._build_engine',
                        side_effect=ValueError('unknown type'))
        patcher.start()
        self.addCleanup(patcher.stop)
        job = Job('a', {'interval': 60}, prompt='work', status='approved',
                  role='nope')
        self.registry.put(job)
        run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'failed')
        self.assertEqual(len(self.reporter.payloads), 1)
        self.assertEqual(self.reporter.payloads[0]['status'], 'failed')
        self.assertIn('unknown type', self.reporter.payloads[0]['reason'])

    def test_report_includes_parked_asks(self):
        from polyglav.asks import AskStore
        from polyglav.sessions.manager import SessionManager
        polyglav_dir = self.config.local_path.parent
        sessions = SessionManager(polyglav_dir / 'sessions')
        root = sessions.create('job.a')
        root.sub_sessions = ['sub_1']
        sessions.save(root)
        sub = sessions.create('sub_1')
        sessions.save(sub)
        AskStore(polyglav_dir / 'asks.json').add('which port?', 'sub_1')
        self._patch_engine([
            TurnResult(status='ok', content='done', duration=1.0, session='job.a'),
        ])
        job = Job('a', {'interval': 60}, prompt='work', status='approved',
                  session='job.a')
        self.registry.put(job)
        self.scheduler.run_job(job)
        parked = self.reporter.payloads[0]['parked_asks']
        self.assertEqual([a['id'] for a in parked], [1])
        self.assertEqual(parked[0]['origin'], 'sub_1')

    def test_no_service_no_dispatch(self):
        self.scheduler._pm = _FakePM(None)
        self._patch_engine([
            TurnResult(status='ok', content='done', duration=1.0, session='job.a'),
        ])
        job = Job('a', {'interval': 60}, prompt='work', status='approved')
        self.registry.put(job)
        run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'verified')
        self.assertEqual(self.reporter.payloads, [])

    def test_service_exception_does_not_fail_run(self):
        class Boom:
            def report(self, payload, config):
                raise RuntimeError('webhook down')

        self.scheduler._pm = _FakePM(Boom())
        self._patch_engine([
            TurnResult(status='ok', content='done', duration=1.0, session='job.a'),
        ])
        job = Job('a', {'interval': 60}, prompt='work', status='approved')
        self.registry.put(job)
        run = self.scheduler.run_job(job)
        self.assertEqual(run.status, 'verified')


class TestAddSupervisor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = _config(self.tmp)
        self.registry = JobRegistry(self.config.local_path.parent / 'jobs.json')

    def tearDown(self):
        self.tmp.cleanup()

    def test_scaffolds_supervisor_job(self):
        from polyglav.jobs import add_supervisor_job, read_task_file
        worktree = self.config.local_path.parent.parent
        job = add_supervisor_job(self.registry, 'night', worktree,
                                 {'interval': 86400}, task='Lead.')
        self.assertEqual(job.role, 'leader')
        self.assertEqual(job.status, 'approved')
        self.assertTrue(job.enabled)
        task = read_task_file(worktree, job)
        self.assertIn('supervisor', task)
        self.assertIn('leader', task)

    def test_duplicate_name_rejected(self):
        from polyglav.jobs import add_supervisor_job
        worktree = self.config.local_path.parent.parent
        add_supervisor_job(self.registry, 'night', worktree,
                           {'interval': 86400})
        with self.assertRaises(ValueError):
            add_supervisor_job(self.registry, 'night', worktree,
                               {'interval': 60})


class TestRender(unittest.TestCase):
    def test_list_and_show(self):
        registry = JobRegistry(Path('/nonexistent/jobs.json'))
        registry._jobs['a'] = Job('a', {'cron': '0 2 * * *'}, prompt='logs',
                                  status='approved')
        with patch('sys.stdout', new=io.StringIO()) as buf:
            render_list(registry)
            self.assertIn('a', buf.getvalue())
            self.assertIn("cron '0 2 * * *'", buf.getvalue())
        with patch('sys.stdout', new=io.StringIO()) as buf:
            self.assertTrue(render_show(registry, 'a'))
            self.assertIn('prompt:', buf.getvalue())
        with patch('sys.stdout', new=io.StringIO()) as buf:
            self.assertFalse(render_show(registry, 'missing'))
            self.assertIn('Job not found', buf.getvalue())

    def test_describe_schedule(self):
        self.assertEqual(describe_schedule(Job('a', {'cron': '0 2 * * *'})),
                         "cron '0 2 * * *'")
        self.assertEqual(describe_schedule(Job('a', {'interval': 60})), 'every 60s')
        self.assertEqual(describe_schedule(Job('a', {'at': '2026-08-27T02:00:00Z'})),
                         'at 2026-08-27T02:00:00Z')

    def test_status_render(self):
        registry = JobRegistry(Path('/nonexistent/jobs.json'))
        job = Job('a', {'interval': 60}, prompt='p', status='verified',
                  created_at='2026-08-26T08:00:00Z')
        job.history = [
            JobRun(status='verified', duration=1.0, content='ok'),
            JobRun(status='failed', reason='boom', session='job.a'),
        ]
        registry._jobs['a'] = job
        with patch('sys.stdout', new=io.StringIO()) as buf:
            render_status(registry)
            out = buf.getvalue()
        self.assertIn('a', out)
        self.assertIn('2 run(s) (1 ok, 1 failed)', out)
        self.assertIn('boom', out)
        self.assertIn('uptime', out)
        self.assertIn('last run: failed (0.0s) boom job.a', out)


class TestJobsCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.config = _config(self.tmp)

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, **kw):
        namespace = SimpleNamespace(path=str(self.base), tools_deny=[],
                                    tool_permission=[], approval='manual',
                                    retries=3, backoff=60.0, timeout=0,
                                    require_approval=False,
                                    session='', mode='', provider='', model='',
                                    role='', system_prompt='', file='',
                                    no_retry=False, verbose=False,
                                    tick=15.0, quiet=False)
        for key, value in kw.items():
            setattr(namespace, key, value)
        return namespace

    def test_add_list_approve_cycle(self):
        from polyglav.cli import cmd_jobs
        with patch('sys.stdout', new=io.StringIO()) as buf:
            code = cmd_jobs(self._args(action='add', name='nightly', prompt='report',
                                       cron='0 2 * * *'))
            self.assertEqual(code, 0)
            self.assertIn('proposed', buf.getvalue())
        registry = JobRegistry(self.base / '.polyglav' / 'jobs.json')
        job = registry.find('nightly')
        self.assertEqual(job.status, 'proposed')
        self.assertFalse(job.runnable())
        self.assertTrue(job.created_at)
        with patch('sys.stdout', new=io.StringIO()):
            cmd_jobs(self._args(action='approve', name='nightly'))
        fresh = JobRegistry(self.base / '.polyglav' / 'jobs.json')
        self.assertTrue(fresh.find('nightly').runnable())
        with patch('sys.stdout', new=io.StringIO()) as buf:
            cmd_jobs(self._args(action='list'))
            self.assertIn('nightly', buf.getvalue())

    def test_add_auto_approved(self):
        from polyglav.cli import cmd_jobs
        cmd_jobs(self._args(action='add', name='auto', prompt='p', cron='* * * * *',
                            approval='auto'))
        registry = JobRegistry(self.base / '.polyglav' / 'jobs.json')
        self.assertTrue(registry.find('auto').runnable())

    def test_add_defaults_to_write_mode(self):
        from polyglav.cli import cmd_jobs
        with patch('sys.stdout', new=io.StringIO()):
            cmd_jobs(self._args(action='add', name='wnightly', prompt='work',
                                cron='0 3 * * *'))
        registry = JobRegistry(self.base / '.polyglav' / 'jobs.json')
        self.assertEqual(registry.find('wnightly').mode, 'write')

    def test_add_keeps_explicit_read_mode(self):
        from polyglav.cli import cmd_jobs
        with patch('sys.stdout', new=io.StringIO()):
            cmd_jobs(self._args(action='add', name='probe', prompt='look',
                                cron='0 4 * * *', mode='read'))
        registry = JobRegistry(self.base / '.polyglav' / 'jobs.json')
        self.assertEqual(registry.find('probe').mode, 'read')

    def test_build_engine_defaults_to_write_mode(self):
        from polyglav.scheduler import _build_engine
        job = Job('m', {'interval': 3600}, prompt='p', status='approved')
        engine = _build_engine(self.config, job, verbose=False)
        self.assertEqual(engine.config.get('mode'), 'write')

    def test_add_rejects_bad_cron(self):
        from polyglav.cli import cmd_jobs
        with patch('sys.stderr', new=io.StringIO()) as err:
            code = cmd_jobs(self._args(action='add', name='bad', prompt='p',
                                       cron='not cron'))
            self.assertEqual(code, 1)
            self.assertIn('Error', err.getvalue())
        self.assertIsNone(JobRegistry(self.base / '.polyglav' / 'jobs.json').find('bad'))

    def test_add_rejects_duplicate(self):
        from polyglav.cli import cmd_jobs
        cmd_jobs(self._args(action='add', name='dup', prompt='p', interval=3600))
        with patch('sys.stderr', new=io.StringIO()) as err:
            code = cmd_jobs(self._args(action='add', name='dup', prompt='p',
                                       interval=3600))
            self.assertEqual(code, 1)
            self.assertIn('already exists', err.getvalue())

    def test_run_exit_code_ok(self):
        from polyglav.cli import cmd_jobs
        config_dir = Path(self.base) / '.polyglav'
        config_dir.mkdir(exist_ok=True)
        registry = JobRegistry(config_dir / 'jobs.json')
        registry.put(Job('nightly', {'interval': 60}, prompt='report',
                         status='approved'))
        with patch('polyglav.scheduler._build_engine', return_value=ScriptedEngine([
            TurnResult(status='ok', content='fine', duration=0.5, session='job.nightly'),
        ])):
            with patch('sys.stdout', new=io.StringIO()) as buf:
                code = cmd_jobs(self._args(action='run', name='nightly'))
        self.assertEqual(code, 0)
        self.assertIn('verified', buf.getvalue())
        registry = JobRegistry(config_dir / 'jobs.json')
        self.assertEqual(registry.find('nightly').status, 'verified')

    def test_run_exit_code_failure(self):
        from polyglav.cli import cmd_jobs
        config_dir = Path(self.base) / '.polyglav'
        config_dir.mkdir(exist_ok=True)
        registry = JobRegistry(config_dir / 'jobs.json')
        registry.put(Job('bad', {'interval': 60}, prompt='boom', status='approved',
                         retries=0, backoff=0))
        engine = ScriptedEngine([TurnResult(status='error',
                                            errors=[{'message': 'boom'}],
                                            duration=0.2, session='job.bad')])
        with patch('polyglav.scheduler._build_engine', return_value=engine):
            with patch('sys.stdout', new=io.StringIO()) as buf:
                code = cmd_jobs(self._args(action='run', name='bad', no_retry=True))
        self.assertEqual(code, 1)
        self.assertIn('failed', buf.getvalue())

    def test_stop_disables_job(self):
        from polyglav.cli import cmd_jobs
        cmd_jobs(self._args(action='add', name='x', prompt='p', interval=3600,
                            approval='auto'))
        with patch('sys.stdout', new=io.StringIO()) as buf:
            cmd_jobs(self._args(action='stop', name='x'))
            self.assertIn('disabled', buf.getvalue())
        fresh = JobRegistry(self.base / '.polyglav' / 'jobs.json')
        self.assertFalse(fresh.find('x').enabled)

    def test_add_require_approval_parks_until_approve(self):
        from polyglav.cli import cmd_jobs
        cmd_jobs(self._args(action='add', name='gated', prompt='p', interval=3600,
                            approval='auto', require_approval=True))
        fresh = JobRegistry(self.base / '.polyglav' / 'jobs.json')
        job = fresh.find('gated')
        self.assertEqual(job.status, 'waiting_approval')
        self.assertFalse(job.ready_to_run())
        cmd_jobs(self._args(action='approve', name='gated'))
        job = JobRegistry(self.base / '.polyglav' / 'jobs.json').find('gated')
        self.assertEqual(job.status, 'approved')
        self.assertTrue(job.approval_pending)
        self.assertTrue(job.ready_to_run())

    def test_run_prints_content_headless(self):
        from polyglav.cli import cmd_jobs
        config_dir = Path(self.base) / '.polyglav'
        config_dir.mkdir(exist_ok=True)
        registry = JobRegistry(config_dir / 'jobs.json')
        registry.put(Job('c', {'interval': 60}, prompt='p', status='approved',
                         retries=0, backoff=0))
        with patch('polyglav.scheduler._build_engine', return_value=ScriptedEngine([
            TurnResult(status='ok', content='hello from the job', duration=0.2,
                       session='job.c')])):
            with patch('sys.stdout', new=io.StringIO()) as buf:
                code = cmd_jobs(self._args(action='run', name='c'))
        self.assertEqual(code, 0)
        self.assertIn('hello from the job', buf.getvalue())

    def test_add_with_task_file_only(self):
        from polyglav.cli import cmd_jobs
        with patch('sys.stdout', new=io.StringIO()) as buf:
            code = cmd_jobs(self._args(action='add', name='doc',
                                       file='tasks/doc.md', cron='0 2 * * *'))
            self.assertEqual(code, 0)
            self.assertIn('doc', buf.getvalue())
        fresh = JobRegistry(self.base / '.polyglav' / 'jobs.json')
        job = fresh.find('doc')
        self.assertEqual(job.prompt, '')
        self.assertEqual(job.task_file, 'tasks/doc.md')
        self.assertTrue((self.base / 'tasks' / 'doc.md').exists())

    def test_add_requires_prompt_or_file(self):
        from polyglav.cli import cmd_jobs
        with patch('sys.stderr', new=io.StringIO()) as err:
            code = cmd_jobs(self._args(action='add', name='bare', cron='* * * * *'))
            self.assertEqual(code, 1)
            self.assertIn('--prompt or --file', err.getvalue())
        self.assertIsNone(JobRegistry(self.base / '.polyglav' / 'jobs.json').find('bare'))

    def test_add_creates_template_when_file_missing(self):
        from polyglav.cli import cmd_jobs
        cmd_jobs(self._args(action='add', name='archiver', interval=3600,
                            file='jobs/archiver.md'))
        path = self.base / 'jobs' / 'archiver.md'
        self.assertTrue(path.exists())
        self.assertIn('# archiver', path.read_text())

    def test_edit_creates_template_and_opens(self):
        from polyglav.cli import cmd_jobs
        cmd_jobs(self._args(action='add', name='writer', interval=3600,
                            prompt='write'))
        task_path = self.base / '.polyglav' / 'jobs' / 'writer.md'
        self.assertFalse(task_path.exists())
        with patch.dict('os.environ', {'EDITOR': 'true'}):
            with patch('sys.stdout', new=io.StringIO()):
                code = cmd_jobs(self._args(action='edit', name='writer'))
        self.assertEqual(code, 0)
        self.assertTrue(task_path.exists())
        self.assertIn('# writer', task_path.read_text())


if __name__ == '__main__':
    unittest.main()