import types
import unittest
from unittest import mock

from src.lw.virtual_gamepad import (
    VirtualGamepadPulseTester,
    VirtualGamepadUnavailableError,
)
from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask


class _FakeGamepad:
    def __init__(self):
        self.calls = []

    def press_button(self, *, button):
        self.calls.append(("press", button))

    def release_button(self, *, button):
        self.calls.append(("release", button))

    def reset(self):
        self.calls.append(("reset",))

    def update(self):
        self.calls.append(("update",))


class TestVirtualGamepadPulseTester(unittest.TestCase):
    def setUp(self):
        self.gamepad = _FakeGamepad()
        self.module = types.SimpleNamespace(
            VX360Gamepad=lambda: self.gamepad,
            XUSB_BUTTON=types.SimpleNamespace(XUSB_GAMEPAD_A="A"),
        )

    def test_pulse_uses_a_and_close_resets_controller(self):
        tester = VirtualGamepadPulseTester(self.module)

        with mock.patch("src.lw.virtual_gamepad.time.sleep") as sleep:
            tester.pulse_a(0.08)

        self.assertTrue(tester.connected)
        self.assertEqual(
            [
                ("reset",),
                ("update",),
                ("press", "A"),
                ("update",),
                ("release", "A"),
                ("update",),
            ],
            self.gamepad.calls,
        )
        sleep.assert_called_once_with(0.08)

        tester.close()

        self.assertFalse(tester.connected)
        self.assertEqual([("reset",), ("update",)], self.gamepad.calls[-2:])

    def test_initialization_error_is_reported_as_unavailable(self):
        module = types.SimpleNamespace(
            VX360Gamepad=mock.Mock(side_effect=OSError("driver missing")),
            XUSB_BUTTON=types.SimpleNamespace(XUSB_GAMEPAD_A="A"),
        )
        tester = VirtualGamepadPulseTester(module)

        with self.assertRaises(VirtualGamepadUnavailableError):
            tester.pulse_a()


class TestRequiemGamepadPolling(unittest.TestCase):
    def _task(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task.config = {
            task.CONF_GAMEPAD_TEST: True,
            task.CONF_GAMEPAD_INTERVAL: 2.5,
        }
        task._gamepad_tester = None
        task._next_gamepad_pulse_at = 0.0
        task._gamepad_error_reported = False
        task.log_info = mock.Mock()
        task.log_error = mock.Mock()
        return task

    def test_enabled_poll_pulses_and_schedules_next_run(self):
        task = self._task()
        tester = mock.Mock()

        with (
            mock.patch(
                "src.tasks.trigger.RequiemCombatConfigTask.VirtualGamepadPulseTester",
                return_value=tester,
            ),
            mock.patch(
                "src.tasks.trigger.RequiemCombatConfigTask.time.monotonic",
                side_effect=[10.0, 10.1],
            ),
        ):
            task._poll_gamepad_test()

        tester.pulse_a.assert_called_once_with(task.GAMEPAD_TEST_HOLD_SECONDS)
        self.assertEqual(12.6, task._next_gamepad_pulse_at)

    def test_turning_test_off_releases_controller(self):
        task = self._task()
        tester = mock.Mock()
        task._gamepad_tester = tester
        task.config[task.CONF_GAMEPAD_TEST] = False

        task._poll_gamepad_test()

        tester.close.assert_called_once_with()
        self.assertIsNone(task._gamepad_tester)


if __name__ == "__main__":
    unittest.main()
