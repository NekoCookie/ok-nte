"""[lw] Deterministic activity vision, input ownership and card safety regressions."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from src.lw.activity import (
    ENABLE, FOOT_X, FOOT_Y, GROUP, HOTKEY, PRIORITY,
    ActivityController, configure_activity, danger_mask, escape_keys, select_card,
)


class TestActivity(unittest.TestCase):
    def make_controller(self):
        task = MagicMock()
        task.CONF_INPUT_MODE, task.INPUT_BG = "input", "background"
        task.config = {ENABLE: True, HOTKEY: "5", "input": "background"}
        task.enabled = True
        task._manual_key_triggers_enabled.return_value = True
        task._get_vk_code.side_effect = lambda key: {
            "5": 53, "mouse4": 5, "mouse5": 6, "w": 87, "a": 65, "s": 83, "d": 68,
        }.get(key)
        task._is_key_pressed.return_value = False
        task.executor.paused = False
        task.executor.current_task = None
        task.executor.exit_event.is_set.return_value = False
        task.is_foreground.return_value = False
        task.executor.method.get_frame.return_value = np.zeros((1080, 1920, 3), np.uint8)
        controller = ActivityController(task)
        return controller, task

    def test_group_defaults_off_and_exposes_key(self):
        task = SimpleNamespace(default_config={}, config_type={}, config_description={})
        configure_activity(task)
        self.assertFalse(task.default_config[ENABLE])
        self.assertEqual(task.default_config[HOTKEY], "5")
        self.assertEqual(task.default_config[PRIORITY], "")
        self.assertEqual(task.config_type[GROUP]["sub_configs"][True],
                         [ENABLE, HOTKEY, PRIORITY, FOOT_X, FOOT_Y])

    def test_card_order_and_no_random_fallback(self):
        self.assertEqual(select_card(["卡牌甲", "卡牌 乙", "卡牌丙"], "卡牌乙,卡牌甲"), 1)
        self.assertIsNone(select_card(["未识别", "", ""], "卡牌甲"))
        self.assertIsNone(select_card(["卡牌甲"] * 3, ""))

    def test_outer_ring_filled_health_bar_ignored_at_multiple_resolutions(self):
        source = np.zeros((540, 960, 3), np.uint8)
        cv2.circle(source, (490, 300), 70, (80, 80, 240), 4)
        cv2.rectangle(source, (300, 170), (390, 174), (0, 0, 255), -1)
        for width, height in ((1920, 1080), (2560, 1440), (3840, 2160)):
            mask = danger_mask(cv2.resize(source, (width, height)))
            self.assertTrue(mask[300, 490])
            self.assertTrue(mask[300, 555])
            self.assertFalse(mask[172, 350])
            self.assertTrue(escape_keys(mask, (490, 300)))

    def test_overlapping_strip_and_circle_escape_union(self):
        mask = np.zeros((540, 960), np.uint8)
        cv2.circle(mask, (480, 270), 65, 255, -1)
        cv2.rectangle(mask, (150, 280), (780, 330), 255, -1)
        self.assertEqual(escape_keys(mask, (480, 315)), ("s",))
        self.assertEqual(escape_keys(mask, (480, 380)), ())
        self.assertEqual(escape_keys(np.ones_like(mask) * 255, (480, 300)), ())

    def test_toggle_requires_release_and_supports_mouse_keys_in_background(self):
        for key in ("5", "mouse4", "mouse5"):
            controller, task = self.make_controller()
            task.config[HOTKEY] = key
            task._is_key_pressed.return_value = True
            controller.poll()
            self.assertFalse(controller.running)
            task._is_key_pressed.return_value = False
            controller.poll()
            task._is_key_pressed.return_value = True
            controller.poll()
            self.assertTrue(controller.running)
            controller.next_tick = float("inf")
            task._is_key_pressed.return_value = False
            controller.poll()
            task._is_key_pressed.return_value = True
            controller.poll()
            self.assertFalse(controller.running)

    def test_activity_starts_with_manual_master_disabled_in_background(self):
        controller, task = self.make_controller()
        task._manual_key_triggers_enabled.return_value = False
        controller.poll()
        task._is_key_pressed.return_value = True
        self.assertTrue(controller.poll())
        self.assertTrue(controller.running)
        task._manual_key_triggers_enabled.assert_not_called()

    def test_activity_switch_stops_activity_in_background(self):
        controller, task = self.make_controller()
        controller.running = True
        task.config[ENABLE] = False
        self.assertFalse(controller.poll())
        self.assertFalse(controller.running)
        task.executor.method.get_frame.assert_not_called()

    def test_hardware_mode_requires_focus_and_other_task_blocks_input(self):
        controller, task = self.make_controller()
        self.assertTrue(controller.available())
        task.config["input"] = "hardware"
        self.assertFalse(controller.available())
        task.is_foreground.return_value = True
        self.assertTrue(controller.available())
        task.executor.current_task = object()
        self.assertFalse(controller.available())

    def test_background_pulse_releases_keys_on_error(self):
        controller, task = self.make_controller()
        task.executor.interaction.send_key_down.side_effect = [None, RuntimeError("failure")]
        with self.assertRaises(RuntimeError):
            controller.pulse(("w", "a"))
        self.assertEqual(task.executor.interaction.send_key_up.call_count, 2)

    def test_busy_trigger_does_not_disarm_and_resumes_when_idle(self):
        controller, task = self.make_controller()
        controller.poll()
        task.executor.current_task = object()
        task._is_key_pressed.return_value = True
        controller.poll()
        self.assertTrue(controller.running)
        task._is_key_pressed.return_value = False
        controller.poll()
        self.assertTrue(controller.running)
        task.executor.method.get_frame.assert_not_called()
        task.executor.current_task = None
        with patch.object(controller, "tick") as tick:
            controller.poll()
            tick.assert_called_once_with()
        self.assertTrue(controller.running)

    def test_hotkey_stops_even_while_other_task_occupies_executor(self):
        controller, task = self.make_controller()
        controller.poll()
        controller.running = True
        task.executor.current_task = object()
        task._is_key_pressed.return_value = True
        controller.poll()
        self.assertFalse(controller.running)
        self.assertTrue(task.log_info.call_args.kwargs["notify"])

    def test_start_and_stop_emit_notifications_and_persistent_status(self):
        controller, task = self.make_controller()
        controller.poll()
        task.log_info.reset_mock()
        task._is_key_pressed.return_value = True
        controller.poll()
        self.assertTrue(controller.running)
        self.assertTrue(task.log_info.call_args.kwargs["notify"])
        self.assertTrue(controller.status)
        task.info_set.assert_called()
        controller.stop()
        self.assertFalse(controller.running)
        self.assertTrue(task.log_info.call_args.kwargs["notify"])

    def test_wait_status_is_not_logged_on_every_poll(self):
        controller, task = self.make_controller()
        with patch("src.lw.activity.time.monotonic", return_value=100):
            for _ in range(20):
                controller.report("waiting")
        self.assertEqual(task.log_info.call_count, 1)

    def test_unknown_scene_updates_diagnostic_status_without_moving(self):
        controller, task = self.make_controller()
        with patch.object(controller, "text", return_value=""):
            controller.tick()
        self.assertTrue(controller.status)
        task.info_set.assert_called()
        task.executor.interaction.send_key_down.assert_not_called()

    def test_background_pulse_interrupts_when_activity_is_disabled(self):
        controller, task = self.make_controller()
        task.executor.interaction.send_key_down.side_effect = (
            lambda key: task.config.update({ENABLE: False})
        )
        controller.pulse(("w", "a"))
        task.executor.interaction.send_key_down.assert_called_once_with("w")
        task.executor.interaction.send_key_up.assert_called_once_with("w")

    def test_cards_require_two_reads_and_click_only_once(self):
        controller, task = self.make_controller()
        task.config[PRIORITY] = "卡牌乙,卡牌甲"
        with patch.object(controller, "text", side_effect=(
            ["选取卡牌", "卡牌甲", "卡牌乙", "卡牌丙"] * 2 + ["选取卡牌"]
        )):
            controller.tick()
            task.executor.interaction.click.assert_not_called()
            controller.tick()
            controller.tick()
        task.executor.interaction.click.assert_called_once_with(x=970, y=432)
        task.executor.interaction.send_key_down.assert_not_called()

    def test_unknown_scene_and_missing_frame_never_move(self):
        controller, task = self.make_controller()
        with patch.object(controller, "text", return_value=""):
            controller.tick()
        task.executor.interaction.send_key_down.assert_not_called()
        controller.running = True
        task.executor.method.get_frame.return_value = None
        controller.tick()
        self.assertFalse(controller.running)


if __name__ == "__main__":
    unittest.main()
