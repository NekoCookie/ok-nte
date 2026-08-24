"""LW 开场辅助资源稳定与首切接线回归。"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.char.BaseChar import BaseChar
from src.combat.BaseCombatTask import BaseCombatTask
from src.combat.planner import ActionSlot
from src.lw.combat_templates import BuffSupport
from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask


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
    support.combat_start_resource_observation = mock.MagicMock(side_effect=states)
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
        task.sleep = mock.MagicMock(side_effect=self.clock.sleep)
        task.log_info = mock.MagicMock()
        return task

    def test_waits_until_support_resource_is_stable_for_two_frames(self):
        current = mock.MagicMock()
        current.describe_role.return_value = SimpleNamespace(combat_start_priority=0)
        support = make_support([None, True, True])
        task = self._task([current, support])

        task.lw_settle_combat_start_resources()

        self.assertEqual(support.combat_start_resource_observation.call_count, 3)
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

        support.combat_start_resource_observation.assert_not_called()
        task.next_frame.assert_not_called()


class TestCombatStartDispatch(unittest.TestCase):
    def _switch_input_task(self, enabled=True):
        task = BaseCombatTask.__new__(BaseCombatTask)
        config_task = SimpleNamespace(
            config={RequiemCombatConfigTask.CONF_COAXIS_SWITCH_ABILITY_INPUT: enabled},
            CONF_COAXIS_SWITCH_ABILITY_INPUT=(
                RequiemCombatConfigTask.CONF_COAXIS_SWITCH_ABILITY_INPUT
            ),
        )
        task.get_task_by_class = mock.MagicMock(return_value=config_task)
        task.send_key = mock.MagicMock(return_value=True)
        return task

    def test_switch_input_uses_scoring_ultimate_or_skill_fallback(self):
        task = self._switch_input_task()
        target = SimpleNamespace(index=1)
        ultimate_decision = SimpleNamespace(
            scoring_action_slot=ActionSlot.ULTIMATE,
            expected_entry=None,
        )
        skill_decision = SimpleNamespace(scoring_action_slot=ActionSlot.SKILL, expected_entry=None)
        entry_ultimate_decision = SimpleNamespace(
            scoring_action_slot=None,
            expected_entry=SimpleNamespace(slot=ActionSlot.ULTIMATE),
        )

        self.assertEqual(task.lw_switch_input_for_decision(target, ultimate_decision), "ultimate")
        self.assertEqual(task.lw_switch_input_for_decision(target, skill_decision), "skill")
        self.assertEqual(task.lw_switch_input_for_decision(target, entry_ultimate_decision), "ultimate")

    def test_switch_input_is_disabled_by_default_setting(self):
        task = self._switch_input_task(enabled=False)
        target = SimpleNamespace(index=1)
        decision = SimpleNamespace(scoring_action_slot=ActionSlot.ULTIMATE, expected_entry=None)

        self.assertIsNone(task.lw_switch_input_for_decision(target, decision))

    def test_switch_skill_input_uses_the_target_long_press_duration(self):
        task = self._switch_input_task()
        target = SimpleNamespace(
            index=2,
            SKILL_DOWN_TIME=0.25,
            get_skill_key=lambda: "e",
        )

        self.assertTrue(task.lw_send_switch_input(target, "skill"))

        task.send_key.assert_called_once_with(
            "e",
            down_time=0.25,
            interval=0.1,
            action_name=("lw_switch_input", 2, "skill"),
        )

    def test_intro_repeats_the_selected_switch_input_instead_of_normal_attacks(self):
        clock = FakeClock()
        task = self._switch_input_task()
        char = SimpleNamespace(index=1, sleep=mock.MagicMock(side_effect=clock.sleep))
        char.logger = mock.MagicMock()
        task._lw_intro_switch_inputs = {1: (char, "ultimate")}
        task.get_current_char = mock.MagicMock(return_value=char)
        task.lw_send_switch_input = mock.MagicMock(return_value=True)

        with mock.patch("src.lw.combat_ext.time.time", clock.time):
            self.assertTrue(task.lw_wait_intro_with_switch_input(char, 0.3))

        self.assertGreaterEqual(task.lw_send_switch_input.call_count, 3)
        self.assertNotIn(1, task._lw_intro_switch_inputs)

    def test_base_char_intro_uses_the_task_switch_input_override(self):
        char = BaseChar.__new__(BaseChar)
        char.has_intro = True
        char.logger = mock.MagicMock()
        char.task = SimpleNamespace(
            lw_wait_intro_with_switch_input=mock.MagicMock(return_value=True),
        )
        char.continues_normal_attack = mock.MagicMock()

        char.wait_intro(time_out=0.3)

        char.task.lw_wait_intro_with_switch_input.assert_called_once_with(char, 0.3)
        char.continues_normal_attack.assert_not_called()

    def test_regular_switch_passes_the_optional_ability_input_to_the_switch_loop(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        current = mock.MagicMock()
        target = mock.MagicMock(index=1)
        task.combat_session = SimpleNamespace(switch_enabled=True)
        task.chars = [current, target]
        task._wait_switch_in_guard = mock.MagicMock()
        task.lw_switch_input_for_decision = mock.MagicMock(return_value="ultimate")
        task._switch_to_char = mock.MagicMock()
        decision = SimpleNamespace(
            target=target,
            has_intro=False,
            expected_entry=None,
            reason="target ultimate ready",
            scoring_action_slot=ActionSlot.ULTIMATE,
        )
        task.combat_planner = mock.MagicMock()
        task.combat_planner.decide_switch.return_value = decision
        task.combat_planner.has_strict_route.return_value = False

        task.switch_next_char(current)

        task.lw_switch_input_for_decision.assert_called_once_with(target, decision)
        self.assertEqual(task._switch_to_char.call_args.kwargs["switch_input"], "ultimate")

    def test_completed_lw_opening_skips_the_initial_attack(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.combat_session = None
        current = mock.MagicMock()
        task.get_current_char = mock.MagicMock(return_value=current)
        task.lw_prepare_combat_start = mock.MagicMock(return_value=True)
        task.click = mock.MagicMock()
        task.switch_to_combat_start_char = mock.MagicMock()

        session = task.begin_combat_session()

        self.assertIs(session.start_char, current)
        task.lw_prepare_combat_start.assert_called_once_with()
        task.click.assert_not_called()
        task.switch_to_combat_start_char.assert_not_called()

    def test_regular_start_keeps_the_initial_attack_after_lw_opening_declines(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.combat_session = None
        current = mock.MagicMock()
        task.get_current_char = mock.MagicMock(return_value=current)
        task.lw_prepare_combat_start = mock.MagicMock(return_value=False)
        task.click = mock.MagicMock()
        task.switch_to_combat_start_char = mock.MagicMock()

        task.begin_combat_session()

        task.click.assert_called_once_with(after_sleep=0.25)
        task.switch_to_combat_start_char.assert_called_once_with(lw_opening_checked=True)

    def test_completed_lw_opening_skips_the_regular_start_decision(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.lw_prepare_combat_start = mock.MagicMock(return_value=True)
        task.combat_planner = mock.MagicMock()

        task.switch_to_combat_start_char()

        task.lw_prepare_combat_start.assert_called_once_with()
        task.combat_planner.decide_combat_start_char.assert_not_called()

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
