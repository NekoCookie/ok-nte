import unittest
from unittest import mock

import cv2
import numpy as np

from src.Labels import Labels
from src.lw.fish_catch_ext import FishCatchingTaskMixin
from src.tasks.FishCatchingTask import FishCatchingTask


class TestFishCatchingVision(unittest.TestCase):
    def test_default_rounds_allow_infinite_mode(self):
        self.assertEqual(FishCatchingTask.DEFAULT_ROUNDS, 0)
        self.assertEqual(FishCatchingTaskMixin.FISH_CLICK_INTERVAL, 0.5)

    def test_blind_click_pattern_covers_center_region(self):
        task = FishCatchingTaskMixin.__new__(FishCatchingTaskMixin)
        task._blind_click_index = 0

        points = [task.next_blind_click_position() for _ in task.BLIND_CLICK_POINTS]

        self.assertEqual(len(points), len(set(points)))
        self.assertTrue(all(0.35 <= x <= 0.43 and 0.27 <= y <= 0.38 for x, y in points))
        self.assertEqual(task.next_blind_click_position(), points[0])

    def test_click_interval_is_configurable_with_conservative_minimum(self):
        task = FishCatchingTaskMixin.__new__(FishCatchingTaskMixin)
        task.CONF_CLICK_INTERVAL = "捕鱼点击间隔"
        task.config = {task.CONF_CLICK_INTERVAL: 0.8}
        self.assertEqual(task.fish_click_interval(), 0.8)

        task.config[task.CONF_CLICK_INTERVAL] = 0
        self.assertEqual(task.fish_click_interval(), 0.05)

    def test_detects_separate_neon_fish_shapes(self):
        image = np.zeros((240, 400, 3), dtype=np.uint8)
        image[:] = (170, 130, 80)
        cv2.ellipse(image, (110, 90), (42, 14), 15, 0, 360, (255, 255, 255), 4)
        cv2.ellipse(image, (290, 160), (28, 10), -20, 0, 360, (90, 255, 170), 4)

        targets = FishCatchingTaskMixin.detect_fish_components(image)

        self.assertGreaterEqual(len(targets), 2)
        centers = {(x + width // 2, y + height // 2) for x, y, width, height in targets}
        self.assertTrue(any(abs(x - 110) < 20 and abs(y - 90) < 20 for x, y in centers))
        self.assertTrue(any(abs(x - 290) < 20 and abs(y - 160) < 20 for x, y in centers))

    def test_result_overlay_is_detected_with_fishing_success_label(self):
        task = FishCatchingTaskMixin.__new__(FishCatchingTaskMixin)
        task.find_one = mock.Mock(return_value="result")

        self.assertTrue(task.has_catch_result())
        task.find_one.assert_called_once_with(Labels.fish_sucess)

    def test_result_overlay_is_closed_by_clicking_blank_area(self):
        task = FishCatchingTaskMixin.__new__(FishCatchingTaskMixin)
        task.find_one = mock.Mock(return_value="result")
        task.operate_click = mock.Mock()
        task.wait_until = mock.Mock()
        task.log_info = mock.Mock()

        self.assertTrue(task.close_catch_result())
        task.operate_click.assert_called_once_with(
            0.50,
            0.90,
            action_name="close_fish_catch_result",
            interval=1,
        )
        task.wait_until.assert_called_once()


if __name__ == "__main__":
    unittest.main()
