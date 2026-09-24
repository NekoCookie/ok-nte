import unittest

import numpy as np

from src.lw.boss_break_bar import BREAK_BAR_BOX, break_bar_ratio

FILL = (223, 223, 223)
TRACK = (50, 41, 25)


def make_frame(ratio, width=2000, height=1125):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = (150, 90, 40)
    x1, y1, x2, y2 = BREAK_BAR_BOX
    left, right = round(width * x1), round(width * x2)
    top, bottom = round(height * y1) - 1, round(height * y2) + 2
    frame[top:bottom, left:right] = TRACK
    fill_end = left + round((right - left) * ratio)
    frame[top:bottom, left:fill_end] = FILL
    return frame, left, right, top, bottom


class TestBossBreakBar(unittest.TestCase):
    def test_reads_partial_fill_across_resolutions(self):
        for width, height in ((2000, 1125), (2560, 1440), (1280, 720)):
            frame, *_ = make_frame(0.86, width, height)
            self.assertAlmostEqual(break_bar_ratio(frame), 0.86, delta=0.01)

    def test_near_empty_bar_reads_zero(self):
        frame, *_ = make_frame(0.0)
        self.assertEqual(break_bar_ratio(frame), 0.0)

    def test_effect_gap_inside_fill_is_ignored(self):
        frame, left, _right, top, bottom = make_frame(0.86)
        frame[top:bottom, left + 100 : left + 160] = (80, 40, 200)
        self.assertAlmostEqual(break_bar_ratio(frame), 0.86, delta=0.01)

    def test_bright_spark_on_empty_track_is_ignored(self):
        frame, _left, right, top, bottom = make_frame(0.5)
        frame[top:bottom, right - 20 : right - 17] = (240, 240, 240)
        self.assertAlmostEqual(break_bar_ratio(frame), 0.5, delta=0.01)

    def test_unusable_frame_returns_none(self):
        self.assertIsNone(break_bar_ratio(None))
        self.assertIsNone(break_bar_ratio(np.zeros((10, 10), dtype=np.uint8)))


if __name__ == "__main__":
    unittest.main()
