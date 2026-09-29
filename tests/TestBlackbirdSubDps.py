import unittest
from unittest import mock

from src.char.core.CharRegistry import char_registry
from src.combat.planner.types import ActionIntent
from src.lw.blackbird_sub_dps import (
    BURST_HOLD,
    DARK_STAR_HOLD,
    DEFAULTS,
    SKILL_WAIT,
    BlackbirdSubDps,
    config_seconds,
    dark_star_setup_pending,
)
from src.lw.requiem_zankou_axis import (
    REQUIEM_IMPL_ID,
    ZANKOU_MAIN_DPS_IMPL_ID,
    perform_zankou_combat_axis,
    run_zankou_opening_gold_skill,
)
from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask
from tests.TestRequiemZankouAxis import (
    FakeCombatChar,
    FakeOpeningTask,
    make_combat_pair,
    make_config_task,
)


class _Clock:
    now = 0.0


class _Task:
    def __init__(self):
        self.freeze = 0.0
        self.chars = []

    def wait_until(self, *args, **kwargs):
        return False

    def find_one(self, feature):
        return False

    def time_elapsed_accounting_for_freeze(self, start):
        if start < 0:
            return 10000
        return _Clock.now - start - self.freeze


def _make_char(ult_ready=True, second_ult_ready=True, skill_ready=True, main_ult_ready=True):
    char = object.__new__(BlackbirdSubDps)
    char.task = _Task()
    char.logger = mock.Mock()
    char.in_ult = False
    char.is_current_char = True
    char.is_dead = False
    char.left_field_time = -1.0
    char.skill_ready_since = -1.0
    char.burst_hold_since = -1.0
    char.lw_skills_disabled_for_test = lambda: False
    char._lw_config = lambda: None
    state = {"ult": ult_ready, "skill": skill_ready, "main_ult": main_ult_ready}
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

    main_dps = mock.Mock(is_dead=False)
    main_dps.ultimate_available = lambda: state["main_ult"]
    char.get_teammates_by_role = lambda role: [main_dps]
    char.ultimate_available = lambda check_color=True: state["ult"]
    char.skill_available = lambda: state["skill"]
    char.click_ultimate = click_ultimate
    char.click_skill = lambda down_time=0.01: click_skill()
    char.normal_attack = lambda: None
    char.now = lambda: _Clock.now
    char._stamp = lambda: _Clock.now
    char.sleep = lambda duration: setattr(_Clock, "now", _Clock.now + duration)
    return char, casts, state


def _run_entry(char):
    """Drive the entry generator like the planner: execute each allowed action."""

    plan = char.combat_plan(None)
    flow = plan.entry()
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
        _Clock.now = 0.0

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
        self.assertLessEqual(_Clock.now, BlackbirdSubDps.SECOND_ULTIMATE_WAIT + 0.11)

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
        _Clock.now = 100.0

    def _off_field(self, **kwargs):
        char, _, state = _make_char(**kwargs)
        char.is_current_char = False
        char.left_field_time = _Clock.now
        return char, state

    def test_blocked_during_dark_star_windows_even_with_everything_ready(self):
        char, _ = self._off_field()

        _Clock.now += DEFAULTS[DARK_STAR_HOLD] - 0.5
        self.assertFalse(char.lw_can_switch_in())
        _Clock.now += 1.0
        self.assertTrue(char.lw_can_switch_in())

    def test_ultimate_time_stop_extends_the_dark_star_hold(self):
        char, _ = self._off_field()
        char.task.freeze = 4.0

        _Clock.now += DEFAULTS[DARK_STAR_HOLD] + 1.0
        self.assertFalse(char.lw_can_switch_in())

    def test_skill_waits_for_a_main_dps_ultimate_up_to_the_cap(self):
        char, state = self._off_field(main_ult_ready=False)
        _Clock.now += DEFAULTS[DARK_STAR_HOLD] + 1.0

        self.assertFalse(char.lw_can_switch_in())
        state["main_ult"] = True
        self.assertTrue(char.lw_can_switch_in())
        state["main_ult"] = False
        _Clock.now += DEFAULTS[SKILL_WAIT] - 0.5
        self.assertFalse(char.lw_can_switch_in())
        _Clock.now += 1.0
        self.assertTrue(char.lw_can_switch_in())

    def test_skill_cooldown_blocks_and_restarts_the_wait(self):
        char, state = self._off_field(skill_ready=False, main_ult_ready=False)
        _Clock.now += 60.0

        self.assertFalse(char.lw_can_switch_in())
        state["skill"] = True
        self.assertFalse(char.lw_can_switch_in())
        _Clock.now += DEFAULTS[SKILL_WAIT] + 0.1
        self.assertTrue(char.lw_can_switch_in())

    def test_first_entry_and_current_field_are_never_blocked(self):
        char, _, _ = _make_char()
        self.assertTrue(char.lw_can_switch_in())
        char.is_current_char = False
        self.assertTrue(char.lw_can_switch_in())

    def test_config_values_fall_back_to_defaults(self):
        cases = [
            (None, DEFAULTS[SKILL_WAIT]),
            ({SKILL_WAIT: 6}, 6.0),
            ({SKILL_WAIT: "bad"}, DEFAULTS[SKILL_WAIT]),
            ({SKILL_WAIT: -3}, 0.0),
        ]
        for config, expected in cases:
            with self.subTest(config=config):
                self.assertEqual(config_seconds(config, SKILL_WAIT), expected)

    def test_template_is_registered(self):
        entry = char_registry.get("builtin:blackbird_sub_dps")

        self.assertIsNotNone(entry)
        self.assertIs(entry.char_cls, BlackbirdSubDps)
        self.assertEqual(entry.cn_name, "黑羽副C")


