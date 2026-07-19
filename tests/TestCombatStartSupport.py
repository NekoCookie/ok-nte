"""LW 开场辅助资源稳定与首切接线回归。"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.combat.BaseCombatTask import BaseCombatTask
from src.lw.combat_templates import BuffSupport


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def time(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


def make_support(states):
    support = BuffSupport.__new__(BuffSupport)
    support.is_current_char = False
    support.is_dead = False
    support.describe_role = mock.MagicMock(
        return_value=SimpleNamespace(combat_start_priority=0)
    )
    support.combat_start_resource_state = mock.MagicMock(side_effect=states)
    return support


class TestCombatStartResourceSettle(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.time_patcher = mock.patch("src.lw.combat_ext.time.time", self.clock.time)
        self.time_patcher.start()
        self.addCleanup(self.time_patcher.stop)

    def _task(self, chars):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.chars = chars
        task.COMBAT_START_RESOURCE_SETTLE_TIMEOUT = 0.6
        task.COMBAT_START_RESOURCE_SETTLE_INTERVAL = 0.08
        task.COMBAT_START_RESOURCE_STABLE_FRAMES = 2
        task.next_frame = mock.MagicMock()
        task.sleep = mock.MagicMock(side_effect=lambda duration, **_: self.clock.sleep(duration))
        task.log_info = mock.MagicMock()
        return task

    def test_waits_until_support_resource_is_stable_for_two_frames(self):
        current = mock.MagicMock()
        current.describe_role.return_value = SimpleNamespace(combat_start_priority=0)
        support = make_support([None, True, True])
        task = self._task([current, support])

        task.lw_settle_combat_start_resources()

        self.assertEqual(support.combat_start_resource_state.call_count, 3)
        self.assertEqual(task.next_frame.call_count, 2)
        task.log_info.assert_called_once_with(
            "combat start support resources settled: (True,)"
        )

    def test_timeout_keeps_unknown_resource_conservative(self):
        current = mock.MagicMock()
        current.describe_role.return_value = SimpleNamespace(combat_start_priority=0)
        support = make_support([None] * 20)
        task = self._task([current, support])

        task.lw_settle_combat_start_resources()

        self.assertGreater(task.next_frame.call_count, 1)
        task.log_info.assert_called_once_with(
            "combat start support resources settle timeout, keep conservative state"
        )

    def test_explicit_combat_start_target_skips_support_settle(self):
        explicit = mock.MagicMock()
        explicit.is_dead = False
        explicit.describe_role.return_value = SimpleNamespace(combat_start_priority=100)
        support = make_support([True])
        task = self._task([explicit, support])

        task.lw_settle_combat_start_resources()

        support.combat_start_resource_state.assert_not_called()
        task.next_frame.assert_not_called()


class TestCombatStartDispatch(unittest.TestCase):
    def test_settles_lw_resources_before_asking_planner(self):
        calls = []
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.in_animation = True
        task.lw_settle_combat_start_resources = mock.MagicMock(
            side_effect=lambda: calls.append("settle")
        )
        current = mock.MagicMock()
        task.get_current_char = mock.MagicMock(return_value=current)
        decision = mock.MagicMock(target=current)
        task.combat_planner = mock.MagicMock()
        task._switch_to_char = mock.MagicMock()
        task.combat_planner.decide_combat_start_char.side_effect = lambda _: (
            calls.append("decide") or decision
        )

        task.switch_to_combat_start_char()

        self.assertEqual(calls, ["settle", "decide"])
        self.assertFalse(task.in_animation)
        task._switch_to_char.assert_not_called()


if __name__ == "__main__":
    unittest.main()
