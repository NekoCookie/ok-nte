"""Regression tests for the standalone Requiem and Zankou coordinated-axis test."""

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
    perform_requiem_combat_axis,
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
        gold_skill_times=(),
        gold_skill_consumed=True,
        gold_skill_consumed_after=1,
    ):
        self.task = SimpleNamespace(
            get_task_by_class=lambda _: config_task,
            last_dodge_time=lambda: self._last_dodge_time,
            find_one=lambda feature: feature == Labels.zankou_skill_gold and self._gold_skill_ready,
        )
        self.clock = 0.0
        self.events = []
        self.last_switch_time = 0.0
        self._dodge_times = list(dodge_times)
        self._last_dodge_time = 0.0
        self._gold_skill_times = list(gold_skill_times)
        self._gold_skill_ready = False
        self._gold_skill_consumed = gold_skill_consumed
        self._gold_skill_consumed_after = gold_skill_consumed_after
        self._gold_skill_inputs = 0
        self.has_intro = False

    def now(self):
        return self.clock

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

    def send_skill_key(self, action_name=None, **_kwargs):
        self.events.append(("gold_skill", self.clock, action_name))
        self._gold_skill_inputs += 1
        if self._gold_skill_consumed and self._gold_skill_inputs >= self._gold_skill_consumed_after:
            self._gold_skill_ready = False
        return True

    def _advance(self, duration):
        end = self.clock + duration
        while self._dodge_times and self._dodge_times[0] <= end:
            self._last_dodge_time = self._dodge_times.pop(0)
        while self._gold_skill_times and self._gold_skill_times[0] <= end:
            self._gold_skill_ready = True
            self._gold_skill_times.pop(0)
        self.clock = end


class FakeOpeningTask:
    def __init__(self, config_task, current_char, zankou, opening_target):
        self._config_task = config_task
        self._current_char = current_char
        self.zankou = zankou
        self.chars = [current_char, zankou, opening_target]
        self.logger = mock.MagicMock()
        self.combat_planner = SimpleNamespace(
            decide_combat_start_char=mock.MagicMock(
                return_value=SimpleNamespace(target=opening_target, has_intro=True)
            )
        )
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
        self._current_char = switch_to


def make_config_task(combat_enabled=True, **overrides):
    config = {
        RequiemCombatConfigTask.CONF_COAXIS_COMBAT_ENABLE: combat_enabled,
        RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_DURATION: 0.45,
        RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION: 2.0,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_SWITCH_DELAY: 0.5,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_INTRO_WAIT_DURATION: 1.25,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT: False,
        RequiemCombatConfigTask.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL: False,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_HOLD_DURATION: 1.8,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_NORMAL_DURATION: 0.45,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION: 0.5,
    }
    config.update(overrides)
    return SimpleNamespace(
        config=config,
        CONF_COAXIS_COMBAT_ENABLE=RequiemCombatConfigTask.CONF_COAXIS_COMBAT_ENABLE,
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
        zankou.find_ult_purple = mock.MagicMock()
        zankou_entry = zankou_plan.entry()
        self.assertEqual(next(zankou_entry).name, "ZankouMainDps_ultimate")
        self.assertEqual(zankou_entry.send(True).name, "ZankouMainDps_coordinated_axis")
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
                (zankou, support, True, "lw opening zankou gold skill return"),
            ],
        )
        self.assertEqual(
            [event for event in zankou.events if event[0] == "gold_skill"],
            [("gold_skill", 1.8, "zankou_opening_gold_skill")],
        )
        self.assertEqual([event for event in zankou.events if event[0] == "hold"], [("hold", 1.8)])
        self.assertEqual(task.switch_attack_options, [False, False])

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
        self.assertEqual(zankou.events[0], ("hold", 1.8))
        self.assertIn(("hold", 1.8), zankou.events)
        self.assertEqual(
            [(name, round(at, 1)) for name, at in zankou.events if name == "tap"],
            [("tap", 1.8), ("tap", 1.9), ("tap", 2.0), ("tap", 2.1), ("tap", 2.2)],
        )
        zankou_context.request_switch.assert_called_once_with(
            requiem,
            reason="zankou coordinated axis complete",
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
            [event for event in zankou.events if event[0] == "hold"],
            [("hold", 1.8), ("hold", 1.8)],
        )
        self.assertEqual(
            [(name, round(at, 2)) for name, at in zankou.events if name == "tap"],
            [
                ("tap", 1.8),
                ("tap", 1.9),
                ("tap", 2.0),
                ("tap", 2.1),
                ("tap", 2.2),
                ("tap", 4.05),
                ("tap", 4.15),
                ("tap", 4.25),
                ("tap", 4.35),
                ("tap", 4.45),
            ],
        )
        context.request_switch.assert_called_once_with(
            requiem,
            reason="zankou coordinated axis complete",
        )

    def test_zankou_combat_axis_does_not_reuse_test_switch_delay(self):
        config_task = make_config_task()
        zankou = FakeCombatChar(config_task)
        zankou.has_intro = True
        requiem = FakeCombatChar(config_task)
        context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_zankou_combat_axis(zankou, context, requiem))

        self.assertEqual(zankou.events[0], ("hold", 1.8))

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
                ("gold_skill", 1.9, "zankou_gold_skill"),
                ("gold_skill", 2.0, "zankou_gold_skill_retry_2"),
                ("gold_skill", 2.1, "zankou_gold_skill_retry_3"),
                ("gold_skill", 2.2, "zankou_gold_skill_retry_4"),
            ],
        )
        self.assertEqual(round(zankou.clock, 2), 2.25)
        self.assertEqual(
            [(event[0], round(event[1], 2)) for event in zankou.events if event[0] == "tap"],
            [
                ("tap", 1.8),
                ("tap", 1.9),
                ("tap", 2.0),
                ("tap", 2.1),
                ("tap", 2.2),
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
                ("gold_skill", 1.9, "zankou_gold_skill"),
                ("gold_skill", 2.0, "zankou_gold_skill_retry_2"),
                ("gold_skill", 2.1, "zankou_gold_skill_retry_3"),
                ("gold_skill", 2.2, "zankou_gold_skill_retry_4"),
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
            [event for event in zankou.events if event[0] == "hold"],
            [("hold", 1.8), ("hold", 1.8)],
        )
        self.assertEqual(
            [(name, round(at, 2)) for name, at in zankou.events if name == "tap"],
            [
                ("tap", 1.8),
                ("tap", 1.9),
                ("tap", 2.0),
                ("tap", 2.1),
                ("tap", 2.2),
                ("tap", 2.3),
                ("tap", 4.15),
                ("tap", 4.25),
                ("tap", 4.35),
                ("tap", 4.45),
                ("tap", 4.55),
            ],
        )
        context.request_switch.assert_called_once_with(
            requiem,
            reason="zankou coordinated axis complete",
        )


if __name__ == "__main__":
    unittest.main()
