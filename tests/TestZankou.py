import unittest

from src.Labels import Labels
from src.char.Zankou import Zankou
from src.combat.planner import Planner


class _SkillProbe:
    def __init__(self, feature):
        self.feature = feature
        self.seen = []

    def find_one(self, feature):
        self.seen.append(feature)
        return feature == self.feature


def _make_char(feature):
    char = object.__new__(Zankou)
    char.task = _SkillProbe(feature)
    clock = [0.0]
    sleeps = []
    heavy_attacks = []
    skill_clicks = []

    char.now = lambda: clock[0]

    def sleep(duration):
        sleeps.append(duration)
        clock[0] += duration

    def heavy_attack(duration=0.6):
        heavy_attacks.append(duration)
        clock[0] = 11.0

    char.sleep = sleep
    char.heavy_attack = heavy_attack
    char.click_skill = lambda: skill_clicks.append(True) or True
    char.find_ult_purple = lambda: False
    return char, sleeps, heavy_attacks, skill_clicks


class TestZankou(unittest.TestCase):
    def test_gold_skill_keeps_polling_with_half_second_heavy_attack(self):
        char, sleeps, heavy_attacks, skill_clicks = _make_char(Labels.zankou_skill_gold)

        result = char.perform_skill_combo()

        self.assertTrue(result)
        self.assertEqual(skill_clicks, [True])
        self.assertEqual(heavy_attacks, [0.5])
        self.assertIn(0.1, sleeps)
        self.assertNotIn(2, sleeps)

    def test_purple_skill_waits_two_seconds_and_finishes_combo(self):
        char, sleeps, heavy_attacks, skill_clicks = _make_char(Labels.zankou_skill_purple)

        result = char.perform_skill_combo()

        self.assertTrue(result)
        self.assertEqual(skill_clicks, [True])
        self.assertEqual(sleeps, [2])
        self.assertEqual(heavy_attacks, [])

    def test_plan_uses_current_combo_action_name_and_main_dps_role(self):
        char = object.__new__(Zankou)

        plan = char.combat_plan(None)

        self.assertEqual(plan.actions[0].name, "zankou_skill_combo")
        self.assertEqual(char.describe_role().role, Planner.Role.MAIN_DPS)
        self.assertEqual(char.describe_role().field_preference, Planner.FieldPreference.MAIN_DPS)


if __name__ == "__main__":
    unittest.main()
