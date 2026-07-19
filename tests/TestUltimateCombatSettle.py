"""LW 大招前战斗检测稳定等待回归测试。"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.combat.BaseCombatTask import BaseCombatTask


class FakeClock:
    def __init__(self, now=100.0):
        self.now = now

    def time(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


class _SettleTask(BaseCombatTask):
    @property
    def combat_detect_uncertain(self):
        return self.uncertain


def make_task(clock, uncertain=True):
    task = _SettleTask.__new__(_SettleTask)
    task.uncertain = uncertain
    task.log_info = mock.MagicMock()
    task.next_frame = mock.MagicMock()
    task.check_combat = mock.MagicMock()
    task.combat_detect = mock.MagicMock()
    task.middle_click = mock.MagicMock()
    task.openvino_clear_cache = mock.MagicMock()
    task.sleep = mock.MagicMock(side_effect=clock.sleep)
    task.get_current_char = mock.MagicMock()
    task.is_in_team = mock.MagicMock(return_value=True)
    task.in_animation = False
    return task


def make_char():
    char = mock.MagicMock()
    char.ULTIMATE_COMBAT_SETTLE_TIMEOUT = 0.3
    char.ultimate_available.return_value = True
    return char


class TestUltimateCombatSettle(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.patcher = mock.patch("src.lw.combat_ext.time.time", self.clock.time)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_ru_combat_check_advances_uncertain_state(self):
        task = make_task(self.clock)
        char = make_char()
        task.get_current_char.return_value = char
        task.check_combat.side_effect = lambda: setattr(task, "uncertain", False)

        self.assertTrue(task.lw_wait_ultimate_combat_settle(char))

        task.check_combat.assert_called_once_with()
        char.fill_idle_attack.assert_called_once_with()

    def test_timeout_uses_policy_without_duplicate_retarget(self):
        task = make_task(self.clock)
        char = make_char()
        task.get_current_char.return_value = char

        self.assertTrue(task.lw_wait_ultimate_combat_settle(char))

        task.combat_detect.assert_not_called()
        task.middle_click.assert_not_called()
        task.openvino_clear_cache.assert_not_called()
        char.click.assert_not_called()
        task.log_info.assert_called_with(
            "click_ultimate forced after combat_detect_settle timeout 0.3s"
        )

    def test_timeout_rejects_stale_character(self):
        task = make_task(self.clock)
        char = make_char()
        task.get_current_char.return_value = mock.MagicMock()

        self.assertFalse(task.lw_wait_ultimate_combat_settle(char))

        char.ultimate_available.assert_not_called()


if __name__ == "__main__":
    unittest.main()
