"""Regression tests for the standalone Requiem and Zankou coordinated-axis test."""

import time
import unittest
from types import SimpleNamespace
from unittest import mock

from src.Labels import Labels
from src.char.Requiem import Requiem
from src.char.BaseChar import BaseChar
from src.char.Zankou import Zankou
from src.combat.planner import ActionSlot
from src.lw.requiem_zankou_axis import (
    CoordinatedAxisSettings,
    REQUIEM_IMPL_ID,
    RequiemZankouAxisTester,
    ZANKOU_MAIN_DPS_IMPL_ID,
    coordinated_axis_settings,
    perform_requiem_combat_axis,
    perform_requiem_double_4a_coaxis,
    perform_requiem_free_skill_coaxis,
    perform_zankou_combat_axis,
    run_zankou_opening_gold_skill,
)
from src.lw.zankou_main_dps import ZankouMainDps
from src.tasks.trigger.AutoCombatTask import AutoCombatTask
from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        if duration < 0:
            raise AssertionError("axis tester must not sleep a negative duration")
        self.now += duration


class FakeAxisIO:
    def __init__(self):
        self.events = []
        self.task_enabled = True
        self.stop_after_attack_down = False
        self._attack_is_down = False

    def enabled(self):
        return self.task_enabled

    def trigger_pressed(self, _key):
        return self.stop_after_attack_down and self._attack_is_down

    def send_key(self, key):
        self.events.append(("key", key))
        return True

    def tap_attack(self):
        self.events.append(("tap",))

    def attack_down(self):
        self._attack_is_down = True
        self.events.append(("down",))

    def attack_up(self):
        self._attack_is_down = False
        self.events.append(("up",))

    def log(self, message):
        self.events.append(("log", message))


class FakeCombatChar:
    def __init__(
        self,
        config_task,
        dodge_times=(),
        dodge_results=(),
        gold_skill_times=(),
        gold_skill_consumed=True,
        gold_skill_consumed_after=1,
        cycle_full=False,
    ):
        self.task = SimpleNamespace(
            get_task_by_class=lambda _: config_task,
            last_dodge_time=lambda: self._last_dodge_time,
            last_sound_dodge_outcome=lambda: self._last_dodge_outcome,
            find_one=lambda feature: feature == Labels.zankou_skill_gold and self._gold_skill_ready,
            mouse_down=self._mouse_down,
            mouse_up=self._mouse_up,
        )
        self.clock = 0.0
        self.events = []
        self.last_switch_time = 0.0
        self._dodge_times = list(dodge_times)
        self._dodge_results = list(dodge_results)
        self._last_dodge_time = 0.0
        self._last_dodge_outcome = None
        self._gold_skill_times = list(gold_skill_times)
        self._gold_skill_ready = False
        self._gold_skill_consumed = gold_skill_consumed
        self._gold_skill_consumed_after = gold_skill_consumed_after
        self._gold_skill_inputs = 0
        self.has_intro = False
        self._cycle_full = cycle_full
        self._heavy_started_at = None

    def now(self):
        return self.clock

    def is_cycle_full(self):
        return self._cycle_full

    def add_intro_motion_freeze(self, _start):
        self.events.append(("intro_freeze", self.intro_motion_freeze_duration()))

    def intro_motion_freeze_duration(self):
        return coordinated_axis_settings(self).zankou_intro_wait_duration

    def wait_intro(self, time_out=-1, click=True):
        duration = self.intro_motion_freeze_duration() if time_out < 0 else time_out
        self.events.append(("intro_wait", duration, click))
        self._advance(duration)

    def normal_attack(self):
        self.events.append(("tap", self.clock))

    def sleep(self, duration):
        if duration < 0:
            raise AssertionError("axis tester must not sleep a negative duration")
        self.events.append(("sleep", duration))
        self._advance(duration)

    def heavy_attack(self, duration):
        self.events.append(("hold", duration))
        self._advance(duration)

    def _mouse_down(self):
        if self._heavy_started_at is not None:
            raise AssertionError("heavy attack input already held")
        self._heavy_started_at = self.clock
        self.events.append(("hold_start", self.clock))

    def _mouse_up(self):
        if self._heavy_started_at is None:
            return
        self.events.append(("hold", self.clock - self._heavy_started_at))
        self._heavy_started_at = None

    def send_skill_key(self, action_name=None, **_kwargs):
        self.events.append(("gold_skill", self.clock, action_name))
        self._gold_skill_inputs += 1
        if self._gold_skill_consumed and self._gold_skill_inputs >= self._gold_skill_consumed_after:
            self._gold_skill_ready = False
        return True

    def _advance(self, duration):
        end = self.clock + duration
        while self._dodge_times and self._dodge_times[0] <= end:
            dodge_at = self._dodge_times.pop(0)
            perfect_dodge = self._dodge_results.pop(0) if self._dodge_results else True
            self._last_dodge_time = dodge_at
            self._last_dodge_outcome = SimpleNamespace(
                perfect_dodge=perfect_dodge,
                result="自动完美" if perfect_dodge else "普通闪避",
                anchor_monotonic=dodge_at,
            )
        while self._gold_skill_times and self._gold_skill_times[0] <= end:
            self._gold_skill_ready = True
            self._gold_skill_times.pop(0)
        self.clock = end


