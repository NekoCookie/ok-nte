import unittest
from unittest import mock

import cv2
import numpy as np
from ok import Box

from src.Labels import Labels
from src.lw.fish_catch_ext import FishCatchingTaskMixin
from src.tasks.FishCatchingTask import FishCatchingTask


class TestFishCatchingVision(unittest.TestCase):
    def test_default_rounds_allow_infinite_mode(self):
        self.assertEqual(FishCatchingTask.DEFAULT_ROUNDS, 0)

    def test_blind_click_position_matches_reference_box_center(self):
        self.assertEqual(FishCatchingTaskMixin.BLIND_CLICK_POSITION, (0.490, 0.404))

    def test_skill_order_is_e_w_q(self):
        task = FishCatchingTaskMixin.__new__(FishCatchingTaskMixin)
        task.read_fish_skill_cooldown = mock.Mock(return_value=0.0)
        task._fish_skill_order_index = 0

        self.assertEqual(task.next_fish_skill(), "e")
        self.assertEqual(task.next_fish_skill(), "w")
        self.assertEqual(task.next_fish_skill(), "q")

    def test_skill_cd_ocr_is_used_before_local_fallback(self):
        task = FishCatchingTaskMixin.__new__(FishCatchingTaskMixin)
        task.box_of_screen = mock.Mock(return_value=Box(0, 0, 500, 500))
        task.ocr = mock.Mock(return_value=[Box(10, 10, 20, 20, name="1.8")])
        task.log_debug = mock.Mock()

        self.assertAlmostEqual(task.read_fish_skill_cooldown("e"), 1.8)

    def test_cast_skill_selects_key_then_clicks_reference_center(self):
        task = FishCatchingTaskMixin.__new__(FishCatchingTaskMixin)
        task.send_key = mock.Mock()
        task.sleep = mock.Mock()
        task.operate_click = mock.Mock(return_value=True)
        task._fish_skill_last_cast = {}

        self.assertTrue(task.cast_fish_skill("e"))
        task.send_key.assert_called_once_with(
            "e", down_time=0.03, action_name="fish_catch_select_e", interval=0.15
        )
        task.operate_click.assert_called_once_with(
            0.490,
            0.404,
            down_time=0.01,
            action_name="fish_catch_target",
        )
        self.assertIn("e", task._fish_skill_last_cast)

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

    def test_result_overlay_is_detected_from_close_prompt_when_template_is_missing(self):
        task = FishCatchingTaskMixin.__new__(FishCatchingTaskMixin)
        task.find_one = mock.Mock(return_value=None)
        task.box_of_screen = mock.Mock(return_value=Box(0, 0, 500, 500))
        task.ocr = mock.Mock(return_value=[Box(120, 240, 160, 36, name="点击 空白区域 关闭")])

        self.assertTrue(task.has_catch_result())

    def test_result_overlay_is_closed_by_clicking_blank_area(self):
        task = FishCatchingTaskMixin.__new__(FishCatchingTaskMixin)
        task.find_one = mock.Mock(return_value="result")
        task.box_of_screen = mock.Mock(return_value=Box(0, 0, 500, 500))
        task.ocr = mock.Mock(return_value=[])
        task.operate_click = mock.Mock()
        task.wait_until = mock.Mock()
        task.log_info = mock.Mock()

        self.assertTrue(task.close_catch_result())
        task.operate_click.assert_called_once_with(
            0.503,
            0.887,
            action_name="close_fish_catch_result_fallback",
            interval=0,
        )
        task.wait_until.assert_called_once()

    def test_result_overlay_clicks_close_prompt_when_ocr_finds_it(self):
        task = FishCatchingTaskMixin.__new__(FishCatchingTaskMixin)
        prompt = Box(120, 240, 160, 36, name="点击空白区域关闭")
        task.find_one = mock.Mock(return_value="result")
        task.box_of_screen = mock.Mock(return_value=Box(0, 0, 500, 500))
        task.ocr = mock.Mock(return_value=[prompt])
        task.operate_click = mock.Mock()
        task.wait_until = mock.Mock()
        task.log_info = mock.Mock()

        self.assertTrue(task.close_catch_result())
        task.operate_click.assert_called_once_with(
            prompt,
            action_name="close_fish_catch_result",
            interval=0,
        )

    def test_result_overlay_retries_when_first_close_does_not_clear_overlay(self):
        task = FishCatchingTaskMixin.__new__(FishCatchingTaskMixin)
        task.find_one = mock.Mock(return_value="result")
        task.find_catch_result_close_prompt = mock.Mock(return_value=None)
        task.operate_click = mock.Mock()
        task.wait_until = mock.Mock(side_effect=[False, True])
        task.sleep = mock.Mock()
        task.log_info = mock.Mock()

        self.assertTrue(task.close_catch_result())
        self.assertEqual(task.operate_click.call_count, 2)
        self.assertEqual(task.wait_until.call_count, 2)


if __name__ == "__main__":
    unittest.main()
