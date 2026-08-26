import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.lw.combat_ext import CombatExtMixin
from src.lw.sound_ext import SoundContextExtMixin, SoundListenerExtMixin
from src.sound_trigger.DodgeCounterTrigger import DodgeCounterTrigger
from src.sound_trigger.SoundCombatContext import SoundCombatContext


class _FakeTask:
    def __init__(self):
        self.outcomes = []

    def after_sound_dodge_resolved(self, *, perfect_dodge):
        self.outcomes.append(perfect_dodge)


class _SoundContextHarness(SoundContextExtMixin):
    def __init__(self, task):
        super().__init__()
        self._context_lock = threading.RLock()
        self._listener = SimpleNamespace(
            counter_attack_threshold=0.12,
            lw_request_dodge_audio_capture=mock.Mock(return_value="dodge.wav"),
        )
        self._trigger = SimpleNamespace(task=task)
        self._pending_task = task


class _ListenerHarness(SoundListenerExtMixin):
    pass


class _CombatContextHarness(SoundCombatContext):
    _instance = None
    _lock = threading.Lock()
    _combat_interrupt = threading.Event()
    _action_complete = threading.Event()


class SoundDodgeConfirmationTests(unittest.TestCase):
    def setUp(self):
        _CombatContextHarness._instance = None
        _CombatContextHarness.clear_priority()

    def test_listener_publishes_scores_without_trigger_arbitration(self):
        listener = _ListenerHarness()
        observed = []
        listener.on_scores_updated = lambda dodge, counter: observed.append((dodge, counter))

        listener.lw_publish_scores(0.2, 0.13)

        self.assertEqual(observed, [(0.2, 0.13)])

    def test_listener_records_one_second_from_dodge_timestamp(self):
        listener = _ListenerHarness()
        written = []
        listener._lw_write_audio_async = lambda name, audio: written.append((name, audio))
        sample_name = listener.lw_request_dodge_audio_capture(10.0)
        chunk = np.ones(12000, dtype=np.float32)

        for ended_at in (10.25, 10.5, 10.75, 11.0):
            listener.lw_publish_audio_chunk(chunk, ended_at=ended_at)

        self.assertEqual(written[0][0], sample_name)
        self.assertEqual(len(written[0][1]), 48000)

    def test_listener_recording_ignores_chunk_timestamp_jitter_inside_window(self):
        listener = _ListenerHarness()
        written = []
        listener._lw_write_audio_async = lambda name, audio: written.append((name, audio))
        listener.lw_request_dodge_audio_capture(10.0)

        for value, ended_at in enumerate((10.25, 10.506, 10.744, 11.0), start=1):
            listener.lw_publish_audio_chunk(
                np.full(12000, value, dtype=np.float32),
                ended_at=ended_at,
            )

        expected = np.repeat(np.arange(1, 5, dtype=np.float32), 12000)
        np.testing.assert_array_equal(written[0][1], expected)

    def test_listener_returns_latest_continuous_audio_window(self):
        listener = _ListenerHarness()
        listener.lw_publish_audio_chunk(np.arange(4, dtype=np.float32), ended_at=1.0)
        listener.lw_publish_audio_chunk(np.arange(4, 8, dtype=np.float32), ended_at=1.2)

        np.testing.assert_array_equal(
            listener.lw_latest_audio_window(6),
            np.arange(2, 8, dtype=np.float32),
        )
        self.assertEqual(listener.lw_audio_sample_position(), 8)

    def test_audio_sample_retention_keeps_only_latest_files(self):
        listener = _ListenerHarness()
        listener.AUDIO_SAMPLE_LIMIT = 2
        samples = [mock.Mock() for _ in range(3)]
        for index, sample in enumerate(samples):
            sample.stat.return_value = SimpleNamespace(st_mtime=index)
        folder = mock.Mock()
        folder.glob.return_value = samples

        listener._lw_prune_audio_samples(folder)

        samples[0].unlink.assert_called_once_with(missing_ok=True)
        samples[1].unlink.assert_not_called()
        samples[2].unlink.assert_not_called()

    def test_perfect_sound_confirms_dodge_immediately(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        context.lw_update_perfect_dodge_wait(0.5)

        class Trigger:
            last_dodge_time = 0.0
            last_dodge_monotonic = 0.0

            def execute_dodge(inner_self):
                inner_self.last_dodge_monotonic = time.perf_counter()
                inner_self.last_dodge_time = time.time()
                context.lw_observe_sound_scores(0.0, 0.13)

        started_at = time.perf_counter()
        outcome = context.lw_execute_dodge_with_confirmation(Trigger(), task)
        context.lw_dispatch_dodge_outcome(task, outcome)

        self.assertTrue(outcome)
        self.assertLess(time.perf_counter() - started_at, 0.1)
        self.assertEqual(task.outcomes, [True])

    def test_ordinary_dodge_waits_then_resumes_normal_flow(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        context._listener.lw_request_dodge_audio_capture = mock.Mock(return_value="dodge.wav")
        context.lw_update_perfect_dodge_wait(0.03)

        class Trigger:
            last_dodge_time = 0.0
            last_dodge_monotonic = 0.0

            def execute_dodge(inner_self):
                inner_self.last_dodge_monotonic = time.perf_counter()
                inner_self.last_dodge_time = time.time()

        trigger = Trigger()

        started_at = time.perf_counter()
        outcome = context.lw_execute_dodge_with_confirmation(trigger, task)
        elapsed = time.perf_counter() - started_at
        context.lw_dispatch_dodge_outcome(task, outcome)

        self.assertFalse(outcome)
        self.assertGreaterEqual(elapsed, 0.025)
        self.assertEqual(task.outcomes, [False])

    def test_ordinary_dodge_deadline_starts_at_shift_not_attack_cue(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        context.lw_update_perfect_dodge_wait(0.03)

        class Trigger:
            last_dodge_time = 0.0
            last_dodge_monotonic = 0.0

            def execute_dodge(inner_self):
                time.sleep(0.02)
                inner_self.last_dodge_monotonic = time.perf_counter()
                inner_self.last_dodge_time = time.time()

        started_at = time.perf_counter()
        outcome = context.lw_execute_dodge_with_confirmation(Trigger(), task)

        self.assertFalse(outcome)
        self.assertGreaterEqual(time.perf_counter() - started_at, 0.045)

    def test_sound_before_shift_does_not_confirm_current_dodge(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        context.lw_update_perfect_dodge_wait(0.02)

        class Trigger:
            last_dodge_time = 0.0
            last_dodge_monotonic = 0.0

            def execute_dodge(inner_self):
                context.lw_observe_sound_scores(0.0, 0.13)
                time.sleep(0.005)
                inner_self.last_dodge_monotonic = time.perf_counter()
                inner_self.last_dodge_time = time.time()

        self.assertFalse(context.lw_execute_dodge_with_confirmation(Trigger(), task))

    def test_counter_trigger_confirms_while_action_queue_is_busy(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        context._lw_begin_dodge_confirmation(task)

        self.assertIsNone(context.lw_counter_trigger_action())
        self.assertIsNotNone(context._lw_dodge_confirmation.confirmed_at)

    def test_one_counter_sound_queues_only_one_manual_perfect_action(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        queued = []
        context._queue_action = queued.append

        context.lw_observe_sound_scores(0.0, 0.13)
        context.lw_observe_sound_scores(0.0, 0.14)
        context.lw_observe_sound_scores(0.0, 0.0)
        context.lw_observe_sound_scores(0.0, 0.13)

        self.assertEqual(queued, ["manual_perfect"])

        context.lw_observe_sound_scores(0.0, 0.0)
        context.lw_observe_sound_scores(0.0, 0.0)
        context.lw_observe_sound_scores(0.0, 0.13)

        self.assertEqual(queued, ["manual_perfect", "manual_perfect"])

    def test_confirmed_automatic_sound_cannot_restart_as_manual_perfect(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        queued = []
        context._queue_action = queued.append
        context._lw_begin_dodge_confirmation(task)

        context.lw_observe_sound_scores(0.0, 0.13)

        self.assertIsNone(context.lw_counter_trigger_action())
        self.assertEqual(queued, [])
        self.assertEqual(context._lw_manual_perfect_dodge_time, 0.0)

    def test_dodge_trigger_publishes_last_successful_input_time(self):
        task = SimpleNamespace()
        trigger = DodgeCounterTrigger(task, dodge_action=lambda: None)

        trigger.execute_dodge()
        first_dodge_at = trigger.last_dodge_time
        trigger.execute_dodge()

        self.assertGreater(first_dodge_at, 0.0)
        self.assertEqual(trigger.last_dodge_time, first_dodge_at)

    def test_sound_context_dispatches_confirmed_outcome_after_dodge(self):
        task = _FakeTask()
        task.executor = SimpleNamespace(paused=False)
        context = _CombatContextHarness()
        context._listener = SimpleNamespace(
            counter_attack_threshold=0.12,
            lw_request_dodge_audio_capture=mock.Mock(return_value="dodge.wav"),
        )
        context.lw_update_perfect_dodge_wait(0.5)

        class Trigger:
            def __init__(inner_self):
                inner_self.task = task
                inner_self.last_dodge_time = 0.0
                inner_self.last_dodge_monotonic = 0.0

            def execute_dodge(inner_self):
                inner_self.last_dodge_monotonic = time.perf_counter()
                inner_self.last_dodge_time = time.time()
                context._on_counter_triggered()

        context._trigger = Trigger()
        context._pending_task = task
        context._pending_action = "dodge"

        context.execute_pending_action()

        self.assertEqual(task.outcomes, [True])
        self.assertIsNone(context._pending_action)

    def test_manual_perfect_sound_dispatches_without_extra_input(self):
        task = _FakeTask()
        task.executor = SimpleNamespace(paused=False)
        context = _CombatContextHarness()
        trigger = SimpleNamespace(
            task=task,
            last_dodge_time=0.0,
            execute_dodge=mock.Mock(),
            execute_counter_attack=mock.Mock(),
        )
        context._listener = SimpleNamespace(counter_attack_threshold=0.12)
        context._trigger = trigger
        context._pending_task = task

        context.lw_observe_sound_scores(0.0, 0.13)
        context._on_counter_triggered()
        context.execute_pending_action()

        self.assertEqual(task.outcomes, [True])
        self.assertGreater(context.last_dodge_time(), 0.0)
        trigger.execute_dodge.assert_not_called()
        trigger.execute_counter_attack.assert_not_called()
        self.assertIsNone(context._pending_action)


class CombatDodgeOutcomeTests(unittest.TestCase):
    def test_only_perfect_dodge_runs_character_counter_hook(self):
        calls = []
        char = SimpleNamespace(on_dodge_counter=lambda: calls.append("counter"))
        combat = SimpleNamespace(
            get_current_char=lambda raise_exception=False: char,
            log_error=lambda message: self.fail(message),
        )

        CombatExtMixin.after_sound_dodge_resolved(combat, perfect_dodge=False)
        CombatExtMixin.after_sound_dodge_resolved(combat, perfect_dodge=True)

        self.assertEqual(calls, ["counter"])


if __name__ == "__main__":
    unittest.main()
