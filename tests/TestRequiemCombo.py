"""安魂曲 combo 执行器的纯逻辑回归测试。"""

import unittest

from src.combat import requiem_combo


class FakeIO:
    def __init__(self, continue_results=None):
        self.continue_results = iter(continue_results or [])
        self.events = []

    def should_continue(self):
        return next(self.continue_results, True)

    def mouse_down(self):
        self.events.append("mouse_down")

    def mouse_up(self):
        self.events.append("mouse_up")

    def space_down(self):
        self.events.append("space_down")

    def space_up(self):
        self.events.append("space_up")

    def sleep_ms(self, ms):
        self.events.append(("sleep", ms))


class TestRequiemComboReport(unittest.TestCase):
    def test_fill_attacks_reports_clicks_and_completion(self):
        io = FakeIO()

        clicks, aborted = requiem_combo._fill_attacks(io, 110, 40, 10)

        self.assertEqual(clicks, 2)
        self.assertFalse(aborted)
        self.assertEqual(io.events.count("mouse_down"), 2)
        self.assertEqual(io.events[-1], ("sleep", 10))

    def test_fill_attacks_reports_abort_before_next_click(self):
        io = FakeIO([True, False])

        clicks, aborted = requiem_combo._fill_attacks(io, 150, 40, 10)

        self.assertEqual(clicks, 1)
        self.assertTrue(aborted)
        self.assertEqual(io.events.count("mouse_down"), 1)

    def test_double_4a_report_contains_all_completed_stages(self):
        io = FakeIO()

        report = requiem_combo.run_scheme_double_4a(
            io, front_ms=100, jump_hold_ms=20, back_ms=50, click=(40, 10)
        )

        self.assertEqual(report["front"][0], 100)
        self.assertEqual(report["front"][2:], (2, False))
        self.assertEqual(report["jump"][0], 20)
        self.assertTrue(report["jump"][2])
        self.assertGreaterEqual(report["jump"][1], 0)
        self.assertEqual(report["back"][0], 50)
        self.assertEqual(report["back"][2:], (1, False))
        self.assertEqual(io.events.count("space_down"), 1)

    def test_double_4a_report_marks_front_abort_without_jump(self):
        io = FakeIO([False])

        report = requiem_combo.run_scheme_double_4a(
            io, front_ms=100, jump_hold_ms=20, back_ms=50, click=(40, 10)
        )

        self.assertEqual(report["front"][2:], (0, True))
        self.assertFalse(report["jump"][2])
        self.assertEqual(report["back"][2:], (0, False))
        self.assertNotIn("space_down", io.events)

    def test_double_4a_report_marks_back_abort_after_jump(self):
        # 前段两次点击、跳前检查均通过，后段第一次检查时中止。
        io = FakeIO([True, True, True, False])

        report = requiem_combo.run_scheme_double_4a(
            io, front_ms=100, jump_hold_ms=20, back_ms=50, click=(40, 10)
        )

        self.assertTrue(report["jump"][2])
        self.assertEqual(report["back"][2:], (0, True))


if __name__ == "__main__":
    unittest.main()
