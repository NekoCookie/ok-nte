import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from src.char.Requiem import Requiem
from src.lw.combat_ext import CombatExtMixin
from src.lw.requiem_zankou_axis import REQUIEM_IMPL_ID, ZANKOU_MAIN_DPS_IMPL_ID
from src.lw.sound_ext import SoundContextExtMixin, SoundListenerExtMixin
from src.sound_trigger.DodgeCounterTrigger import DodgeCounterTrigger
from src.sound_trigger.SoundCombatContext import SoundCombatContext
from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask


class _FakeTask:
    def __init__(self):
        self.outcomes = []
        self.dodge_results = []

    def after_sound_dodge_resolved(self, *, perfect_dodge, dodge_result):
        self.outcomes.append(perfect_dodge)
        self.dodge_results.append(dodge_result)


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
        listener.AUDIO_DIAGNOSTIC_CAPTURE = True
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
        listener.AUDIO_DIAGNOSTIC_CAPTURE = True
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

    def test_listener_does_not_capture_dodge_audio_by_default(self):
        listener = _ListenerHarness()

        self.assertEqual(listener.lw_request_dodge_audio_capture(10.0), "")
        self.assertEqual(listener._lw_audio_captures, [])

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
        context.lw_update_ordinary_dodge_wait(0.5)

        class Trigger:
            last_dodge_time = 0.0
            last_dodge_monotonic = 0.0

            def execute_dodge(inner_self):
                inner_self.last_dodge_monotonic = time.perf_counter()
                inner_self.last_dodge_time = time.time()
                context.lw_observe_sound_scores(0.0, 0.13)

        started_at = time.perf_counter()
        with mock.patch("src.lw.sound_ext.logger.info") as log_info:
            outcome = context.lw_execute_dodge_with_confirmation(Trigger(), task)
        context.lw_dispatch_dodge_outcome(task, outcome, context.DODGE_RESULT_AUTO_PERFECT)

        self.assertTrue(outcome)
        self.assertLess(time.perf_counter() - started_at, 0.1)
        self.assertEqual(task.outcomes, [True])
        self.assertEqual(task.dodge_results, ["自动完美"])
        resolved = context.last_dodge_outcome()
        self.assertTrue(resolved.perfect_dodge)
        self.assertEqual(resolved.result, "自动完美")
        self.assertLess(abs(time.monotonic() - resolved.anchor_monotonic), 0.1)
        self.assertTrue(
            any("声音闪避结果: 自动完美" in call.args[0] for call in log_info.call_args_list)
        )

    def test_character_releases_held_input_only_before_an_accepted_automatic_dodge(self):
        events = []
        task = SimpleNamespace(
            prepare_current_char_for_sound_dodge=lambda: events.append("release")
        )
        trigger = DodgeCounterTrigger(task, dodge_action=lambda: events.append("shift"))

        trigger.execute_dodge()
        trigger.execute_dodge()
        self.assertEqual(events, ["release", "shift"])

    def test_requiem_real_skill_departure_suppresses_automatic_dodge_input(self):
        task = _FakeTask()
        current_char = SimpleNamespace(
            lw_sound_dodge_block_reason=lambda: (
                "requiem real skill waiting for off-field switch"
            )
        )
        task.get_current_char = lambda raise_exception=False: current_char
        context = _SoundContextHarness(task)
        trigger = mock.MagicMock(last_dodge_time=0.0, last_dodge_monotonic=0.0)

        with mock.patch("src.lw.sound_ext.logger.info") as log_info:
            outcome = context.lw_execute_dodge_with_confirmation(trigger, task)

        self.assertIsNone(outcome)
        self.assertIsNone(context._lw_dodge_confirmation)
        trigger.execute_dodge.assert_not_called()
        log_info.assert_called_once_with(
            "声音闪避跳过: requiem real skill waiting for off-field switch"
        )

    def test_ordinary_dodge_waits_then_resumes_normal_flow(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        context._listener.lw_request_dodge_audio_capture = mock.Mock(return_value="dodge.wav")
        context.lw_update_ordinary_dodge_wait(0.03)

        class Trigger:
            last_dodge_time = 0.0
            last_dodge_monotonic = 0.0

            def execute_dodge(inner_self):
                inner_self.last_dodge_monotonic = time.perf_counter()
                inner_self.last_dodge_time = time.time()

        trigger = Trigger()

        started_at = time.perf_counter()
        with mock.patch("src.lw.sound_ext.logger.info") as log_info:
            outcome = context.lw_execute_dodge_with_confirmation(trigger, task)
        elapsed = time.perf_counter() - started_at
        context.lw_dispatch_dodge_outcome(task, outcome, context.DODGE_RESULT_ORDINARY)

        self.assertFalse(outcome)
        self.assertGreaterEqual(elapsed, 0.025)
        self.assertEqual(task.outcomes, [False])
        self.assertEqual(task.dodge_results, ["普通闪避"])
        resolved = context.last_dodge_outcome()
        self.assertFalse(resolved.perfect_dodge)
        self.assertEqual(resolved.result, "普通闪避")
        self.assertGreaterEqual(time.monotonic() - resolved.anchor_monotonic, 0.025)
        self.assertTrue(
            any("声音闪避结果: 普通闪避" in call.args[0] for call in log_info.call_args_list)
        )

    def test_ordinary_dodge_deadline_starts_at_shift_not_attack_cue(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        context.lw_update_ordinary_dodge_wait(0.03)

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

    def test_global_ordinary_dodge_wait_applies_to_non_requiem_character(self):
        task = _FakeTask()
        config_task = SimpleNamespace(
            config={
                RequiemCombatConfigTask.CONF_ORDINARY_DODGE_WAIT: 0.02,
            }
        )
        task.get_task_by_class = lambda _task_class: config_task
        context = _SoundContextHarness(task)
        context.lw_update_ordinary_dodge_wait(0.5)

        class Trigger:
            last_dodge_time = 0.0
            last_dodge_monotonic = 0.0

            def execute_dodge(inner_self):
                inner_self.last_dodge_monotonic = time.perf_counter()
                inner_self.last_dodge_time = time.time()

        started_at = time.perf_counter()
        outcome = context.lw_execute_dodge_with_confirmation(Trigger(), task)
        elapsed = time.perf_counter() - started_at

        self.assertFalse(outcome)
        self.assertGreaterEqual(elapsed, 0.015)
        self.assertLess(elapsed, 0.1)
        self.assertEqual(context.lw_ordinary_dodge_wait_for_task(task), 0.02)

    def test_requiem_ordinary_dodge_wait_uses_dedicated_value(self):
        task = _FakeTask()
        config_task = SimpleNamespace(
            config={
                RequiemCombatConfigTask.CONF_ORDINARY_DODGE_WAIT: 0.02,
                RequiemCombatConfigTask.CONF_REQUIEM_ORDINARY_DODGE_WAIT: 0.07,
            }
        )
        task.get_task_by_class = lambda _task_class: config_task
        task.get_current_char = lambda raise_exception=False: SimpleNamespace(
            impl_id=REQUIEM_IMPL_ID
        )
        context = _SoundContextHarness(task)
        context.lw_update_ordinary_dodge_wait(0.5)

        self.assertEqual(context.lw_ordinary_dodge_wait_for_task(task), 0.07)

    def test_requiem_ordinary_dodge_wait_does_not_fall_back_to_global_value(self):
        task = _FakeTask()
        config_task = SimpleNamespace(
            config={RequiemCombatConfigTask.CONF_ORDINARY_DODGE_WAIT: 0.02}
        )
        task.get_task_by_class = lambda _task_class: config_task
        task.get_current_char = lambda raise_exception=False: SimpleNamespace(
            impl_id=REQUIEM_IMPL_ID
        )
        context = _SoundContextHarness(task)
        context.lw_update_ordinary_dodge_wait(0.02)

        self.assertEqual(context.lw_ordinary_dodge_wait_for_task(task), 0.5)

    def test_shared_ordinary_dodge_wait_falls_back_when_config_is_unavailable(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        context.lw_update_ordinary_dodge_wait(0.5)

        self.assertEqual(context.lw_ordinary_dodge_wait_for_task(task), 0.5)

    def test_sound_before_shift_does_not_confirm_current_dodge(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        context.lw_update_ordinary_dodge_wait(0.02)

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
        context.lw_update_ordinary_dodge_wait(0.5)

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
        self.assertEqual(task.dodge_results, ["自动完美"])
        self.assertIsNone(context._pending_action)

    def test_manual_perfect_sound_dispatches_without_extra_input(self):
        task = _FakeTask()
        task.executor = SimpleNamespace(paused=False)
        prepare_for_sound_dodge = mock.Mock()
        task.prepare_current_char_for_sound_dodge = prepare_for_sound_dodge
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

        with mock.patch("src.lw.sound_ext.logger.info") as log_info:
            context.lw_observe_sound_scores(0.0, 0.13)
            context._on_counter_triggered()
            context.execute_pending_action()

        self.assertEqual(task.outcomes, [True])
        self.assertEqual(task.dodge_results, ["手动完美"])
        self.assertGreater(context.last_dodge_time(), 0.0)
        resolved = context.last_dodge_outcome()
        self.assertTrue(resolved.perfect_dodge)
        self.assertEqual(resolved.result, "手动完美")
        self.assertLess(abs(time.monotonic() - resolved.anchor_monotonic), 0.1)
        trigger.execute_dodge.assert_not_called()
        trigger.execute_counter_attack.assert_not_called()
        prepare_for_sound_dodge.assert_called_once_with()
        self.assertIsNone(context._pending_action)
        self.assertTrue(
            any("声音闪避结果: 手动完美" in call.args[0] for call in log_info.call_args_list)
        )


class CombatDodgeOutcomeTests(unittest.TestCase):
    def test_each_dodge_result_runs_only_its_matching_character_hook(self):
        calls = []
        char = SimpleNamespace(
            on_dodge_counter=lambda: calls.append("counter"),
            on_ordinary_dodge=lambda: calls.append("ordinary"),
        )
        combat = SimpleNamespace(
            get_current_char=lambda raise_exception=False: char,
            log_error=lambda message: self.fail(message),
            info_set=mock.Mock(),
        )

        CombatExtMixin.after_sound_dodge_resolved(
            combat,
            perfect_dodge=False,
            dodge_result="普通闪避",
        )
        CombatExtMixin.after_sound_dodge_resolved(
            combat,
            perfect_dodge=True,
            dodge_result="自动完美",
        )

        self.assertEqual(calls, ["ordinary", "counter"])
        self.assertEqual(
            combat.info_set.call_args_list,
            [
                mock.call("闪避情况", "普通闪避"),
                mock.call("闪避情况", "自动完美"),
            ],
        )

    def test_requiem_ordinary_dodge_starts_normal_combo_after_wait(self):
        requiem = Requiem.__new__(Requiem)
        requiem._pending_double_4a = object()
        requiem._d4_front_left_ms = 100.0
        requiem.logger = mock.MagicMock()
        requiem.combo_attack = mock.MagicMock()

        requiem.on_ordinary_dodge()

        self.assertIsNone(requiem._pending_double_4a)
        self.assertEqual(requiem._d4_front_left_ms, 0.0)
        requiem.combo_attack.assert_called_once_with()

    def test_requiem_ordinary_dodge_resumes_plain_normals_during_coaxis(self):
        config_task = SimpleNamespace(
            config={RequiemCombatConfigTask.CONF_COAXIS_COMBAT_ENABLE: True},
            CONF_COAXIS_COMBAT_ENABLE=RequiemCombatConfigTask.CONF_COAXIS_COMBAT_ENABLE,
        )
        requiem = Requiem.__new__(Requiem)
        requiem.impl_id = REQUIEM_IMPL_ID
        requiem.is_dead = False
        requiem._pending_double_4a = object()
        requiem._d4_front_left_ms = 100.0
        requiem.logger = mock.MagicMock()
        requiem.combo_attack = mock.MagicMock()
        zankou = SimpleNamespace(
            impl_id=ZANKOU_MAIN_DPS_IMPL_ID,
            is_dead=False,
        )
        requiem.task = SimpleNamespace(
            chars=[requiem, zankou],
            get_task_by_class=lambda _task_class: config_task,
        )

        requiem.on_ordinary_dodge()

        self.assertIsNone(requiem._pending_double_4a)
        self.assertEqual(requiem._d4_front_left_ms, 0.0)
        requiem.combo_attack.assert_not_called()
        self.assertTrue(requiem._coaxis_ordinary_dodge_restart_pending)
        requiem.logger.info.assert_called_once_with(
            "安魂曲普通闪避: 专用等待结束, 请求重开完整无取消合轴普攻"
        )

    def test_requiem_switch_out_discards_unconsumed_ordinary_dodge_restart(self):
        requiem = Requiem.__new__(Requiem)
        requiem._coaxis_ordinary_dodge_restart_pending = True
        requiem.is_current_char = True
        requiem.has_intro = True

        requiem.switch_out()

        self.assertFalse(requiem._coaxis_ordinary_dodge_restart_pending)
        self.assertFalse(requiem.is_current_char)
        self.assertFalse(requiem.has_intro)


if __name__ == "__main__":
    unittest.main()