class TestMainDpsBurstHold(unittest.TestCase):
    def setUp(self):
        _Clock.now = 100.0

    def _blackbird_with_mate(self, **kwargs):
        char, state = TestBlackbirdSubDpsReturn._off_field(self, **kwargs)
        char.left_field_time = -1.0
        mate = mock.Mock()
        mate.task = char.task
        char.task.chars = [mate, char]
        return char, mate, state

    def test_main_dps_holds_burst_while_blackbird_is_coming(self):
        char, mate, _ = self._blackbird_with_mate()

        self.assertTrue(dark_star_setup_pending(mate))

    def test_hold_is_capped(self):
        char, mate, _ = self._blackbird_with_mate()

        self.assertTrue(dark_star_setup_pending(mate))
        _Clock.now += DEFAULTS[BURST_HOLD] + 0.1
        self.assertFalse(dark_star_setup_pending(mate))

    def test_no_hold_once_dark_star_was_triggered(self):
        char, mate, _ = self._blackbird_with_mate()
        char.is_current_char = True
        self.assertFalse(dark_star_setup_pending(mate))

        char.is_current_char = False
        char.left_field_time = _Clock.now
        self.assertFalse(dark_star_setup_pending(mate))

    def test_no_hold_when_blackbird_skill_is_on_cooldown(self):
        char, mate, _ = self._blackbird_with_mate(skill_ready=False)

        self.assertFalse(dark_star_setup_pending(mate))

    def test_no_hold_without_blackbird_template(self):
        mate = mock.Mock()
        mate.task = mock.Mock(chars=[mate])

        self.assertFalse(dark_star_setup_pending(mate))


class TestMainDpsHoldWiring(unittest.TestCase):
    def test_zankou_first_ultimate_waits_but_awakened_second_does_not(self):
        _requiem, zankou, context = make_combat_pair(combat_enabled=True)
        zankou.lw_skills_disabled_for_test = lambda: False
        zankou.ultimate_available = lambda check_color=True: True

        with mock.patch("src.lw.zankou_main_dps.dark_star_setup_pending", return_value=True):
            plan = zankou.combat_plan(context)
            entry = plan.entry()
            first = next(entry)
            self.assertFalse(first.is_allowed(context))
            zankou._wait_for_awakened_second_ultimate = mock.MagicMock(return_value=True)
            second = entry.send(True)
            self.assertTrue(second.is_allowed(context))

    def test_requiem_keeps_ultimate_and_real_skill_for_dark_star(self):
        requiem, _zankou, context = make_combat_pair(combat_enabled=True)
        requiem._skills_disabled_for_test = lambda *args: False
        requiem.ultimate_available = lambda check_color=True: True
        requiem.skill_available = lambda: True
        requiem.is_real_skill_now = lambda: True

        with mock.patch("src.char.Requiem.dark_star_setup_pending", return_value=True):
            plan = requiem.combat_plan(context)
            actions = {action.name: action for action in plan.actions}
            self.assertFalse(actions["Requiem_ultimate"].is_allowed(context))
            self.assertFalse(actions["Requiem_real_skill"].is_allowed(context))
            self.assertFalse(requiem._skill_or_ult_ready())
        with mock.patch("src.char.Requiem.dark_star_setup_pending", return_value=False):
            plan = requiem.combat_plan(context)
            actions = {action.name: action for action in plan.actions}
            self.assertTrue(actions["Requiem_ultimate"].is_allowed(context))
            self.assertTrue(actions["Requiem_real_skill"].is_allowed(context))


class TestZankouGoldSkillWaitsForDarkStar(unittest.TestCase):
    HELD = "src.lw.blackbird_sub_dps.dark_star_setup_pending"

    def test_opening_gold_skill_is_deferred_while_blackbird_is_coming(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL: True}
        )
        requiem = FakeCombatChar(config_task)
        requiem.impl_id = REQUIEM_IMPL_ID
        zankou = FakeCombatChar(config_task, gold_skill_times=(1.0,))
        zankou.impl_id = ZANKOU_MAIN_DPS_IMPL_ID
        task = FakeOpeningTask(config_task, requiem, zankou, FakeCombatChar(config_task))

        with mock.patch(self.HELD, return_value=True):
            self.assertFalse(run_zankou_opening_gold_skill(task))

        self.assertEqual(task.switches, [])
        self.assertEqual([event for event in zankou.events if event[0] == "hold"], [])

    def test_axis_keeps_lit_gold_skill_until_dark_star(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT: True}
        )
        zankou = FakeCombatChar(config_task, gold_skill_times=(1.85,))
        requiem = FakeCombatChar(config_task)

        with mock.patch(self.HELD, return_value=True):
            self.assertTrue(perform_zankou_combat_axis(zankou, object(), requiem))

        self.assertEqual([event for event in zankou.events if event[0] == "gold_skill"], [])

    def test_post_dodge_gold_skill_also_waits_for_dark_star(self):
        config_task = make_config_task(
            **{
                RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT: True,
                RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION: 0.45,
            }
        )
        zankou = FakeCombatChar(config_task, dodge_times=(0.4,), gold_skill_times=(0.6,))
        requiem = FakeCombatChar(config_task)

        with mock.patch(self.HELD, return_value=True):
            self.assertTrue(perform_zankou_combat_axis(zankou, object(), requiem))

        self.assertEqual([event for event in zankou.events if event[0] == "gold_skill"], [])


if __name__ == "__main__":
    unittest.main()
