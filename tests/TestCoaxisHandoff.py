import unittest
from unittest import mock

from src.char.Requiem import Requiem
from src.combat.planner import ActionTag, CombatPlanner, FieldPreference
from src.lw.combat_templates import MainDps
from src.lw.requiem_zankou_axis import coaxis_handoff_target
from tests.TestCombatPlanner import FakeChar, FakeTask

RECENT_SWITCH = 100.0


def _no_resource(index, name, field_preference):
    # Only the planner's built-in field time makes this character a candidate.
    return FakeChar(
        index,
        name,
        field_preference=field_preference,
        priority_ready=lambda _: False,
    )


class TestCoaxisHandoff(unittest.TestCase):
    """A finished axis turn leaves the choice of the next character to planner scoring."""

    def setUp(self):
        self.zankou = _no_resource(0, "zankou", FieldPreference.MAIN_DPS)
        self.requiem = _no_resource(1, "requiem", FieldPreference.MAIN_DPS)
        self.sub_dps = _no_resource(2, "sub_dps", FieldPreference.SUB_DPS)
        # Requiem left the field moments ago, inside the planner's 0.9s re-entry cooldown.
        self.requiem.last_switch_time = RECENT_SWITCH

    def _planner(self, chars):
        task = FakeTask()
        task.chars = chars
        task.time_elapsed_accounting_for_freeze = lambda start, intro_motion_freeze=False: (
            0.3 if start == RECENT_SWITCH else 999
        )
        planner = CombatPlanner(task)
        planner.reset(chars)
        return planner

    def _hand_off(self, char, partner):
        char._coaxis_switch_pending = True
        char._coaxis_handoff_to = partner

    def test_idle_team_returns_to_axis_partner_despite_reentry_cooldown(self):
        planner = self._planner([self.zankou, self.requiem, self.sub_dps])
        self._hand_off(self.zankou, self.requiem)

        decision = planner.decide_switch(self.zankou)

        self.assertIs(decision.target, self.requiem)

    def test_reentry_cooldown_still_applies_without_an_axis_handoff(self):
        planner = self._planner([self.zankou, self.requiem, self.sub_dps])

        decision = planner.decide_switch(self.zankou)

        self.assertIs(decision.target, self.sub_dps)

    def test_ready_sub_dps_ultimate_outranks_axis_partner(self):
        blackbird = FakeChar(
            2,
            "blackbird",
            field_preference=FieldPreference.SUB_DPS,
            tags={ActionTag.ULTIMATE_ACTION},
        )
        planner = self._planner([self.zankou, self.requiem, blackbird])
        self._hand_off(self.zankou, self.requiem)

        decision = planner.decide_switch(self.zankou)

        self.assertIs(decision.target, blackbird)

    def test_cooldown_exemption_only_covers_the_recorded_partner(self):
        planner = self._planner([self.zankou, self.requiem, self.sub_dps])
        self._hand_off(self.zankou, self.requiem)

        self.assertTrue(planner.lw_ignores_switch_cooldown(self.zankou, self.requiem))
        self.assertFalse(planner.lw_ignores_switch_cooldown(self.zankou, self.sub_dps))
        self.zankou._coaxis_switch_pending = False
        self.assertFalse(planner.lw_ignores_switch_cooldown(self.zankou, self.requiem))


class TestRequiemHandoffLifecycle(unittest.TestCase):
    def _requiem(self):
        requiem = Requiem.__new__(Requiem)
        requiem._coaxis_switch_pending = True
        requiem._coaxis_handoff_to = object()
        return requiem

    def test_leaving_the_field_clears_the_handoff(self):
        requiem = self._requiem()
        with mock.patch.object(MainDps, "switch_out"):
            requiem.switch_out()

        self.assertIsNone(coaxis_handoff_target(requiem))
        self.assertFalse(requiem.should_force_off_field())

    def test_staying_current_after_switch_attempt_resumes_own_entry_flow(self):
        requiem = self._requiem()
        requiem.is_current_char = True
        with mock.patch.object(MainDps, "switch_next_char"):
            requiem.switch_next_char()

        self.assertIsNone(coaxis_handoff_target(requiem))
        self.assertFalse(requiem._coaxis_switch_pending)


if __name__ == "__main__":
    unittest.main()
