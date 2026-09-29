import unittest
from types import SimpleNamespace
from unittest import mock

from src.char.BaseChar import BaseChar
from src.char.core.CharRegistry import char_registry
from src.char.Requiem import Requiem
from src.combat.BaseCombatTask import BaseCombatTask
from src.combat.planner import ActionSlot
from src.combat.planner.types import ActionIntent
from src.lw.blackbird_sub_dps import (
    DARK_STAR_HOLD,
    DEFAULTS,
    ROUND_SETUP,
    SAKIRI_CHARGE,
    ZANKOU_FLAME,
    BlackbirdSubDps,
    Step,
    config_seconds,
    dark_star_relay,
    dark_star_setup_pending,
    opening_burst_held,
    perform_dark_star_relay,
    preferred_reaction_target,
    round_allows_switch_in,
    sakiri_ultimate_held,
)
from src.lw.combat_templates import SakiriBuffSupport
from src.lw.requiem_zankou_axis import (
    REQUIEM_IMPL_ID,
    ZANKOU_MAIN_DPS_IMPL_ID,
    perform_zankou_combat_axis,
    run_zankou_opening_gold_skill,
)
from src.lw.zankou_main_dps import ZankouMainDps
from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask
from tests.TestRequiemZankouAxis import (
    FakeCombatChar,
    FakeOpeningTask,
    make_combat_pair,
    make_config_task,
)

Element = BaseChar.ElementType


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


def _make_blackbird(task=None, ult_ready=True, second_ult_ready=True, skill_ready=True):
    char = object.__new__(BlackbirdSubDps)
    char.task = task or _Task()
    char.logger = mock.Mock()
    char.in_ult = False
    char.is_current_char = True
    char.is_dead = False
    char._reset_dark_star_state()
    char.lw_skills_disabled_for_test = lambda: False
    char._lw_config = lambda: None
    state = {"ult": ult_ready, "skill": skill_ready, "main_ult": True}
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

    char._main_dps_ultimate_ready = lambda: state["main_ult"]
    char.ultimate_available = lambda check_color=True: state["ult"]
    char.skill_available = lambda: state["skill"]
    char.click_ultimate = click_ultimate
    char.click_skill = lambda down_time=0.01: click_skill()
    char.normal_attack = lambda: None
    char.now = lambda: _Clock.now
    char._stamp = lambda: _Clock.now
    char.sleep = lambda duration: setattr(_Clock, "now", _Clock.now + duration)
    return char, casts, state


def _mate(cls, task, element):
    char = cls.__new__(cls)
    char.task = task
    char.logger = mock.Mock()
    char.element = element
    char.is_dead = False
    char.is_current_char = False
    char.last_ultimate_time = -1.0
    return char


def _team():
    """Blackbird off field with E and a main DPS ultimate ready; Sakiri currently on field."""

    task = _Task()
    blackbird, _, state = _make_blackbird(task)
    blackbird.is_current_char = False
    state["zankou_ult"] = True
    sakiri = _mate(SakiriBuffSupport, task, Element.RED)
    sakiri.is_current_char = True
    requiem = _mate(Requiem, task, Element.PURPLE)
    zankou = _mate(ZankouMainDps, task, Element.RED)
    zankou.lw_stored_flame = False
    zankou.ultimate_available = lambda check_color=True: state["zankou_ult"]
    task.chars = [sakiri, blackbird, requiem, zankou]
    team = SimpleNamespace(
        task=task, blackbird=blackbird, sakiri=sakiri, requiem=requiem, zankou=zankou,
        state=state,
    )

    def put_on_field(char):
        for member in task.chars:
            member.is_current_char = member is char

    team.put_on_field = put_on_field
    return team


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


