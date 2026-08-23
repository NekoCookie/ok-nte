"""Regression tests for the standalone Requiem and Zankou coordinated-axis test."""

import unittest
from types import SimpleNamespace
from unittest import mock

from src.char.Requiem import Requiem
from src.char.Zankou import Zankou
from src.combat.planner import ActionSlot
from src.lw.requiem_zankou_axis import (
    CoordinatedAxisSettings,
    REQUIEM_IMPL_ID,
    RequiemZankouAxisTester,
    ZANKOU_MAIN_DPS_IMPL_ID,
    perform_requiem_combat_axis,
    perform_zankou_combat_axis,
)
from src.lw.zankou_main_dps import ZankouMainDps
from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, duration):
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
    def __init__(self, config_task, dodge_times=()):
        self.task = SimpleNamespace(
            get_task_by_class=lambda _: config_task,
            last_dodge_time=lambda: self._last_dodge_time,
        )
        self.clock = 0.0
        self.events = []
        self.last_switch_time = 0.0
        self._dodge_times = list(dodge_times)
        self._last_dodge_time = 0.0

    def now(self):
        return self.clock

    def normal_attack(self):
        self.events.append(("tap", self.clock))

    def sleep(self, duration):
        self.events.append(("sleep", duration))
        self._advance(duration)

    def heavy_attack(self, duration):
        self.events.append(("hold", duration))
        self._advance(duration)

    def _advance(self, duration):
        end = self.clock + duration
        while self._dodge_times and self._dodge_times[0] <= end:
            self._last_dodge_time = self._dodge_times.pop(0)
        self.clock = end

def make_config_task(combat_enabled=True, **overrides):
    config = {
        RequiemCombatConfigTask.CONF_COAXIS_COMBAT_ENABLE: combat_enabled,
        RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_INTERVAL: 0.2,
        RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_DURATION: 0.45,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_SWITCH_DELAY: 0.5,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_HOLD_DURATION: 1.8,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_NORMAL_DURATION: 0.45,
        RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION: 0.5,
    }
    config.update(overrides)
    return SimpleNamespace(
        config=config,
        CONF_COAXIS_COMBAT_ENABLE=RequiemCombatConfigTask.CONF_COAXIS_COMBAT_ENABLE,
        CONF_COAXIS_REQUIEM_INTERVAL=RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_INTERVAL,
        CONF_COAXIS_REQUIEM_DURATION=RequiemCombatConfigTask.CONF_COAXIS_REQUIEM_DURATION,
        CONF_COAXIS_ZANKOU_SWITCH_DELAY=(
            RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_SWITCH_DELAY
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
            requiem_attack_interval=0.2,
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
                ("key", "1"),
                ("down",),
                ("up",),
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

    def test_combat_actions_use_configured_timings_and_request_each_partner(self):
        config_task = make_config_task()
        requiem = FakeCombatChar(config_task)
        zankou = FakeCombatChar(config_task)
        requiem_context = SimpleNamespace(request_switch=mock.MagicMock())
        zankou_context = SimpleNamespace(request_switch=mock.MagicMock())

        self.assertTrue(perform_requiem_combat_axis(requiem, requiem_context, zankou))
        self.assertEqual(
            [event for event in requiem.events if event[0] == "tap"],
            [("tap", 0.0), ("tap", 0.2), ("tap", 0.4)],
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
            [("tap", 1.8), ("tap", 2.0), ("tap", 2.2)],
        )
        zankou_context.request_switch.assert_called_once_with(
            requiem,
            reason="zankou coordinated axis complete",
        )

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
                ("tap", 2.0),
                ("tap", 2.2),
                ("tap", 4.05),
                ("tap", 4.25),
                ("tap", 4.45),
            ],
        )
        context.request_switch.assert_called_once_with(
            requiem,
            reason="zankou coordinated axis complete",
        )

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
                ("tap", 2.0),
                ("tap", 2.2),
                ("tap", 2.4),
                ("tap", 4.25),
                ("tap", 4.45),
                ("tap", 4.65),
            ],
        )
        context.request_switch.assert_called_once_with(
            requiem,
            reason="zankou coordinated axis complete",
        )


if __name__ == "__main__":
    unittest.main()
