import unittest

from src.Labels import Labels
from src.char.Zankou import Zankou
from src.combat.planner import Planner


class _SkillProbe:
    def __init__(self, feature, clock):
        self.feature = feature
        self.seen = []
        self.mouse_events = []
        self._clock = clock

    def find_one(self, feature):
        self.seen.append(feature)
        return feature == self.feature

    def mouse_down(self):
        self.mouse_events.append("down")
        self._clock[0] = 11.0

    def mouse_up(self):
        self.mouse_events.append("up")


def _make_char(feature):
    char = object.__new__(Zankou)
    clock = [0.0]
    char.task = _SkillProbe(feature, clock)
    sleeps = []
    skill_clicks = []

    char.now = lambda: clock[0]

    def sleep(duration):
        sleeps.append(duration)
        clock[0] += duration

    char.sleep = sleep
    char.click_skill = lambda: skill_clicks.append(True) or True
    char.find_ult_purple = lambda: False
    return char, sleeps, skill_clicks


class TestZankou(unittest.TestCase):
    def test_gold_skill_charges_heavy_and_always_releases_the_mouse(self):
        char, sleeps, skill_clicks = _make_char(Labels.zankou_skill_gold)

        result = char.perform_skill_combo()

        self.assertTrue(result)
        self.assertEqual(skill_clicks, [True])
        self.assertEqual(char.task.mouse_events, ["down", "up"])
        self.assertIn(0.1, sleeps)
        self.assertNotIn(2, sleeps)

    def test_purple_skill_waits_two_seconds_and_finishes_combo(self):
        char, sleeps, skill_clicks = _make_char(Labels.zankou_skill_purple)

        result = char.perform_skill_combo()

        self.assertTrue(result)
        self.assertEqual(skill_clicks, [True])
        self.assertEqual(sleeps, [2])
        self.assertEqual(char.task.mouse_events, [])

    def test_plan_uses_current_combo_action_name_and_main_dps_role(self):
        char = object.__new__(Zankou)

        plan = char.combat_plan(None)

        self.assertEqual(plan.actions[0].name, "zankou_skill_combo")
        self.assertEqual(char.describe_role().role, Planner.Role.MAIN_DPS)
        self.assertEqual(char.describe_role().field_preference, Planner.FieldPreference.MAIN_DPS)


if __name__ == "__main__":
    unittest.main()