class TestBlackbirdEntry(unittest.TestCase):
    def setUp(self):
        _Clock.now = 0.0

    def test_entry_casts_q1_then_q2_then_skill(self):
        char, casts, _ = _make_blackbird()

        _run_entry(char)

        self.assertEqual(casts, ["Q1", "Q2", "E"])
        self.assertFalse(char.in_ult)
        self.assertTrue(char.stint_cast_skill)

    def test_entry_without_ultimate_energy_only_casts_skill(self):
        char, casts, _ = _make_blackbird(ult_ready=False)

        _run_entry(char)

        self.assertEqual(casts, ["E"])

    def test_missing_second_ultimate_still_casts_skill_and_keeps_witch_state(self):
        char, casts, _ = _make_blackbird(second_ult_ready=False)

        _run_entry(char)

        self.assertEqual(casts, ["Q1", "E"])
        self.assertTrue(char.in_ult)
        self.assertLessEqual(_Clock.now, BlackbirdSubDps.SECOND_ULTIMATE_WAIT + 0.11)

    def test_leftover_witch_state_finishes_with_q2_then_skill(self):
        char, casts, _ = _make_blackbird()
        char.in_ult = True

        _run_entry(char)

        self.assertEqual(casts, ["Q2", "E"])

    def test_test_mode_casts_nothing_and_claims_nothing(self):
        char, casts, _ = _make_blackbird()
        char.lw_skills_disabled_for_test = lambda: True

        plan = _run_entry(char)

        self.assertEqual(casts, [])
        self.assertEqual(plan.claims, [])

    def test_entry_does_not_read_the_witch_form_from_screen(self):
        char, casts, _ = _make_blackbird()
        char.task.wait_until = mock.Mock()
        char.task.find_one = mock.Mock()

        _run_entry(char)

        char.task.wait_until.assert_not_called()
        char.task.find_one.assert_not_called()
        self.assertEqual(casts, ["Q1", "Q2", "E"])

    def test_ring_entry_skips_intro_attacks(self):
        char, _, _ = _make_blackbird()
        char.has_intro = True
        char.round_start = _Clock.now
        char.continues_normal_attack = mock.Mock()

        char.wait_intro()

        char.continues_normal_attack.assert_not_called()

    def test_template_is_registered(self):
        entry = char_registry.get("builtin:blackbird_sub_dps")

        self.assertIs(entry.char_cls, BlackbirdSubDps)
        self.assertEqual(entry.cn_name, "黑羽副C")


class TestDarkStarRoundSteps(unittest.TestCase):
    def setUp(self):
        _Clock.now = 100.0
        self.team = _team()
        self.blackbird = self.team.blackbird

    def test_round_waits_for_skill_and_a_main_dps_ultimate(self):
        self.team.state["skill"] = False
        self.assertIs(self.blackbird.dark_star_step(), Step.IDLE)

        self.team.state["skill"] = True
        self.team.state["main_ult"] = False
        self.assertIs(self.blackbird.dark_star_step(), Step.IDLE)
        _Clock.now += 60.0
        self.assertIs(self.blackbird.dark_star_step(), Step.IDLE)
        self.team.state["main_ult"] = True
        self.assertIs(self.blackbird.dark_star_step(), Step.SAKIRI)

    def test_steps_run_sakiri_then_flame_then_open(self):
        self.assertIs(self.blackbird.dark_star_step(), Step.SAKIRI)

        self.team.sakiri.last_ultimate_time = _Clock.now
        self.assertIs(self.blackbird.dark_star_step(), Step.FLAME)

        self.team.zankou.lw_stored_flame = True
        self.assertIs(self.blackbird.dark_star_step(), Step.OPEN)

    def test_flame_is_skipped_when_zankou_has_no_ultimate_this_round(self):
        self.team.sakiri.last_ultimate_time = _Clock.now
        self.team.state["zankou_ult"] = False

        self.assertIs(self.blackbird.dark_star_step(), Step.OPEN)

    def test_sakiri_ultimate_cast_just_before_the_round_counts(self):
        self.team.sakiri.last_ultimate_time = _Clock.now - 3.0
        self.team.zankou.lw_stored_flame = True

        self.assertIs(self.blackbird.dark_star_step(), Step.OPEN)

    def test_sakiri_charge_and_round_setup_are_capped(self):
        self.assertIs(self.blackbird.dark_star_step(), Step.SAKIRI)
        _Clock.now += DEFAULTS[SAKIRI_CHARGE] + 0.1
        self.assertIs(self.blackbird.dark_star_step(), Step.FLAME)
        _Clock.now += DEFAULTS[ROUND_SETUP]
        self.assertIs(self.blackbird.dark_star_step(), Step.LATE)
        self.assertFalse(dark_star_setup_pending(self.team.requiem))

    def test_flame_step_can_be_disabled(self):
        self.team.sakiri.last_ultimate_time = _Clock.now
        self.blackbird._lw_config = lambda: {ZANKOU_FLAME: False}

        self.assertIs(self.blackbird.dark_star_step(), Step.OPEN)

    def test_skill_swap_opens_the_dark_star_window(self):
        self.blackbird.stint_cast_skill = True
        self.blackbird.switch_out()

        self.assertTrue(self.blackbird.dark_star_opened)
        self.assertIs(self.blackbird.dark_star_step(), Step.WINDOW)
        self.team.task.freeze = 4.0
        _Clock.now += DEFAULTS[DARK_STAR_HOLD] + 1.0
        self.assertIs(self.blackbird.dark_star_step(), Step.WINDOW)
        _Clock.now += 4.0
        self.assertIsNot(self.blackbird.dark_star_step(), Step.WINDOW)

    def test_leaving_without_skill_does_not_open_a_window(self):
        self.blackbird.switch_out()

        self.assertFalse(self.blackbird.dark_star_opened)
        self.assertIsNot(self.blackbird.dark_star_step(), Step.WINDOW)

    def test_config_values_fall_back_to_defaults(self):
        self.assertEqual(config_seconds(None, ROUND_SETUP), DEFAULTS[ROUND_SETUP])
        self.assertEqual(config_seconds({ROUND_SETUP: 6}, ROUND_SETUP), 6.0)
        self.assertEqual(config_seconds({ROUND_SETUP: "x"}, ROUND_SETUP), DEFAULTS[ROUND_SETUP])
        self.assertEqual(config_seconds({ROUND_SETUP: -3}, ROUND_SETUP), 0.0)


