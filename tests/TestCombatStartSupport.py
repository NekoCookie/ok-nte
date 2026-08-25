"""LW 开场辅助资源稳定与首切接线回归。"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.combat.BaseCombatTask import BaseCombatTask
from src.combat.planner import ActionSlot
from src.char.BaseChar import BaseChar
from src.lw.combat_templates import BuffSupport
from src.lw.requiem_zankou_axis import ZANKOU_MAIN_DPS_IMPL_ID
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
    def _intro_char(self, early_entry_abilities):
        task = SimpleNamespace(
            record_first_engage=mock.MagicMock(),
            lw_early_entry_ability_input_enabled=mock.MagicMock(
                return_value=early_entry_abilities
            ),
            combat_planner=mock.MagicMock(),
            refresh_cd=mock.MagicMock(),
        )
        char = BaseChar.__new__(BaseChar)
        char.task = task
        char.index = 0
        char.has_intro = True
        char.add_intro_motion_freeze = mock.MagicMock()
        char.intro_motion_freeze_duration = mock.MagicMock(return_value=1.5)
        char.wait_intro = mock.MagicMock()
        char._try_default_arc_click = mock.MagicMock()
        char.switch_next_char = mock.MagicMock()
        char.logger = mock.MagicMock()
        return char

    def test_intro_keeps_ru_attack_wait_when_early_entry_setting_is_off(self):
        char = self._intro_char(early_entry_abilities=False)

        BaseChar.perform(char)

        char.wait_intro.assert_called_once_with()
        char.task.combat_planner.perform_entry_expected_action.assert_not_called()

    def test_intro_runs_planner_entry_action_when_early_entry_setting_is_on(self):
        char = self._intro_char(early_entry_abilities=True)
        timeline = []
        char.wait_intro.side_effect = lambda *args, **kwargs: timeline.append(
            ("wait", kwargs.get("time_out"))
        )
        char.task.combat_planner.perform_entry_expected_action.side_effect = (
            lambda _: timeline.append(("action", None))
        )

        with mock.patch("src.char.BaseChar.time.time", side_effect=[100.0, 101.0]):
            BaseChar.perform(char)

        char.task.combat_planner.perform_entry_expected_action.assert_called_once_with(char)
        self.assertEqual(
            timeline[:3],
            [("wait", 1.0), ("action", None), ("wait", 0.5)],
        )

    def _entry_ability_task(self, enabled=True):
        task = BaseCombatTask.__new__(BaseCombatTask)
        config_task = SimpleNamespace(
            config={RequiemCombatConfigTask.CONF_COAXIS_EARLY_ENTRY_ABILITY_INPUT: enabled},
            CONF_COAXIS_EARLY_ENTRY_ABILITY_INPUT=(
                RequiemCombatConfigTask.CONF_COAXIS_EARLY_ENTRY_ABILITY_INPUT
            ),
        )
        task.get_task_by_class = mock.MagicMock(
            side_effect=lambda task_class: config_task
            if task_class is RequiemCombatConfigTask
            else (_ for _ in ()).throw(LookupError("unexpected config task"))
        )
        return task

    def test_switch_entry_uses_scoring_ultimate_or_skill_fallback(self):
        task = self._entry_ability_task()
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

        self.assertEqual(
            task.lw_switch_expected_entry_for_decision(target, ultimate_decision).slot,
            ActionSlot.ULTIMATE,
        )
        self.assertEqual(
            task.lw_switch_expected_entry_for_decision(target, skill_decision).slot,
            ActionSlot.SKILL,
        )
        self.assertIsNone(task.lw_switch_expected_entry_for_decision(target, entry_ultimate_decision))

    def test_switch_entry_prioritizes_ready_ultimate_over_skill_score(self):
        task = self._entry_ability_task()
        target = SimpleNamespace(
            index=2,
            ultimate_available=mock.MagicMock(return_value=True),
        )
        decision = SimpleNamespace(scoring_action_slot=ActionSlot.SKILL, expected_entry=None)

        self.assertEqual(
            task.lw_switch_expected_entry_for_decision(target, decision).slot,
            ActionSlot.ULTIMATE,
        )
        target.ultimate_available.assert_called_once_with()

    def test_zankou_axis_entry_does_not_fallback_to_an_ordinary_skill(self):
        task = self._entry_ability_task()
        target = SimpleNamespace(
            index=2,
            impl_id=ZANKOU_MAIN_DPS_IMPL_ID,
            ultimate_available=mock.MagicMock(return_value=False),
        )
        decision = SimpleNamespace(scoring_action_slot=None, expected_entry=None)

        self.assertIsNone(task.lw_switch_expected_entry_for_decision(target, decision))
        target.ultimate_available.assert_called_once_with()

    def test_switch_entry_keeps_explicit_skill_entry_over_a_ready_ultimate(self):
        task = self._entry_ability_task()
        target = SimpleNamespace(
            index=2,
            ultimate_available=mock.MagicMock(return_value=True),
        )
        decision = SimpleNamespace(
            scoring_action_slot=ActionSlot.ULTIMATE,
            expected_entry=SimpleNamespace(slot=ActionSlot.SKILL),
        )

        self.assertIsNone(task.lw_switch_expected_entry_for_decision(target, decision))
        target.ultimate_available.assert_not_called()

    def test_active_switch_target_is_not_marked_dead_by_another_char_revive_prompt(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        current = SimpleNamespace(index=3, mark_dead=mock.MagicMock())
        target = SimpleNamespace(index=2)
        task.chars = [SimpleNamespace(), SimpleNamespace(), target, current]
        task.box_of_screen = mock.MagicMock(return_value="revive_box")
        task.find_confirm = mock.MagicMock(return_value=True)
        task.is_char_at_index = mock.MagicMock(return_value=True)
        task.ensure_main = mock.MagicMock()

        self.assertTrue(task.lw_switch_target_entered_during_revive_prompt(current, target, "frame"))

        current.mark_dead.assert_called_once_with("revive prompt after switch target became active")
        task.ensure_main.assert_called_once_with(in_world=False)

    def test_inactive_switch_target_keeps_existing_revive_death_handling(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        current = SimpleNamespace(index=3, mark_dead=mock.MagicMock())
        target = SimpleNamespace(index=2)
        task.chars = [SimpleNamespace(), SimpleNamespace(), target, current]
        task.box_of_screen = mock.MagicMock(return_value="revive_box")
        task.find_confirm = mock.MagicMock(return_value=True)
        task.is_char_at_index = mock.MagicMock(return_value=False)
        task.ensure_main = mock.MagicMock()

        self.assertFalse(task.lw_switch_target_entered_during_revive_prompt(current, target, "frame"))

        current.mark_dead.assert_not_called()
        task.ensure_main.assert_not_called()

    def test_switch_entry_is_disabled_by_default_setting(self):
        task = self._entry_ability_task(enabled=False)
        target = SimpleNamespace(index=1)
        decision = SimpleNamespace(scoring_action_slot=ActionSlot.ULTIMATE, expected_entry=None)

        self.assertIsNone(task.lw_switch_expected_entry_for_decision(target, decision))

    def test_regular_switch_registers_the_supplemental_planner_entry_action(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        current = mock.MagicMock()
        target = mock.MagicMock(index=1)
        task.combat_session = SimpleNamespace(switch_enabled=True)
        task.chars = [current, target]
        task._wait_switch_in_guard = mock.MagicMock()
        task.lw_switch_expected_entry_for_decision = mock.MagicMock(
            return_value=SimpleNamespace(slot=ActionSlot.ULTIMATE)
        )
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

        task.lw_switch_expected_entry_for_decision.assert_called_once_with(target, decision)
        task.combat_planner.expect_entry_action.assert_called_once_with(
            target, task.lw_switch_expected_entry_for_decision.return_value
        )
        self.assertNotIn("send_switch_attack", task._switch_to_char.call_args.kwargs)
        self.assertTrue(task._switch_to_char.call_args.kwargs["retry_intro"])

    def test_strict_route_does_not_replan_the_switch_target_for_a_late_intro(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        current = mock.MagicMock()
        target = mock.MagicMock(index=1)
        expected_entry = SimpleNamespace(slot=ActionSlot.ULTIMATE)
        task.combat_session = SimpleNamespace(switch_enabled=True)
        task.chars = [current, target]
        task._wait_switch_in_guard = mock.MagicMock()
        task.lw_switch_expected_entry_for_decision = mock.MagicMock()
        task._switch_to_char = mock.MagicMock()
        decision = SimpleNamespace(
            target=target,
            has_intro=False,
            expected_entry=expected_entry,
            reason="strict route to zankou",
            scoring_action_slot=ActionSlot.ULTIMATE,
        )
        task.combat_planner = mock.MagicMock()
        task.combat_planner.decide_switch.return_value = decision
        task.combat_planner.has_strict_route.return_value = True

        task.switch_next_char(current)

        task._wait_switch_in_guard.assert_not_called()
        task._switch_to_char.assert_called_once()
        self.assertIs(task._switch_to_char.call_args.args[0], target)
        self.assertFalse(task._switch_to_char.call_args.kwargs["retry_intro"])

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
