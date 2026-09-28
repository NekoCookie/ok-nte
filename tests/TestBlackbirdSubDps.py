import unittest
from types import SimpleNamespace
from unittest import mock

from src.char.core.CharRegistry import char_registry
from src.lw.blackbird_sub_dps import (
    CONF_ULT_FIELD_TIME_LIMIT,
    DEFAULT_ULT_FIELD_TIME_LIMIT,
    BlackbirdSubDps,
)


class _Context:
    def is_action_allowed(self, char, action):
        return action.is_allowed(self)


def _make_char(skill_ready_at=None, config=None):
    char = object.__new__(BlackbirdSubDps)
    clock = [0.0]
    events = []
    char.logger = mock.Mock()
    char.now = lambda: clock[0]

    def sleep(duration):
        clock[0] += duration

    def click_skill():
        events.append(("skill", clock[0]))
        return True

    char.sleep = sleep
    char.normal_attack = lambda: events.append(("attack", clock[0]))
    char.skill_available = lambda: skill_ready_at is not None and clock[0] >= skill_ready_at
    char.click_skill = click_skill
    char.ultimate_available = lambda check_color=True: True
    char.lw_skills_disabled_for_test = lambda: False
    char._lw_config = lambda: config
    return char, clock, events


def _cycle_full_ru_skill():
    """RU's skill intent refuses to run while the cycle is full and a reaction mate exists."""

    return SimpleNamespace(is_allowed=lambda _: False)


class TestBlackbirdSubDps(unittest.TestCase):
    def test_enhanced_skill_fires_and_hands_off_even_with_full_cycle(self):
        char, clock, events = _make_char(skill_ready_at=1.5)

        char.perform_in_ult(_Context(), _cycle_full_ru_skill())

        skills = [time for kind, time in events if kind == "skill"]
        self.assertEqual(len(skills), 1)
        self.assertAlmostEqual(skills[0], 1.5, delta=0.11)
        self.assertLess(clock[0], 2.0)

    def test_witch_field_time_is_capped_when_enhanced_skill_never_unlocks(self):
        char, clock, events = _make_char(skill_ready_at=None)

        char.perform_in_ult(_Context(), _cycle_full_ru_skill())

        self.assertNotIn("skill", [kind for kind, _ in events])
        self.assertGreaterEqual(clock[0], DEFAULT_ULT_FIELD_TIME_LIMIT)
        self.assertLess(clock[0], DEFAULT_ULT_FIELD_TIME_LIMIT + 0.2)

    def test_test_mode_blocks_enhanced_skill(self):
        char, clock, events = _make_char(skill_ready_at=0.0)
        char.lw_skills_disabled_for_test = lambda: True

        char.perform_in_ult(_Context(), _cycle_full_ru_skill())

        self.assertNotIn("skill", [kind for kind, _ in events])

    def test_field_time_limit_reads_config_and_stays_within_witch_duration(self):
        cases = [
            (None, DEFAULT_ULT_FIELD_TIME_LIMIT),
            ({CONF_ULT_FIELD_TIME_LIMIT: 2.5}, 2.5),
            ({CONF_ULT_FIELD_TIME_LIMIT: "bad"}, DEFAULT_ULT_FIELD_TIME_LIMIT),
            ({CONF_ULT_FIELD_TIME_LIMIT: 99}, BlackbirdSubDps.ULT_DURATION),
            ({CONF_ULT_FIELD_TIME_LIMIT: -1}, 0.0),
        ]
        for config, expected in cases:
            with self.subTest(config=config):
                char, _, _ = _make_char(config=config)
                self.assertEqual(char.ult_field_time_limit(), expected)

    def test_template_is_registered(self):
        entry = char_registry.get("builtin:blackbird_sub_dps")

        self.assertIsNotNone(entry)
        self.assertIs(entry.char_cls, BlackbirdSubDps)
        self.assertEqual(entry.cn_name, "黑羽副C")


if __name__ == "__main__":
    unittest.main()