class TestDarkStarRoundRouting(unittest.TestCase):
    def setUp(self):
        _Clock.now = 100.0
        self.team = _team()

    def allowed(self):
        team = self.team
        return {
            name: (
                team.blackbird.lw_can_switch_in()
                if char is team.blackbird
                else round_allows_switch_in(char)
            )
            for name, char in (
                ("sakiri", team.sakiri),
                ("blackbird", team.blackbird),
                ("requiem", team.requiem),
                ("zankou", team.zankou),
            )
            if not char.is_current_char
        }

    def test_sakiri_step_only_lets_sakiri_in(self):
        self.team.put_on_field(self.team.requiem)

        self.assertEqual(
            self.allowed(), {"sakiri": True, "blackbird": False, "zankou": False}
        )

    def test_flame_step_lets_zankou_and_requiem_axis_until_one_cycle_is_full(self):
        self.team.sakiri.last_ultimate_time = _Clock.now

        self.assertEqual(
            self.allowed(), {"blackbird": False, "requiem": True, "zankou": True}
        )
        self.team.put_on_field(self.team.zankou)
        self.assertEqual(
            self.allowed(), {"sakiri": False, "blackbird": False, "requiem": True}
        )
        self.team.put_on_field(self.team.requiem)
        self.assertEqual(
            self.allowed(), {"sakiri": False, "blackbird": False, "zankou": True}
        )

    def test_open_step_sends_blackbird_then_blackbird_into_requiem(self):
        self.team.sakiri.last_ultimate_time = _Clock.now
        self.team.zankou.lw_stored_flame = True

        self.assertEqual(
            self.allowed(), {"blackbird": True, "requiem": False, "zankou": False}
        )
        self.team.put_on_field(self.team.blackbird)
        self.team.blackbird.round_start = _Clock.now
        self.assertEqual(
            self.allowed(), {"sakiri": False, "requiem": True, "zankou": False}
        )

    def test_outside_a_round_only_blackbird_waits(self):
        self.team.state["skill"] = False

        self.assertEqual(
            self.allowed(), {"blackbird": False, "requiem": True, "zankou": True}
        )

    def test_reaction_target_skips_teammates_the_round_keeps_out(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.chars = self.team.task.chars
        task.element_reaction_counts = {}
        self.team.sakiri.last_ultimate_time = _Clock.now
        self.team.zankou.lw_stored_flame = True
        self.team.put_on_field(self.team.blackbird)
        self.team.blackbird.round_start = _Clock.now
        for index, char in enumerate(task.chars):
            char.index = index
            char.last_switch_time = float(index)

        self.assertIs(
            task.find_element_reaction_target(self.team.requiem), self.team.blackbird
        )

    def test_scorch_with_requiem_stores_zankou_flame(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.element_reaction_counts = {}
        task._update_element_reaction_info = lambda: None

        self.assertTrue(task.record_element_reaction(self.team.sakiri, self.team.requiem))
        self.assertFalse(self.team.zankou.lw_stored_flame)
        self.assertTrue(task.record_element_reaction(self.team.zankou, self.team.requiem))
        self.assertTrue(self.team.zankou.lw_stored_flame)


class TestDarkStarRoundHolds(unittest.TestCase):
    def setUp(self):
        _Clock.now = 100.0
        self.team = _team()

    def test_main_dps_ultimates_wait_for_every_round(self):
        self.assertTrue(dark_star_setup_pending(self.team.requiem))
        self.team.blackbird.dark_star_opened = True
        self.assertTrue(dark_star_setup_pending(self.team.requiem))

    def test_requiem_skills_and_gold_skill_wait_only_for_the_first_dark_star(self):
        self.assertTrue(opening_burst_held(self.team.zankou))
        self.team.blackbird.dark_star_opened = True
        self.assertFalse(opening_burst_held(self.team.zankou))

    def test_sakiri_keeps_ultimate_for_the_round(self):
        self.assertFalse(sakiri_ultimate_held(self.team.sakiri))
        self.team.sakiri.last_ultimate_time = _Clock.now
        self.assertTrue(sakiri_ultimate_held(self.team.sakiri))
        self.team.state["skill"] = False
        self.assertTrue(sakiri_ultimate_held(self.team.sakiri))

    def test_no_holds_without_blackbird_template(self):
        mate = mock.Mock()
        mate.task = mock.Mock(chars=[mate])

        self.assertFalse(dark_star_setup_pending(mate))
        self.assertFalse(opening_burst_held(mate))
        self.assertTrue(round_allows_switch_in(mate))


class TestSakiriChargesForTheRound(unittest.TestCase):
    def _sakiri(self, step, on_field=True, ult_ready=True):
        c = SakiriBuffSupport.__new__(SakiriBuffSupport)
        c.index = 1
        c.logger = mock.Mock()
        c.is_current_char = on_field
        c.team_has_main_dps = lambda: True
        c.recently_used_resource = lambda: False
        c.has_skill_resource = lambda: False
        c.needs_resource_probe = lambda: False
        c.skill_available = lambda: False
        c.ultimate_available = lambda: ult_ready
        c.ultimate_ready_now = lambda: ult_ready
        c.lw_skills_disabled_for_test = lambda: False
        patcher = mock.patch("src.lw.blackbird_sub_dps.round_step", return_value=step)
        patcher.start()
        self.addCleanup(patcher.stop)
        return c

    def test_on_field_sakiri_charges_while_the_round_waits_on_her(self):
        c = self._sakiri(Step.SAKIRI, ult_ready=False)

        plan = c.combat_plan(None)

        self.assertIn(f"{c}_charge_ultimate", [action.name for action in plan.actions])

    def test_off_field_sakiri_is_called_in_by_the_round(self):
        c = self._sakiri(Step.SAKIRI, on_field=False, ult_ready=False)

        plan = c.combat_plan(None)

        self.assertEqual(
            [claim.reason for claim in plan.claims], ["dark star round sakiri ultimate"]
        )

    def test_ready_ultimate_is_kept_outside_the_sakiri_step(self):
        c = self._sakiri(Step.IDLE)

        plan = c.combat_plan(None)

        ultimate = next(a for a in plan.actions if a.slot == ActionSlot.ULTIMATE)
        self.assertFalse(ultimate.is_allowed(None))
        self.assertEqual(plan.claims, [])


class TestMainDpsHoldWiring(unittest.TestCase):
    def test_zankou_first_ultimate_waits_but_awakened_second_does_not(self):
        _requiem, zankou, context = make_combat_pair(combat_enabled=True)
        zankou.lw_skills_disabled_for_test = lambda: False
        zankou.ultimate_available = lambda check_color=True: True
        zankou.lw_stored_flame = True

        with mock.patch("src.lw.zankou_main_dps.dark_star_setup_pending", return_value=True):
            entry = zankou.combat_plan(context).entry()
            first = next(entry)
            self.assertFalse(first.is_allowed(context))
            zankou._wait_for_awakened_second_ultimate = mock.MagicMock(return_value=True)
            second = entry.send(True)
            self.assertTrue(second.is_allowed(context))
        self.assertFalse(zankou.lw_stored_flame)

    def test_zankou_is_called_in_for_stored_flame(self):
        _requiem, zankou, context = make_combat_pair(combat_enabled=True)
        zankou.is_current_char = False

        with mock.patch("src.lw.zankou_main_dps.round_step", return_value=Step.FLAME):
            plan = zankou.combat_plan(context)

        self.assertEqual(
            [claim.reason for claim in plan.claims], ["dark star round stored flame"]
        )

    def test_requiem_ultimate_waits_every_round_but_skills_only_at_opening(self):
        requiem, _zankou, context = make_combat_pair(combat_enabled=True)
        requiem._skills_disabled_for_test = lambda *args: False
        requiem.ultimate_available = lambda check_color=True: True
        requiem.skill_available = lambda: True

        def actions(real_skill_now):
            requiem.is_real_skill_now = lambda: real_skill_now
            return {a.name: a for a in requiem.combat_plan(context).actions}

        pending = mock.patch("src.char.Requiem.dark_star_setup_pending", return_value=True)
        with pending, mock.patch("src.char.Requiem.opening_burst_held", return_value=False):
            self.assertFalse(actions(True)["Requiem_ultimate"].is_allowed(context))
            self.assertTrue(actions(True)["Requiem_real_skill"].is_allowed(context))
            self.assertTrue(actions(False)["Requiem_free_skill"].is_allowed(context))
        pending = mock.patch("src.char.Requiem.dark_star_setup_pending", return_value=True)
        with pending, mock.patch("src.char.Requiem.opening_burst_held", return_value=True):
            self.assertFalse(actions(True)["Requiem_real_skill"].is_allowed(context))
            self.assertFalse(actions(False)["Requiem_free_skill"].is_allowed(context))
            self.assertFalse(requiem._skill_or_ult_ready())


class TestZankouGoldSkillWaitsForFirstDarkStar(unittest.TestCase):
    HELD = "src.lw.blackbird_sub_dps.opening_burst_held"

    def test_opening_gold_skill_is_left_to_the_dark_star_round(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL: True}
        )
        requiem = FakeCombatChar(config_task)
        requiem.impl_id = REQUIEM_IMPL_ID
        zankou = FakeCombatChar(config_task, gold_skill_times=(1.0,))
        zankou.impl_id = ZANKOU_MAIN_DPS_IMPL_ID
        task = FakeOpeningTask(config_task, requiem, zankou, FakeCombatChar(config_task))

        with mock.patch("src.lw.blackbird_sub_dps.dark_star_setup_pending", return_value=True):
            self.assertFalse(run_zankou_opening_gold_skill(task))

        self.assertEqual(task.switches, [])

    def test_axis_keeps_the_first_gold_skill(self):
        config_task = make_config_task(
            **{RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT: True}
        )
        zankou = FakeCombatChar(config_task, gold_skill_times=(1.85,))
        partner = FakeCombatChar(config_task)

        with mock.patch(self.HELD, return_value=True):
            self.assertTrue(perform_zankou_combat_axis(zankou, object(), partner))

        self.assertEqual([event for event in zankou.events if event[0] == "gold_skill"], [])

    def test_post_dodge_gold_skill_also_waits(self):
        config_task = make_config_task(
            **{
                RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT: True,
                RequiemCombatConfigTask.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION: 0.45,
            }
        )
        zankou = FakeCombatChar(config_task, dodge_times=(0.4,), gold_skill_times=(0.6,))
        partner = FakeCombatChar(config_task)

        with mock.patch(self.HELD, return_value=True):
            self.assertTrue(perform_zankou_combat_axis(zankou, object(), partner))

        self.assertEqual([event for event in zankou.events if event[0] == "gold_skill"], [])


class TestMainDpsRelayTheRoundSetup(unittest.TestCase):
    def test_relay_leaves_without_attacking(self):
        char = mock.Mock()

        self.assertTrue(perform_dark_star_relay(char))

        char.continues_normal_attack.assert_not_called()

    def test_relay_entry_skips_intro_attacks_and_switch_cooldown(self):
        requiem, zankou, _context = make_combat_pair(combat_enabled=True)
        for char, target in ((requiem, "src.char.Requiem.dark_star_relay"),
                             (zankou, "src.lw.zankou_main_dps.dark_star_relay")):
            char.has_intro = True
            char.logger = mock.Mock()
            char.continues_normal_attack = mock.Mock()
            char.sleep = mock.Mock()
            char.task.time_elapsed_accounting_for_freeze = mock.Mock(return_value=0.2)
            char.last_perform = 0.0
            with self.subTest(char=char), mock.patch(target, return_value=True),                     mock.patch("src.lw.zankou_main_dps.round_step", return_value=Step.OPEN):
                char.wait_intro()
                char.wait_switch_cd()
                char.continues_normal_attack.assert_not_called()
                char.sleep.assert_not_called()

    def test_requiem_skips_its_axis_and_leaves_during_round_setup(self):
        requiem, _zankou, context = make_combat_pair(combat_enabled=True)
        requiem.is_current_char = True
        requiem.skill_off_field_until = 0.0

        with mock.patch("src.char.Requiem.dark_star_relay", return_value=True):
            first = next(requiem.combat_plan(context).entry())
            self.assertEqual(first.name, "Requiem_dark_star_relay")
            self.assertTrue(requiem.should_force_off_field())

    def test_flame_step_relays_only_with_a_full_cycle(self):
        _Clock.now = 100.0
        team = _team()
        team.sakiri.last_ultimate_time = _Clock.now
        for char in (team.zankou, team.requiem):
            team.put_on_field(char)
            with self.subTest(char=char):
                char.is_cycle_full = lambda: False
                self.assertFalse(dark_star_relay(char))
                char.is_cycle_full = lambda: True
                self.assertTrue(dark_star_relay(char))
        team.zankou.lw_stored_flame = True
        team.put_on_field(team.requiem)
        team.requiem.is_cycle_full = lambda: False
        self.assertTrue(dark_star_relay(team.requiem))


class TestRequiemBanksZankouFlame(unittest.TestCase):
    def setUp(self):
        _Clock.now = 100.0
        self.team = _team()

    def test_full_requiem_cycle_goes_to_zankou_without_flame_outside_opening(self):
        team = self.team
        team.state["main_ult"] = False  # between rounds
        self.assertIs(preferred_reaction_target(team.requiem), team.zankou)

        team.zankou.lw_stored_flame = True
        self.assertIsNone(preferred_reaction_target(team.requiem))

    def test_opening_and_sakiri_steps_keep_the_default_target(self):
        team = self.team
        self.assertIsNone(preferred_reaction_target(team.requiem))  # SAKIRI step
        team.sakiri.last_ultimate_time = _Clock.now
        team.state["zankou_ult"] = False
        self.assertIs(team.blackbird.dark_star_step(), Step.OPEN)
        self.assertIsNone(preferred_reaction_target(team.requiem))

    def test_flame_config_off_and_other_sources_have_no_preference(self):
        team = self.team
        team.state["main_ult"] = False
        self.assertIsNone(preferred_reaction_target(team.zankou))
        team.blackbird._lw_config = lambda: {ZANKOU_FLAME: False}
        self.assertIsNone(preferred_reaction_target(team.requiem))

    def test_reaction_target_follows_the_preference(self):
        team = self.team
        team.state["main_ult"] = False
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.chars = team.task.chars
        task.element_reaction_counts = {}
        for index, char in enumerate(task.chars):
            char.index = index
            char.last_switch_time = float(index)

        self.assertIs(task.find_element_reaction_target(team.requiem), team.zankou)


class TestCombatStateSurvivesRosterReload(unittest.TestCase):
    def _task(self, chars, in_combat):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.chars = chars
        task._in_combat = in_combat
        return task

    def _reload(self, task, new_chars):
        pool = task._lw_export_combat_state(task.chars)
        task.chars = new_chars
        for char in new_chars:
            char.reset_state = lambda c=char: (
                c._reset_dark_star_state() if isinstance(c, BlackbirdSubDps) else None
            )
            char.reset_state()
            task._lw_import_combat_state(char, pool)

    def test_teammate_dropped_and_readded_mid_combat_keeps_its_records(self):
        _Clock.now = 100.0
        team = _team()
        team.zankou.lw_stored_flame = True
        team.blackbird.dark_star_opened = True
        team.blackbird.left_field_time = 90.0
        team.sakiri.last_ultimate_time = 95.0
        task = self._task(list(team.task.chars), in_combat=True)

        without_zankou = [team.sakiri, team.blackbird, team.requiem]
        self._reload(task, without_zankou)
        new_zankou = _mate(ZankouMainDps, team.task, Element.RED)
        new_zankou.lw_stored_flame = False
        self._reload(task, without_zankou + [new_zankou])

        self.assertTrue(new_zankou.lw_stored_flame)
        self.assertTrue(team.blackbird.dark_star_opened)
        self.assertEqual(team.blackbird.left_field_time, 90.0)
        self.assertEqual(team.sakiri.last_ultimate_time, 95.0)

    def test_new_combat_starts_from_clean_records(self):
        team = _team()
        team.zankou.lw_stored_flame = True
        task = self._task(list(team.task.chars), in_combat=True)
        task._lw_export_combat_state(task.chars)
        task._in_combat = False
        task.chars = []

        new_zankou = _mate(ZankouMainDps, team.task, Element.RED)
        new_zankou.lw_stored_flame = False
        self._reload(task, [new_zankou])

        self.assertFalse(new_zankou.lw_stored_flame)


if __name__ == "__main__":
    unittest.main()
