import threading
import time
import unittest
from types import SimpleNamespace

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
        self._listener = SimpleNamespace(counter_attack_threshold=0.12)
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
    def test_listener_publishes_scores_without_trigger_arbitration(self):
        listener = _ListenerHarness()
        observed = []
        listener.on_scores_updated = lambda dodge, counter: observed.append((dodge, counter))

        listener.lw_publish_scores(0.2, 0.13)

        self.assertEqual(observed, [(0.2, 0.13)])

    def test_perfect_sound_confirms_dodge_immediately(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        context.lw_update_perfect_dodge_wait(0.5)

        class Trigger:
            last_dodge_time = 0.0

            def execute_dodge(inner_self):
                context.lw_observe_sound_scores(0.0, 0.13)
                inner_self.last_dodge_time = time.time()

        started_at = time.monotonic()
        outcome = context.lw_execute_dodge_with_confirmation(Trigger(), task)
        context.lw_dispatch_dodge_outcome(task, outcome)

        self.assertTrue(outcome)
        self.assertLess(time.monotonic() - started_at, 0.1)
        self.assertEqual(task.outcomes, [True])

    def test_ordinary_dodge_waits_then_resumes_normal_flow(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        context.lw_update_perfect_dodge_wait(0.03)

        class Trigger:
            last_dodge_time = 0.0

            def execute_dodge(inner_self):
                inner_self.last_dodge_time = time.time()

        trigger = Trigger()

        started_at = time.monotonic()
        outcome = context.lw_execute_dodge_with_confirmation(trigger, task)
        elapsed = time.monotonic() - started_at
        context.lw_dispatch_dodge_outcome(task, outcome)

        self.assertFalse(outcome)
        self.assertGreaterEqual(elapsed, 0.025)
        self.assertEqual(task.outcomes, [False])

    def test_counter_trigger_confirms_while_action_queue_is_busy(self):
        task = _FakeTask()
        context = _SoundContextHarness(task)
        context._lw_begin_dodge_confirmation(task)

        self.assertTrue(context.lw_confirm_perfect_dodge_trigger())
        self.assertTrue(context._lw_dodge_confirmation.confirmed)

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
        context._listener = SimpleNamespace(counter_attack_threshold=0.12)
        context.lw_update_perfect_dodge_wait(0.5)

        class Trigger:
            def __init__(inner_self):
                inner_self.task = task
                inner_self.last_dodge_time = 0.0

            def execute_dodge(inner_self):
                context._on_counter_triggered()
                inner_self.last_dodge_time = time.time()

        context._trigger = Trigger()
        context._pending_task = task
        context._pending_action = "dodge"

        context.execute_pending_action()

        self.assertEqual(task.outcomes, [True])
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
