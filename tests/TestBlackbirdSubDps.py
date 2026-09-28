import unittest
from unittest import mock

from src.char.core.CharRegistry import char_registry
from src.combat.planner.types import ActionIntent
from src.lw.blackbird_sub_dps import (
    DARK_STAR_HOLD,
    DEFAULTS,
    BlackbirdSubDps,
    dark_star_hold_seconds,
)


class _Task:
    def __init__(self):
        self.freeze = 0.0

    def wait_until(self, *args, **kwargs):
        return False

    def find_one(self, feature):
        return False

    def time_elapsed_accounting_for_freeze(self, start):
        if start < 0:
            return 10000
        return _Task.clock - start - self.freeze


_Task.clock = 0.0


def _make_char(ult_ready=True, second_ult_ready=True, skill_ready=True, config=None):
    char = object.__new__(BlackbirdSubDps)
    char.task = _Task()
    char.logger = mock.Mock()
    char.in_ult = False
    char.is_current_char = True
    char.left_field_time = -1.0
    char.lw_skills_disabled_for_test = lambda: False
    char._lw_config = lambda: config
    state = {"ult": ult_ready, "skill": skill_ready}
    casts = []

    def click_ultimate():
        if not state["ult"]:
            return False
        casts.append("Q2" if char.in_ult else "Q1")
        state["ult"] = second_ult_ready and not char.in_ult
        return True

    def click_skill():
        if not state["skill"]:
            return False
        casts.append("E")
        state["skill"] = False
        return True

    char.ultimate_available = lambda check_color=True: state["ult"]
    char.skill_available = lambda: state["skill"]
    char.click_ultimate = click_ultimate
    char.click_skill = lambda down_time=0.01: click_skill()
    char.normal_attack = lambda: None
    char.now = lambda: _Task.clock
    char.sleep = lambda duration: setattr(_Task, "clock", _Task.clock + duration)
    return char, casts, state


def _run_entry(char):
    """Drive the entry generator like the planner: execute each allowed action."""

    plan = char.combat_plan(None)
    flow = plan.entry()
    result = None
    try:
        action = flow.send(None)
        while True:
            assert isinstance(action, ActionIntent)
            result = bool(action.is_allowed(None) and action.execute(None))
            action = flow.send(result)
    except StopIteration:
        pass
    return plan


class TestBlackbirdSubDpsEntry(unittest.TestCase):
    def setUp(self):
        _Task.clock = 0.0

    def test_entry_casts_q1_then_q2_then_skill(self):
        char, casts, _ = _make_char()

        _run_entry(char)

        self.assertEqual(casts, ["Q1", "Q2", "E"])
        self.assertFalse(char.in_ult)

    def test_entry_without_ultimate_energy_only_casts_skill(self):
        char, casts, _ = _make_char(ult_ready=False)

        _run_entry(char)

        self.assertEqual(casts, ["E"])

    def test_missing_second_ultimate_still_casts_skill_and_keeps_witch_state(self):
        char, casts, _ = _make_char(second_ult_ready=False)

        _run_entry(char)

        self.assertEqual(casts, ["Q1", "E"])
        self.assertTrue(char.in_ult)
        self.assertLessEqual(_Task.clock, BlackbirdSubDps.SECOND_ULTIMATE_WAIT + 0.11)

    def test_leftover_witch_state_finishes_with_q2_then_skill(self):
        char, casts, _ = _make_char()
        char.in_ult = True

        _run_entry(char)

        self.assertEqual(casts, ["Q2", "E"])
        self.assertFalse(char.in_ult)

    def test_test_mode_casts_nothing_and_claims_nothing(self):
        char, casts, _ = _make_char()
        char.lw_skills_disabled_for_test = lambda: True

        plan = _run_entry(char)

        self.assertEqual(casts, [])
        self.assertEqual(plan.claims, [])


class TestBlackbirdSubDpsReturn(unittest.TestCase):
    def setUp(self):
        _Task.clock = 100.0

    def _off_field(self, skill_ready=True, config=None, freeze=0.0):
        char, _, state = _make_char(skill_ready=skill_ready, config=config)
        char.is_current_char = False
        char.left_field_time = _Task.clock
        char.task.freeze = freeze
        return char, state

    def test_blocked_during_dark_star_windows_even_with_skill_ready(self):
        char, _ = self._off_field()

        _Task.clock += DEFAULTS[DARK_STAR_HOLD] - 0.5
        self.assertFalse(char.lw_can_switch_in())
        _Task.clock += 1.0
        self.assertTrue(char.lw_can_switch_in())

    def test_ultimate_animation_time_extends_the_hold(self):
        char, _ = self._off_field(freeze=4.0)

        _Task.clock += DEFAULTS[DARK_STAR_HOLD] + 1.0
        self.assertFalse(char.lw_can_switch_in())

    def test_waits_for_skill_after_the_windows(self):
        char, state = self._off_field(skill_ready=False)

        _Task.clock += DEFAULTS[DARK_STAR_HOLD] + 3.0
        self.assertFalse(char.lw_can_switch_in())
        state["skill"] = True
        self.assertTrue(char.lw_can_switch_in())

    def test_first_entry_and_current_field_are_never_blocked(self):
        char, _, _ = _make_char()
        self.assertTrue(char.lw_can_switch_in())
        char.is_current_char = False
        self.assertTrue(char.lw_can_switch_in())

    def test_hold_reads_config_with_default_fallback(self):
        cases = [
            (None, DEFAULTS[DARK_STAR_HOLD]),
            ({DARK_STAR_HOLD: 6}, 6.0),
            ({DARK_STAR_HOLD: "bad"}, DEFAULTS[DARK_STAR_HOLD]),
            ({DARK_STAR_HOLD: -3}, 0.0),
        ]
        for config, expected in cases:
            with self.subTest(config=config):
                self.assertEqual(dark_star_hold_seconds(config), expected)

    def test_template_is_registered(self):
        entry = char_registry.get("builtin:blackbird_sub_dps")

        self.assertIsNotNone(entry)
        self.assertIs(entry.char_cls, BlackbirdSubDps)
        self.assertEqual(entry.cn_name, "黑羽副C")


if __name__ == "__main__":
    unittest.main()
