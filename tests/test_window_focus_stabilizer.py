import threading
import unittest
from unittest import mock

from src.lw.window_focus import WindowFocusStabilizer
from src.interaction.NTEInteraction import NTEInteraction


class FakeClock:
    def __init__(self):
        self.current = 0.0
        self.sleeps = []

    def __call__(self):
        return self.current

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.current += seconds


class WindowFocusStabilizerTest(unittest.TestCase):
    def test_stable_background_returns_immediately(self):
        clock = FakeClock()
        stabilizer = WindowFocusStabilizer(lambda: False, sleep=clock.sleep, now=clock)
        self.assertTrue(stabilizer.stable())
        self.assertEqual(clock.sleeps, [])

    def test_stable_foreground_returns_immediately(self):
        clock = FakeClock()
        stabilizer = WindowFocusStabilizer(lambda: True, sleep=clock.sleep, now=clock)
        self.assertTrue(stabilizer.stable())
        self.assertEqual(clock.sleeps, [])

    def test_waits_until_state_settles(self):
        clock = FakeClock()
        state = {"visible": False}
        stabilizer = WindowFocusStabilizer(
            lambda: state["visible"], sleep=clock.sleep, now=clock
        )
        self.assertTrue(stabilizer.stable(settle_seconds=0.5))
        state["visible"] = True
        self.assertTrue(stabilizer.stable(settle_seconds=0.5))
        self.assertGreaterEqual(clock.current, 0.5)
        self.assertLess(clock.current, 0.6)
        self.assertGreaterEqual(len(clock.sleeps), 10)

    def test_times_out_when_state_keeps_changing(self):
        clock = FakeClock()
        state = {"tick": 0}

        def flipping():
            state["tick"] += 1
            return state["tick"] % 2 == 0

        stabilizer = WindowFocusStabilizer(flipping, sleep=clock.sleep, now=clock)
        stabilizer.observe(True)
        self.assertFalse(
            stabilizer.stable(settle_seconds=0.5, timeout_seconds=0.3)
        )
        self.assertGreaterEqual(clock.current, 0.3)

    def test_click_is_cancelled_when_focus_never_settles_before_posting(self):
        task = object.__new__(NTEInteraction)
        task._input_lock = threading.RLock()
        task.lw_stabilize_focus = mock.Mock(side_effect=[True, False])
        task.try_activate = mock.Mock()
        task.capture = mock.Mock()
        task.post = mock.Mock()

        self.assertFalse(task.click(x=1, y=1, move=False))
        task.try_activate.assert_called_once_with()
        task.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