class FakeOpeningTask:
    def __init__(
        self,
        config_task,
        current_char,
        zankou,
        opening_target,
        *,
        reaction_target=None,
        handoff_target=None,
    ):
        self._config_task = config_task
        self._current_char = current_char
        self.zankou = zankou
        self.chars = [current_char, zankou, opening_target]
        self.logger = mock.MagicMock()
        self.combat_planner = SimpleNamespace(
            decide_combat_start_char=mock.MagicMock(
                return_value=SimpleNamespace(target=opening_target, has_intro=True)
            ),
            decide_switch=mock.MagicMock(
                return_value=SimpleNamespace(target=handoff_target, has_intro=False)
            ),
            lw_switch_target_has_intro=mock.MagicMock(
                side_effect=lambda _current, target, available: (
                    available and target is reaction_target
                )
            ),
        )
        self.is_boss = mock.MagicMock(return_value=True)
        self.switches = []
        self.switch_attack_options = []
        for char in self.chars:
            char.task = self
            char.is_current_char = char is current_char

    def get_task_by_class(self, _task_class):
        return self._config_task

    def get_current_char(self, raise_exception=False):
        return self._current_char

    def find_one(self, feature):
        return feature == Labels.zankou_skill_gold and self.zankou._gold_skill_ready

    def next_frame(self):
        return None

    def _switch_to_char(
        self,
        switch_to,
        current_char,
        has_intro,
        log_prefix,
        send_switch_attack=True,
    ):
        self.switches.append((current_char, switch_to, has_intro, log_prefix))
        self.switch_attack_options.append(send_switch_attack)
        current_char.is_current_char = False
        switch_to.is_current_char = True
        switch_to.has_intro = has_intro
        self._current_char = switch_to


def make_config_task(combat_enabled=True, **overrides):
    config = {
        RequiemCombatConfigTask.CONF_COAXIS_COMBAT_ENABLE: combat_enabled,
        RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT: "关闭",
        RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_DURATION: 0.45,
        RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION: 2.0,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_SWITCH_DELAY: 0.5,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_INTRO_WAIT_DURATION: 1.25,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT: False,
        RequiemCombatConfigTask.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL: False,
        RequiemCombatConfigTask.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL_NON_BOSS: True,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_HOLD_DURATION: 1.8,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_NORMAL_DURATION: 0.45,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION: 0.5,
    }
    config.update(overrides)
    return SimpleNamespace(
        config=config,
        CONF_COAXIS_COMBAT_ENABLE=RequiemCombatConfigTask.CONF_COAXIS_COMBAT_ENABLE,
        CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT=(
            RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT
        ),
        CONF_COAXIS_REQUIEM_DURATION=RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_DURATION,
        CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION=(
            RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION
        ),
        CONF_COAXIS_ZANKOU_SWITCH_DELAY=(
            RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_SWITCH_DELAY
        ),
        CONF_COAXIS_ZANKOU_INTRO_WAIT_DURATION=(
            RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_INTRO_WAIT_DURATION
        ),
        CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT=(
            RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT
        ),
        CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL=(
            RequiemCombatConfigTask.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL
        ),
        CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL_NON_BOSS=(
            RequiemCombatConfigTask.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL_NON_BOSS
        ),
        CONF_COAXIS_ZANKOU_HOLD_DURATION=(
            RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_HOLD_DURATION
        ),
        CONF_COAXIS_ZANKOU_NORMAL_DURATION=(
            RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_NORMAL_DURATION
        ),
        CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION=(
            RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION
        ),
    )


def make_combat_pair(combat_enabled=True):
    config_task = make_config_task(combat_enabled=combat_enabled)
    task = SimpleNamespace(chars=[], get_task_by_class=lambda _: config_task)
    requiem = Requiem.__new__(Requiem)
    requiem.index = 0
    requiem.impl_id = REQUIEM_IMPL_ID
    requiem.is_dead = False
    requiem.task = task
    requiem._pending_double_4a = None
    zankou = ZankouMainDps.__new__(ZankouMainDps)
    zankou.index = 1
    zankou.impl_id = ZANKOU_MAIN_DPS_IMPL_ID
    zankou.is_dead = False
    zankou.task = task
    task.chars = [requiem, zankou]
    context = SimpleNamespace(chars=task.chars)
    return requiem, zankou, context


