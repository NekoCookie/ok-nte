"""Regression tests for the standalone Requiem and Zankou coordinated-axis test."""

import unittest
from unittest import mock

from src.char.Zankou import Zankou
from src.lw.requiem_zankou_axis import (
    CoordinatedAxisSettings,
    RequiemZankouAxisTester,
)
from src.lw.zankou_main_dps import ZankouMainDps


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


class TestRequiemZankouAxis(unittest.TestCase):
    def test_zankou_main_dps_inherits_current_ru_combat_logic(self):
        self.assertIs(ZankouMainDps.combat_plan, Zankou.combat_plan)
        self.assertIs(ZankouMainDps.perform_skill_combo, Zankou.perform_skill_combo)

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


if __name__ == "__main__":
    unittest.main()