class TestRequiemZankouAxis(unittest.TestCase):
    def test_standard_intro_duration_uses_auto_combat_config_or_ru_default(self):
        char = BaseChar.__new__(BaseChar)
        char.task = SimpleNamespace(
            config={AutoCombatTask.CONF_INTRO_MOTION_DURATION: 2.25},
            CONF_INTRO_MOTION_DURATION=AutoCombatTask.CONF_INTRO_MOTION_DURATION,
        )
        self.assertEqual(char.intro_motion_freeze_duration(), 2.25)

        char.task.config = {}
        self.assertEqual(char.intro_motion_freeze_duration(), 1.5)

    def test_zankou_main_dps_keeps_ru_skill_combo_implementation(self):
        self.assertIs(ZankouMainDps.perform_skill_combo, Zankou.perform_skill_combo)

    def test_combat_switch_off_keeps_original_requiem_and_zankou_plans(self):
        requiem, zankou, context = make_combat_pair(combat_enabled=False)

        requiem_names = {action.name for action in requiem.combat_plan(context).actions}
        self.assertIn("Requiem_double_4a", requiem_names)
        self.assertNotIn("Requiem_coordinated_axis", requiem_names)
        with mock.patch.object(Zankou, "combat_plan", return_value="ru-plan") as ru_plan:
            self.assertEqual(zankou.combat_plan(context), "ru-plan")
        ru_plan.assert_called_once_with(context)

    def test_combat_switch_on_replaces_requiem_fallback_and_removes_zankou_skill(self):
        requiem, zankou, context = make_combat_pair(combat_enabled=True)

        requiem_plan = requiem.combat_plan(context)
        requiem_names = {action.name for action in requiem_plan.actions}
        self.assertIn("Requiem_coordinated_axis", requiem_names)
        self.assertNotIn("Requiem_double_4a", requiem_names)
        self.assertEqual(
            sum(action.slot == ActionSlot.SKILL for action in requiem_plan.actions),
            2,
        )
        requiem._maybe_trigger_g_skill = mock.MagicMock(return_value=False)
        requiem._skills_disabled_for_test = mock.MagicMock(return_value=True)
        self.assertEqual(next(requiem_plan.entry()).name, "Requiem_coordinated_axis")
        requiem._maybe_trigger_g_skill.assert_called_once_with()

        zankou_plan = zankou.combat_plan(context)
        zankou_names = {action.name for action in zankou_plan.actions}
        self.assertEqual(
            zankou_names,
            {"ZankouMainDps_ultimate", "ZankouMainDps_coordinated_axis"},
        )
        self.assertFalse(any(action.slot == ActionSlot.SKILL for action in zankou_plan.actions))
        zankou.find_ult_purple = mock.MagicMock(return_value=False)
        zankou_entry = zankou_plan.entry()
        self.assertEqual(next(zankou_entry).name, "ZankouMainDps_ultimate")
        self.assertEqual(zankou_entry.send(True).name, "ZankouMainDps_coordinated_axis")
        zankou.find_ult_purple.assert_called_once_with()

    def test_awakened_zankou_repeats_standard_ultimate_before_axis(self):
        _requiem, zankou, context = make_combat_pair(combat_enabled=True)
        zankou.logger = mock.MagicMock()
        zankou.find_ult_purple = mock.MagicMock(return_value=True)
        zankou._wait_for_awakened_second_ultimate = mock.MagicMock(return_value=True)

        entry = zankou.combat_plan(context).entry()
        first_ultimate = next(entry)
        second_ultimate = entry.send(True)
        coaxis = entry.send(True)

        self.assertEqual(first_ultimate.name, "ZankouMainDps_ultimate")
        self.assertEqual(second_ultimate.name, "ZankouMainDps_ultimate")
        self.assertIs(first_ultimate.execute, second_ultimate.execute)
        self.assertNotEqual(first_ultimate.identity_key(), second_ultimate.identity_key())
        self.assertEqual(coaxis.name, "ZankouMainDps_coordinated_axis")
        zankou.find_ult_purple.assert_called_once_with()
        zankou._wait_for_awakened_second_ultimate.assert_called_once_with()

    def test_awakened_zankou_continues_axis_when_second_ultimate_does_not_appear(self):
        _requiem, zankou, context = make_combat_pair(combat_enabled=True)
        zankou.logger = mock.MagicMock()
        zankou.find_ult_purple = mock.MagicMock(return_value=True)
        zankou._wait_for_awakened_second_ultimate = mock.MagicMock(return_value=False)

        entry = zankou.combat_plan(context).entry()
        self.assertEqual(next(entry).name, "ZankouMainDps_ultimate")
        self.assertEqual(entry.send(True).name, "ZankouMainDps_coordinated_axis")

    def test_zankou_does_not_wait_for_second_ultimate_after_failed_first_stage(self):
        _requiem, zankou, context = make_combat_pair(combat_enabled=True)
        zankou.find_ult_purple = mock.MagicMock(return_value=True)
        zankou._wait_for_awakened_second_ultimate = mock.MagicMock()

        entry = zankou.combat_plan(context).entry()
        self.assertEqual(next(entry).name, "ZankouMainDps_ultimate")
        self.assertEqual(entry.send(False).name, "ZankouMainDps_coordinated_axis")
        zankou._wait_for_awakened_second_ultimate.assert_not_called()

    def test_zankou_second_ultimate_poll_uses_bounded_point_one_second_cadence(self):
        _requiem, zankou, _context = make_combat_pair(combat_enabled=True)
        zankou.logger = mock.MagicMock()
        clock = [0.0]
        sleeps = []
        zankou.now = lambda: clock[0]

        def sleep(duration):
            sleeps.append(duration)
            clock[0] += duration

        zankou.sleep = sleep
        zankou.ultimate_available = mock.MagicMock(return_value=False)

        self.assertFalse(zankou._wait_for_awakened_second_ultimate())

        self.assertAlmostEqual(sum(sleeps), 0.8)
        self.assertTrue(all(duration <= 0.1 for duration in sleeps))
        self.assertEqual(zankou.ultimate_available.call_count, len(sleeps) + 1)

    def test_test_switch_skips_awakened_ultimate_detection_in_axis_plan(self):
        _requiem, zankou, context = make_combat_pair(combat_enabled=True)
        config_task = zankou.task.get_task_by_class(None)
        config_task.config[RequiemCombatConfigTask.CONF_DISABLE_SKILLS] = True
        zankou.find_ult_purple = mock.MagicMock()

        entry = zankou.combat_plan(context).entry()

        self.assertEqual(next(entry).name, "ZankouMainDps_coordinated_axis")
        zankou.find_ult_purple.assert_not_called()

    def test_combat_switch_requires_both_exact_main_dps_templates(self):
        requiem, zankou, context = make_combat_pair(combat_enabled=True)
        zankou.impl_id = "builtin:zankou"

        requiem_names = {action.name for action in requiem.combat_plan(context).actions}
        self.assertIn("Requiem_double_4a", requiem_names)
        with mock.patch.object(Zankou, "combat_plan", return_value="ru-plan") as ru_plan:
            self.assertEqual(zankou.combat_plan(context), "ru-plan")
        ru_plan.assert_called_once_with(context)

    def test_opening_gold_skill_returns_to_the_original_opening_target_without_ultimate(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL: True}
        )
        requiem = FakeCombatChar(config_task)
        requiem.impl_id = REQUIEM_IMPL_ID
        zankou = FakeCombatChar(config_task, gold_skill_times=(1.0,))
        zankou.impl_id = ZANKOU_MAIN_DPS_IMPL_ID
        support = FakeCombatChar(config_task)
        task = FakeOpeningTask(config_task, requiem, zankou, support)

        self.assertTrue(run_zankou_opening_gold_skill(task))

        task.combat_planner.decide_combat_start_char.assert_called_once_with(requiem)
        self.assertEqual(
            task.switches,
            [
                (requiem, zankou, False, "lw opening zankou gold skill"),
                (zankou, support, False, "lw opening zankou gold skill return"),
            ],
        )
        self.assertEqual(
            [event for event in zankou.events if event[0] == "gold_skill"],
            [("gold_skill", 1.8, "zankou_opening_gold_skill")],
        )
        self.assertEqual([event for event in zankou.events if event[0] == "hold"], [("hold", 1.8)])
        self.assertEqual(task.switch_attack_options, [False, False])

    def test_opening_gold_skill_waits_for_zankou_ring_entry_before_heavy_attack(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL: True}
        )
        requiem = FakeCombatChar(config_task, cycle_full=True)
        requiem.impl_id = REQUIEM_IMPL_ID
        zankou = FakeCombatChar(config_task, gold_skill_times=(2.5,))
        zankou.impl_id = ZANKOU_MAIN_DPS_IMPL_ID
        support = FakeCombatChar(config_task)
        task = FakeOpeningTask(
            config_task,
            requiem,
            zankou,
            support,
            reaction_target=zankou,
        )

        self.assertTrue(run_zankou_opening_gold_skill(task))

        self.assertEqual(
            task.switches,
            [
                (requiem, zankou, True, "lw opening zankou gold skill"),
                (zankou, support, False, "lw opening zankou gold skill return"),
            ],
        )
        self.assertEqual(
            [
                event
                for event in zankou.events
                if event[0] in {"intro_freeze", "intro_wait", "hold"}
            ],
            [
                ("intro_freeze", 1.25),
                ("intro_wait", 1.25, True),
                ("hold", 1.8),
            ],
        )
        self.assertFalse(zankou.has_intro)

    def test_opening_gold_skill_does_not_wait_when_ring_targets_another_character(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL: True}
        )
        requiem = FakeCombatChar(config_task, cycle_full=True)
        requiem.impl_id = REQUIEM_IMPL_ID
        zankou = FakeCombatChar(config_task, gold_skill_times=(1.0,))
        zankou.impl_id = ZANKOU_MAIN_DPS_IMPL_ID
        support = FakeCombatChar(config_task)
        task = FakeOpeningTask(
            config_task,
            requiem,
            zankou,
            support,
            reaction_target=support,
        )

        self.assertTrue(run_zankou_opening_gold_skill(task))

        self.assertFalse(task.switches[0][2])
        self.assertFalse(any(event[0] == "intro_wait" for event in zankou.events))
        self.assertEqual([event for event in zankou.events if event[0] == "hold"], [("hold", 1.8)])

    def test_opening_gold_skill_current_zankou_falls_back_to_partner_before_ultimate(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL: True}
        )
        zankou = FakeCombatChar(config_task, gold_skill_times=(1.0,))
        zankou.impl_id = ZANKOU_MAIN_DPS_IMPL_ID
        requiem = FakeCombatChar(config_task)
        requiem.impl_id = REQUIEM_IMPL_ID
        task = FakeOpeningTask(
            config_task,
            zankou,
            zankou,
            zankou,
            handoff_target=zankou,
        )
        task.chars = [zankou, requiem]

        self.assertTrue(run_zankou_opening_gold_skill(task))

        task.combat_planner.decide_switch.assert_called_once_with(zankou)
        self.assertEqual(
            task.switches,
            [(zankou, requiem, False, "lw opening zankou gold skill return")],
        )
        self.assertEqual([event for event in zankou.events if event[0] == "hold"], [("hold", 1.8)])

    def test_opening_gold_skill_can_skip_non_boss_battles(self):
        config_task = make_config_task(
            **{
                RequiemCombatConfigTask.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL: True,
                RequiemCombatConfigTask.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL_NON_BOSS: False,
            }
        )
        requiem = FakeCombatChar(config_task)
        requiem.impl_id = REQUIEM_IMPL_ID
        zankou = FakeCombatChar(config_task, gold_skill_times=(1.0,))
        zankou.impl_id = ZANKOU_MAIN_DPS_IMPL_ID
        support = FakeCombatChar(config_task)
        task = FakeOpeningTask(config_task, requiem, zankou, support)
        task.is_boss.return_value = False

        self.assertFalse(run_zankou_opening_gold_skill(task))

        task.is_boss.assert_called_once_with()
        task.combat_planner.decide_combat_start_char.assert_not_called()
        self.assertEqual(task.switches, [])
        self.assertEqual([event for event in zankou.events if event[0] == "hold"], [])

    def test_requiem_free_skill_uses_axis_followup_instead_of_old_break_sequence(self):
        requiem, zankou, context = make_combat_pair(combat_enabled=True)
        requiem.logger = mock.MagicMock()
        requiem.click_skill = mock.MagicMock(return_value=True)
        requiem._free_skill_break_a5 = mock.MagicMock()
        requiem.free_skill_followup_attack = mock.MagicMock()

        with mock.patch(
            "src.char.Requiem.perform_requiem_free_skill_coaxis", return_value=True
        ) as axis_followup:
            self.assertTrue(requiem._execute_free_skill(context))

        axis_followup.assert_called_once_with(requiem, context, zankou)
        requiem._free_skill_break_a5.assert_not_called()
        requiem.free_skill_followup_attack.assert_not_called()

    def test_test_switch_disables_zankou_e_q_outside_the_axis(self):
        _requiem, zankou, context = make_combat_pair(combat_enabled=False)
        config_task = zankou.task.get_task_by_class(None)
        config_task.config[RequiemCombatConfigTask.CONF_DISABLE_SKILLS] = True

        plan = zankou.combat_plan(context)

        self.assertEqual(
            [action.name for action in plan.actions],
            ["ZankouMainDps_test_normal_attacks"],
        )
        self.assertEqual(next(plan.entry()).name, "ZankouMainDps_test_normal_attacks")

    def test_requiem_pending_axis_switch_forces_departure_from_field_time(self):
        requiem, _zankou, _context = make_combat_pair(combat_enabled=True)
        requiem.skill_off_field_until = 0.0
        requiem._coaxis_switch_pending = True

        self.assertTrue(requiem.should_force_off_field())

        requiem._coaxis_switch_pending = False
        self.assertFalse(requiem.should_force_off_field())

    def test_real_skill_axis_routes_zankou_through_its_normal_ultimate_then_axis(self):
        requiem, zankou, _context = make_combat_pair(combat_enabled=True)
        config_task = requiem.task.get_task_by_class(None)
        config_task.config[RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT] = "2"
        requiem.skill_off_field_until = time.time() + 3.0
        requiem.logger = mock.MagicMock()
        context = mock.MagicMock(chars=[requiem, zankou])

        requiem._request_real_skill_configured_handoff(context)

        steps = context.request_route.call_args.args[0]
        self.assertEqual([step.slot for step in steps], [ActionSlot.ULTIMATE, ActionSlot.LEGACY_COMBO])
        self.assertTrue(steps[0].optional)
        self.assertFalse(requiem.lw_can_switch_in())

    def test_real_skill_handoff_can_strictly_switch_to_a_configured_non_zankou_slot(self):
        requiem, zankou, _context = make_combat_pair(combat_enabled=True)
        support = SimpleNamespace(index=2, is_dead=False)
        requiem.task.chars.append(support)
        config_task = requiem.task.get_task_by_class(None)
        config_task.config[RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT] = "3"
        requiem.skill_off_field_until = time.time() + 3.0
        requiem.logger = mock.MagicMock()
        context = mock.MagicMock(chars=[requiem, zankou, support])

        requiem._request_real_skill_configured_handoff(context)

        steps = context.request_route.call_args.args[0]
        self.assertEqual(len(steps), 1)
        self.assertTrue(steps[0].requires_switch)
        self.assertEqual(steps[0].target_indices, {2})
        self.assertFalse(requiem.lw_can_switch_in())

    def test_real_skill_handoff_ignores_the_current_requiem_slot(self):
        requiem, zankou, _context = make_combat_pair(combat_enabled=True)
        config_task = requiem.task.get_task_by_class(None)
        config_task.config[RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT] = "1"
        requiem.skill_off_field_until = time.time() + 3.0
        requiem.logger = mock.MagicMock()
        context = mock.MagicMock(chars=[requiem, zankou])

        requiem._request_real_skill_configured_handoff(context)

        context.request_route.assert_not_called()
        self.assertTrue(requiem.lw_can_switch_in())

    def test_zankou_axis_fills_normal_attacks_until_real_skill_handoff_ends(self):
        config_task = make_config_task()
        zankou = FakeCombatChar(config_task)
        partner = SimpleNamespace(lw_can_switch_in=lambda: zankou.now() >= 2.4)
        context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_zankou_combat_axis(zankou, context, partner))

        self.assertGreaterEqual(zankou.clock, 2.4)
        self.assertEqual(
            [event for event in zankou.events if event[0] == "hold"],
            [("hold", 1.8)],
        )
        tap_times = [event[1] for event in zankou.events if event[0] == "tap"]
        self.assertGreaterEqual(len(tap_times), 7)
        self.assertGreaterEqual(tap_times[-1], 2.35)
        context.request_switch.assert_called_once_with(
            partner,
            reason="zankou coordinated axis complete",
        )

    def test_zankou_axis_yields_to_planner_when_support_resource_appears_during_handoff(self):
        config_task = make_config_task()
        zankou = FakeCombatChar(config_task)
        zankou.should_yield_to_support = lambda: True
        partner = SimpleNamespace(lw_can_switch_in=lambda: False)
        context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_zankou_combat_axis(zankou, context, partner))

        context.request_switch.assert_not_called()
        self.assertFalse(getattr(zankou, "_coaxis_switch_pending", False))

    def test_one_round_uses_configured_keys_and_attack_sequence(self):
        clock = FakeClock()
        io = FakeAxisIO()
        settings = CoordinatedAxisSettings(
            requiem_switch_key="3",
            zankou_switch_key="1",
            requiem_attack_duration=0.45,
            zankou_switch_delay=0.4,
            zankou_hold_duration=1.8,
            zankou_normal_attack_duration=0.45,
        )
        tester = RequiemZankouAxisTester(io, settings)
        tester._trigger_was_down = False

        with mock.patch("src.lw.requiem_zankou_axis.time", clock):
            self.assertTrue(tester.run_round())

        self.assertEqual(
            io.events,
            [
                ("tap",),
                ("tap",),
                ("tap",),
                ("tap",),
                ("tap",),
                ("key", "1"),
                ("down",),
                ("up",),
                ("tap",),
                ("tap",),
                ("tap",),
                ("tap",),
                ("tap",),
                ("key", "3"),
            ],
        )
        self.assertAlmostEqual(clock.now, 3.25)

    def test_second_trigger_press_stops_and_releases_held_attack(self):
        clock = FakeClock()
        io = FakeAxisIO()
        io.stop_after_attack_down = True
        settings = CoordinatedAxisSettings(
            requiem_attack_duration=0,
            zankou_hold_duration=2.0,
        )
        tester = RequiemZankouAxisTester(io, settings)
        tester._trigger_was_down = False

        with mock.patch("src.lw.requiem_zankou_axis.time", clock):
            self.assertFalse(tester.run_round())

        self.assertEqual(io.events, [("key", "2"), ("down",), ("up",)])

    def test_initial_trigger_release_must_be_stable_before_stop_edge_is_armed(self):
        clock = FakeClock()
        io = FakeAxisIO()
        states = iter([True, False, True, *([False] * 8)])
        io.trigger_pressed = lambda _key: next(states, False)
        tester = RequiemZankouAxisTester(io, CoordinatedAxisSettings())

        with mock.patch("src.lw.requiem_zankou_axis.time", clock):
            self.assertTrue(tester._wait_for_initial_release())

        self.assertFalse(tester._trigger_was_down)
        self.assertGreaterEqual(clock.now, 0.16)

    def test_combat_actions_use_configured_timings_and_request_each_partner(self):
        config_task = make_config_task()
        requiem = FakeCombatChar(config_task)
        zankou = FakeCombatChar(config_task)
        requiem_context = SimpleNamespace(request_switch=mock.MagicMock())
        zankou_context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_requiem_combat_axis(requiem, requiem_context, zankou))
        self.assertEqual(
            [(name, round(at, 1)) for name, at in requiem.events if name == "tap"],
            [("tap", 0.0), ("tap", 0.1), ("tap", 0.2), ("tap", 0.3), ("tap", 0.4)],
        )
        requiem_context.request_switch.assert_called_once()
        args, kwargs = requiem_context.request_switch.call_args
        self.assertEqual(args, (zankou,))
        self.assertEqual(kwargs["reason"], "requiem coordinated axis complete")
        self.assertTrue(requiem._coaxis_switch_pending)
        kwargs["on_finish"]()
        self.assertFalse(requiem._coaxis_switch_pending)

        self.assertTrue(perform_zankou_combat_axis(zankou, zankou_context, requiem))
        self.assertEqual(
            [(name, round(duration, 1)) for name, duration in zankou.events if name == "hold"],
            [("hold", 1.8)],
        )
        self.assertEqual(
            [(name, round(at, 1)) for name, at in zankou.events if name == "tap"],
            [("tap", 1.8), ("tap", 1.9), ("tap", 2.0), ("tap", 2.1), ("tap", 2.2)],
        )
        zankou_context.request_switch.assert_called_once_with(
            requiem,
            reason="zankou coordinated axis complete",
        )

    def test_requiem_axis_finishes_pending_double_4a_before_handoff(self):
        config_task = make_config_task()
        requiem = FakeCombatChar(config_task)
        zankou = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())
        requiem._pending_double_4a = None

        original_sleep = requiem.sleep

        def trigger_double_4a(duration):
            original_sleep(duration)
            requiem._pending_double_4a = object()

        requiem.sleep = trigger_double_4a
        requiem._run_double_4a_outside = mock.MagicMock(
            side_effect=lambda: setattr(requiem, "_pending_double_4a", None)
        )
        requiem.logger = mock.MagicMock()

        self.assertTrue(perform_requiem_combat_axis(requiem, context, zankou))

        self.assertEqual(
            [(name, round(at, 1)) for name, at in requiem.events if name == "tap"],
            [("tap", 0.0)],
        )
        requiem._run_double_4a_outside.assert_called_once_with()
        context.request_switch.assert_called_once()
        args, kwargs = context.request_switch.call_args
        self.assertEqual(args, (zankou,))
        self.assertEqual(kwargs["reason"], "requiem perfect-dodge double-4a complete")
        self.assertTrue(requiem._coaxis_switch_pending)

    def test_requiem_ordinary_dodge_restarts_full_axis_duration(self):
        config_task = make_config_task()
        requiem = FakeCombatChar(config_task)
        zankou = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())
        requiem._pending_double_4a = None
        requiem._coaxis_ordinary_dodge_restart_pending = False
        requiem.logger = mock.MagicMock()
        original_sleep = requiem.sleep
        triggered = False

        def trigger_ordinary_dodge(duration):
            nonlocal triggered
            original_sleep(duration)
            if not triggered:
                triggered = True
                requiem._coaxis_ordinary_dodge_restart_pending = True

        requiem.sleep = trigger_ordinary_dodge

        self.assertTrue(perform_requiem_combat_axis(requiem, context, zankou))

        tap_times = [round(at, 2) for name, at in requiem.events if name == "tap"]
        self.assertEqual(tap_times, [0.0, 0.1, 0.2, 0.3, 0.4, 0.5])
        self.assertAlmostEqual(requiem.clock, 0.55)
        self.assertEqual(
            context.request_switch.call_args.kwargs["reason"],
            "requiem ordinary-dodge coordinated axis complete",
        )
        self.assertFalse(requiem._coaxis_ordinary_dodge_restart_pending)

    def test_requiem_pending_double_4a_action_uses_axis_handoff(self):
        requiem, zankou, context = make_combat_pair(combat_enabled=True)
        requiem._pending_double_4a = object()
        plan = requiem.combat_plan(context)
        continuation = next(
            action for action in plan.actions if action.name == "Requiem_double_4a_continue"
        )

        with mock.patch(
            "src.char.Requiem.perform_requiem_double_4a_coaxis",
            return_value=True,
        ) as finish_double_4a:
            self.assertTrue(continuation.execute(context))

        finish_double_4a.assert_called_once_with(requiem, context, zankou)

    def test_requiem_double_4a_axis_handoff_returns_success(self):
        config_task = make_config_task()
        requiem = FakeCombatChar(config_task)
        zankou = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())
        requiem._pending_double_4a = object()
        continuations = iter((object(), None))
        requiem._run_double_4a_outside = mock.MagicMock(
            side_effect=lambda: setattr(requiem, "_pending_double_4a", next(continuations))
        )
        requiem.logger = mock.MagicMock()

        self.assertTrue(perform_requiem_double_4a_coaxis(requiem, context, zankou))

        self.assertEqual(requiem._run_double_4a_outside.call_count, 2)
        context.request_switch.assert_called_once()
        self.assertEqual(
            context.request_switch.call_args.kwargs["reason"],
            "requiem perfect-dodge double-4a complete",
        )

    def test_requiem_double_4a_interrupted_by_ordinary_dodge_restarts_plain_axis(self):
        config_task = make_config_task()
        requiem = FakeCombatChar(config_task)
        zankou = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())
        requiem._pending_double_4a = object()
        requiem._coaxis_ordinary_dodge_restart_pending = False

        def ordinary_interrupt():
            requiem._pending_double_4a = None
            requiem._coaxis_ordinary_dodge_restart_pending = True

        requiem._run_double_4a_outside = mock.MagicMock(side_effect=ordinary_interrupt)
        requiem.logger = mock.MagicMock()

        self.assertTrue(perform_requiem_double_4a_coaxis(requiem, context, zankou))

        self.assertEqual(
            [round(at, 2) for name, at in requiem.events if name == "tap"],
            [0.0, 0.1, 0.2, 0.3, 0.4],
        )
        self.assertEqual(
            context.request_switch.call_args.kwargs["reason"],
            "requiem ordinary-dodge coordinated axis complete",
        )
        self.assertFalse(
            any(
                "perfect-dodge double-4a complete" in call.args[0]
                for call in requiem.logger.info.call_args_list
            )
        )

    def test_requiem_free_skill_axis_attacks_then_requests_zankou_without_support_ultimate(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION: 0.25}
        )
        requiem = FakeCombatChar(config_task)
        zankou = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_requiem_free_skill_coaxis(requiem, context, zankou))

        self.assertEqual(
            [(name, round(at, 2)) for name, at in requiem.events if name == "tap"],
            [("tap", 0.0), ("tap", 0.1), ("tap", 0.2)],
        )
        context.request_switch.assert_called_once()
        args, kwargs = context.request_switch.call_args
        self.assertEqual(args, (zankou,))
        self.assertEqual(kwargs["reason"], "requiem free skill coordinated axis complete")
        self.assertTrue(requiem._coaxis_switch_pending)

    def test_requiem_free_skill_axis_finishes_pending_double_4a_before_handoff(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION: 0.45}
        )
        requiem = FakeCombatChar(config_task)
        zankou = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())
        requiem._pending_double_4a = None

        original_sleep = requiem.sleep

        def trigger_double_4a(duration):
            original_sleep(duration)
            requiem._pending_double_4a = object()

        requiem.sleep = trigger_double_4a
        requiem._run_double_4a_outside = mock.MagicMock(
            side_effect=lambda: setattr(requiem, "_pending_double_4a", None)
        )
        requiem.logger = mock.MagicMock()

        self.assertTrue(perform_requiem_free_skill_coaxis(requiem, context, zankou))

        self.assertEqual(
            [(name, round(at, 1)) for name, at in requiem.events if name == "tap"],
            [("tap", 0.0)],
        )
        requiem._run_double_4a_outside.assert_called_once_with()
        self.assertEqual(
            context.request_switch.call_args.kwargs["reason"],
            "requiem perfect-dodge double-4a complete",
        )

    def test_requiem_free_skill_ordinary_dodge_uses_standard_full_axis_duration(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION: 0.2}
        )
        requiem = FakeCombatChar(config_task)
        zankou = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())
        requiem._pending_double_4a = None
        requiem._coaxis_ordinary_dodge_restart_pending = False
        requiem.logger = mock.MagicMock()
        original_sleep = requiem.sleep
        triggered = False

        def trigger_ordinary_dodge(duration):
            nonlocal triggered
            original_sleep(duration)
            if not triggered:
                triggered = True
                requiem._coaxis_ordinary_dodge_restart_pending = True

        requiem.sleep = trigger_ordinary_dodge

        self.assertTrue(perform_requiem_free_skill_coaxis(requiem, context, zankou))

        self.assertAlmostEqual(requiem.clock, 0.55)
        self.assertEqual(
            context.request_switch.call_args.kwargs["reason"],
            "requiem ordinary-dodge coordinated axis complete",
        )

    def test_requiem_free_skill_axis_defers_to_pending_support_ultimate(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION: 0.2}
        )
        requiem = FakeCombatChar(config_task)
        zankou = FakeCombatChar(config_task)
        support = SimpleNamespace(is_dead=False, ultimate_buff_pending=lambda: True)
        requiem.task.chars = [requiem, zankou, support]
        context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_requiem_free_skill_coaxis(requiem, context, zankou))

        self.assertEqual(
            [(name, round(at, 2)) for name, at in requiem.events if name == "tap"],
            [("tap", 0.0), ("tap", 0.1)],
        )
        context.request_switch.assert_not_called()
        self.assertFalse(hasattr(requiem, "_coaxis_switch_pending"))

    def test_zankou_sound_dodge_recovers_then_restarts_axis(self):
        config_task = make_config_task(
            **{
                RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION: 0.45,
            }
        )
        zankou = FakeCombatChar(config_task, dodge_times=(0.4,))
        requiem = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_zankou_combat_axis(zankou, context, requiem))

        self.assertEqual(
            [(name, round(duration, 2)) for name, duration in zankou.events if name == "hold"],
            [("hold", 0.4), ("hold", 1.8)],
        )
        self.assertEqual(
            [(name, round(at, 2)) for name, at in zankou.events if name == "hold_start"],
            [("hold_start", 0.0), ("hold_start", 0.85)],
        )
        self.assertEqual(
            [(name, round(at, 2)) for name, at in zankou.events if name == "tap"],
            [
                ("tap", 0.4),
                ("tap", 0.5),
                ("tap", 2.66),
                ("tap", 2.76),
                ("tap", 2.86),
                ("tap", 2.96),
                ("tap", 3.06),
            ],
        )
        context.request_switch.assert_called_once_with(
            requiem,
            reason="zankou coordinated axis complete",
        )

    def test_zankou_perfect_dodge_keeps_minimum_gap_before_restarted_heavy(self):
        config_task = make_config_task(
            **{
                RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION: 0.05,
            }
        )
        zankou = FakeCombatChar(config_task, dodge_times=(0.4,))
        requiem = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_zankou_combat_axis(zankou, context, requiem))

        recovery_taps = [at for name, at in zankou.events if name == "tap"][:2]
        heavy_starts = [at for name, at in zankou.events if name == "hold_start"]
        self.assertEqual([round(at, 2) for at in recovery_taps], [0.4, 0.5])
        self.assertEqual(round(heavy_starts[1] - recovery_taps[1], 2), 0.1)

    def test_zankou_releases_held_coaxis_attack_for_sound_dodge(self):
        zankou = ZankouMainDps.__new__(ZankouMainDps)
        zankou._coaxis_heavy_held = True
        zankou.task = SimpleNamespace(mouse_up=mock.Mock())

        zankou.prepare_for_sound_dodge()

        zankou.task.mouse_up.assert_called_once_with()
        self.assertFalse(zankou._coaxis_heavy_held)

    def test_zankou_combat_axis_does_not_reuse_test_switch_delay(self):
        config_task = make_config_task()
        zankou = FakeCombatChar(config_task)
        zankou.has_intro = True
        requiem = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_zankou_combat_axis(zankou, context, requiem))

        self.assertEqual(
            [(name, round(duration, 1)) for name, duration in zankou.events if name == "hold"],
            [("hold", 1.8)],
        )

    def test_zankou_gold_skill_interrupts_axis_and_requests_partner_switch(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT: True}
        )
        zankou = FakeCombatChar(config_task, gold_skill_times=(1.85,))
        requiem = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_zankou_combat_axis(zankou, context, requiem))

        self.assertEqual([event for event in zankou.events if event[0] == "hold"], [("hold", 1.8)])
        self.assertEqual(
            [(event[0], round(event[1], 1)) for event in zankou.events if event[0] == "tap"],
            [("tap", 1.8)],
        )
        self.assertEqual(
            [(event[0], round(event[1], 1)) for event in zankou.events if event[0] == "gold_skill"],
            [("gold_skill", 1.9)],
        )
        context.request_switch.assert_called_once_with(
            requiem,
            reason="zankou gold skill complete",
        )

    def test_zankou_gold_skill_failure_keeps_the_axis_on_its_original_deadline(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT: True}
        )
        zankou = FakeCombatChar(
            config_task,
            gold_skill_times=(1.85,),
            gold_skill_consumed=False,
        )
        requiem = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_zankou_combat_axis(zankou, context, requiem))

        self.assertEqual(
            [
                (event[0], round(event[1], 2), event[2])
                for event in zankou.events
                if event[0] == "gold_skill"
            ],
            [
                ("gold_skill", 1.91, "zankou_gold_skill"),
                ("gold_skill", 2.01, "zankou_gold_skill_retry_2"),
                ("gold_skill", 2.11, "zankou_gold_skill_retry_3"),
                ("gold_skill", 2.21, "zankou_gold_skill_retry_4"),
            ],
        )
        self.assertEqual(round(zankou.clock, 2), 2.26)
        self.assertEqual(
            [(event[0], round(event[1], 2)) for event in zankou.events if event[0] == "tap"],
            [
                ("tap", 1.81),
                ("tap", 1.91),
                ("tap", 2.01),
                ("tap", 2.11),
                ("tap", 2.21),
            ],
        )
        context.request_switch.assert_called_once_with(
            requiem,
            reason="zankou coordinated axis complete",
        )

    def test_zankou_gold_skill_retries_until_confirmed_within_axis_deadline(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT: True}
        )
        zankou = FakeCombatChar(
            config_task,
            gold_skill_times=(1.85,),
            gold_skill_consumed_after=4,
        )
        requiem = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_zankou_combat_axis(zankou, context, requiem))

        self.assertEqual(
            [
                (event[0], round(event[1], 2), event[2])
                for event in zankou.events
                if event[0] == "gold_skill"
            ],
            [
                ("gold_skill", 1.91, "zankou_gold_skill"),
                ("gold_skill", 2.01, "zankou_gold_skill_retry_2"),
                ("gold_skill", 2.11, "zankou_gold_skill_retry_3"),
                ("gold_skill", 2.21, "zankou_gold_skill_retry_4"),
            ],
        )
        context.request_switch.assert_called_once_with(
            requiem,
            reason="zankou gold skill complete",
        )

    def test_zankou_coaxis_intro_wait_is_silent_and_uses_its_own_duration(self):
        config_task = make_config_task()
        task = SimpleNamespace(chars=[], get_task_by_class=lambda _: config_task)
        requiem = Requiem.__new__(Requiem)
        requiem.impl_id = REQUIEM_IMPL_ID
        requiem.is_dead = False
        requiem.task = task
        zankou = ZankouMainDps.__new__(ZankouMainDps)
        zankou.impl_id = ZANKOU_MAIN_DPS_IMPL_ID
        zankou.is_dead = False
        zankou.has_intro = True
        zankou.task = task
        zankou.logger = mock.MagicMock()
        zankou.sleep = mock.MagicMock()
        task.chars = [requiem, zankou]

        self.assertEqual(zankou.intro_motion_freeze_duration(), 1.25)
        zankou.wait_intro()

        zankou.sleep.assert_called_once_with(1.25)

    def test_zankou_without_coaxis_keeps_standard_intro_behavior(self):
        zankou = ZankouMainDps.__new__(ZankouMainDps)
        zankou.impl_id = ZANKOU_MAIN_DPS_IMPL_ID
        zankou.is_dead = False
        zankou.has_intro = True
        zankou.task = SimpleNamespace(
            chars=[zankou],
            config={AutoCombatTask.CONF_INTRO_MOTION_DURATION: 2.25},
            CONF_INTRO_MOTION_DURATION=AutoCombatTask.CONF_INTRO_MOTION_DURATION,
            get_task_by_class=lambda _: make_config_task(combat_enabled=False),
        )
        zankou.logger = mock.MagicMock()
        zankou.continues_normal_attack = mock.MagicMock()

        zankou.wait_intro()

        zankou.continues_normal_attack.assert_called_once_with(2.25)

    def test_zankou_normal_phase_sound_dodge_recovers_then_restarts_axis(self):
        config_task = make_config_task(
            **{
                RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION: 0.45,
            }
        )
        zankou = FakeCombatChar(config_task, dodge_times=(1.9,))
        requiem = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_zankou_combat_axis(zankou, context, requiem))

        self.assertEqual(
            [(name, round(duration, 2)) for name, duration in zankou.events if name == "hold"],
            [("hold", 1.8), ("hold", 1.8)],
        )
        self.assertEqual(
            [(name, round(at, 2)) for name, at in zankou.events if name == "tap"],
            [
                ("tap", 1.81),
                ("tap", 1.91),
                ("tap", 2.01),
                ("tap", 4.16),
                ("tap", 4.26),
                ("tap", 4.36),
                ("tap", 4.46),
                ("tap", 4.56),
            ],
        )
        context.request_switch.assert_called_once_with(
            requiem,
            reason="zankou coordinated axis complete",
        )

    def test_zankou_ordinary_dodge_restarts_heavy_without_recovery_normals(self):
        config_task = make_config_task(
            **{
                RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION: 0.45,
            }
        )
        zankou = FakeCombatChar(
            config_task,
            dodge_times=(1.9,),
            dodge_results=(False,),
        )
        requiem = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_zankou_combat_axis(zankou, context, requiem))

        self.assertEqual(
            [(name, round(at, 2)) for name, at in zankou.events if name == "tap"],
            [
                ("tap", 1.81),
                ("tap", 3.72),
                ("tap", 3.82),
                ("tap", 3.92),
                ("tap", 4.02),
                ("tap", 4.12),
            ],
        )
        context.request_switch.assert_called_once_with(
            requiem,
            reason="zankou coordinated axis complete",
        )


if __name__ == "__main__":
    unittest.main()
