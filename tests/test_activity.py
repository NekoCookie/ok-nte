"""[lw] Deterministic activity vision, input ownership and card safety regressions."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from src.lw.activity import (
    ENABLE, FOOT_X, FOOT_Y, GROUP, HOTKEY, MOVE_SECONDS, PRIORITY,
    ActivityController, configure_activity, danger_mask, escape_keys, select_card,
)


class TestActivity(unittest.TestCase):
    @staticmethod
    def replacement_boxes(levels=(9, 10, 4, 9, 1, 1)):
        boxes = [SimpleNamespace(name="选择要替换的技能", y=220),
                 SimpleNamespace(name="确认", x=550, y=395, width=40, height=20)]
        for index, level in enumerate(levels):
            if level is not None:
                boxes.append(SimpleNamespace(name=f"Lv. {level}",
                                             x=(.316 + index / 12) * 960 - 15,
                                             y=320, width=30, height=18))
        return boxes

    def test_replacement_selects_rightmost_lowest_then_confirms_and_retries(self):
        controller, task = self.make_controller()
        controller.running = True
        task.config[PRIORITY] = "确认"  # Generic OCR must not skip icon selection.
        task.ocr.return_value = self.replacement_boxes()
        frame = np.zeros((540, 960, 3), np.uint8)
        with patch("src.lw.activity.time.monotonic", return_value=100) as clock:
            controller.click_configured_text(frame)
            click = task.executor.interaction.click
            self.assertEqual(click.call_args.kwargs,
                             dict(x=703, y=297, move_back=True))
            clock.return_value = 100.5
            controller.click_configured_text(frame)
            self.assertEqual(click.call_args.kwargs,
                             dict(x=570, y=405, move_back=True))
            clock.return_value = 102.4
            controller.click_configured_text(frame)
            self.assertEqual(click.call_count, 2)
            clock.return_value = 102.9
            controller.click_configured_text(frame)
            self.assertEqual(click.call_count, 3)
            self.assertEqual(click.call_args.kwargs["x"], 703)

    def test_replacement_uses_unique_lowest_and_waits_for_all_levels(self):
        for levels, expected in (((9, 10, 1, 9, 4, 4), 463),
                                 ((9, 10, None, 9, 1, 1), None)):
            controller, task = self.make_controller()
            controller.running = True
            task.ocr.return_value = self.replacement_boxes(levels)
            controller.click_configured_text(np.zeros((540, 960, 3), np.uint8))
            if expected is None:
                task.executor.interaction.click.assert_not_called()
            else:
                self.assertEqual(task.executor.interaction.click.call_args.kwargs["x"], expected)

    def test_replacement_failed_selection_never_confirms_and_stop_clears_pending(self):
        controller, task = self.make_controller()
        controller.running = True
        task.ocr.return_value = self.replacement_boxes()
        task.executor.interaction.click.return_value = False
        frame = np.zeros((540, 960, 3), np.uint8)
        with patch("src.lw.activity.time.monotonic", return_value=100) as clock:
            controller.click_configured_text(frame)
            clock.return_value = 100.5
            controller.click_configured_text(frame)
        task.executor.interaction.click.assert_called_once()
        self.assertIsNone(controller.replacement_pending)
        controller.replacement_pending = ((1,) * 6, 5)
        controller.stop()
        self.assertIsNone(controller.replacement_pending)

    def test_replacement_popup_disappearance_cancels_confirmation(self):
        controller, task = self.make_controller()
        controller.running = True
        frame = np.zeros((540, 960, 3), np.uint8)
        with patch("src.lw.activity.time.monotonic", return_value=100) as clock:
            task.ocr.return_value = self.replacement_boxes()
            controller.click_configured_text(frame)
            clock.return_value = 100.5
            task.ocr.return_value = []
            controller.click_configured_text(frame)
        self.assertIsNone(controller.replacement_pending)
        task.executor.interaction.click.assert_called_once()

    def test_medium_boss_ring_clipped_at_bottom_triggers_directional_dodge(self):
        from src.lw.activity import oversized_boss_ellipse

        frame = np.zeros((540, 960, 3), np.uint8)
        cv2.ellipse(frame, (465, 350), (230, 196), 0, 0, 360, (25, 25, 150), 9)
        ellipse = oversized_boss_ellipse(frame)
        self.assertIsNotNone(ellipse)
        controller, task = self.make_controller()
        controller.running = True
        task.executor.method.get_frame.return_value = frame
        with (patch.object(controller, "text", return_value="伤害跳字"),
              patch.object(controller, "pulse") as pulse):
            controller.tick()
        self.assertTrue(pulse.call_args.kwargs["sprint"])

    def test_oversized_clipped_ring_survives_banner_occlusion(self):
        from src.lw.activity import oversized_boss_ellipse, boss_warning_mask

        frame = np.zeros((540, 960, 3), np.uint8)
        cv2.ellipse(frame, (480, 330), (490, 343), 0, 0, 360, (25, 25, 120), 8)
        cv2.rectangle(frame, (0, 100), (959, 185), (20, 20, 120), -1)
        ellipse = oversized_boss_ellipse(frame)
        self.assertIsNotNone(ellipse)
        self.assertTrue(boss_warning_mask(frame, ellipse)[305, 480])

    def test_banner_and_small_rings_are_not_oversized_warning(self):
        from src.lw.activity import oversized_boss_ellipse

        frame = np.zeros((540, 960, 3), np.uint8)
        cv2.rectangle(frame, (0, 100), (959, 185), (20, 20, 120), -1)
        for center in ((480, 300), (600, 350), (380, 260)):
            cv2.circle(frame, center, 75, (50, 50, 240), 6)
        self.assertIsNone(oversized_boss_ellipse(frame))

    def test_offscreen_exit_still_moves_and_dodges_with_direction_held(self):
        controller, task = self.make_controller()
        controller.running = True
        ellipse = ((480., 350.), (1000., 700.), 0.)
        with (patch.object(controller, "text", return_value="伤害跳字"),
              patch("src.lw.activity.oversized_boss_ellipse", return_value=ellipse),
              patch.object(controller, "pulse") as pulse):
            controller.tick()
        self.assertEqual(pulse.call_args.args[0], ("w",))
        self.assertTrue(pulse.call_args.kwargs["sprint"])

    def test_offscreen_fallback_stops_outside_predicted_ring(self):
        from src.lw.activity import oversized_escape_keys

        ellipse = ((480., 350.), (1000., 700.), 0.)
        self.assertEqual(oversized_escape_keys(ellipse, (480, 305)), ("w",))
        self.assertEqual(oversized_escape_keys(ellipse, (480, 710)), ())

    def test_card_attribute_click_targets_upper_card_at_supported_resolutions(self):
        for width, height in ((1920, 1080), (2560, 1440), (3840, 2160)):
            for center in (.275, .505, .73):
                for scaled in (False, True):
                    with self.subTest(width=width, center=center, scaled=scaled):
                        controller, task = self.make_controller()
                        controller.running = True
                        task.config[PRIORITY] = "定时回复生命"
                        title = SimpleNamespace(name="选取卡牌", y=.16 * height)
                        scale = 2 if scaled else 1
                        attr = SimpleNamespace(name="定时回复生命",
                                               x=(center - .04) * width * scale,
                                               y=.63 * height * scale,
                                               width=.08 * width * scale,
                                               height=.02 * height * scale)
                        task.ocr.side_effect = [[title], [attr]] if scaled else [[title, attr]]
                        controller.click_configured_text(np.zeros((height, width, 3), np.uint8))
                        click = task.executor.interaction.click.call_args.kwargs
                        self.assertLess(abs(click["x"] / width - center), .005)
                        self.assertEqual(click["y"], round(.4 * height))
                        self.assertTrue(click["move_back"])

    def test_card_page_controls_keep_actual_text_coordinates(self):
        controller, task = self.make_controller()
        controller.running = True
        task.config[PRIORITY] = "刷新"
        task.ocr.return_value = [SimpleNamespace(name="选取卡牌", y=80),
                                SimpleNamespace(name="刷新", x=840, y=470,
                                                width=60, height=30)]
        controller.click_configured_text(np.zeros((540, 960, 3), np.uint8))
        task.executor.interaction.click.assert_called_once_with(x=870, y=485, move_back=True)

    def test_pause_and_resume_are_visible_without_overriding_global_pause(self):
        controller, task = self.make_controller()
        controller.poll()
        task.executor.paused = True
        task._is_key_pressed.return_value = True
        controller.poll()
        self.assertTrue(controller.running)
        self.assertTrue(controller.observed_pause)
        task.executor.start.assert_not_called()
        task._is_key_pressed.return_value = False
        controller.poll()
        task.executor.paused = False
        controller.poll()
        self.assertFalse(controller.observed_pause)
        self.assertTrue(task.log_info.call_args.kwargs["notify"])

    def test_pause_event_logs_source_without_mutating_executor(self):
        from ok.gui.Communicate import communicate

        controller, task = self.make_controller()
        controller.install_pause_diagnostics()
        try:
            communicate.executor_paused.emit(True)
            task.log_info.assert_called_once()
            task.executor.start.assert_not_called()
        finally:
            communicate.executor_paused.disconnect(controller._pause_observer)

    def test_capture_exception_keeps_activity_armed_for_retry(self):
        from ok.task.exceptions import CaptureException

        controller, task = self.make_controller()
        controller.running = True
        with patch.object(controller, "tick", side_effect=CaptureException("test")):
            controller.process()
        self.assertTrue(controller.running)
        task.executor.interaction.click.assert_not_called()

    def test_unmatched_cards_random_after_ten_seconds_and_restore_mouse(self):
        controller, task = self.make_controller()
        controller.running = True
        task.ocr.return_value = [SimpleNamespace(name="选取卡牌", y=80)]
        frame = np.zeros((540, 960, 3), np.uint8)
        with (patch("src.lw.activity.time.monotonic", return_value=100) as clock,
              patch("src.lw.activity.random.choice", return_value=.505)):
            controller.click_configured_text(frame)
            clock.return_value = 109
            controller.click_configured_text(frame)
            task.executor.interaction.click.assert_not_called()
            clock.return_value = 110
            self.assertTrue(controller.click_configured_text(frame))
        task.executor.interaction.click.assert_called_once_with(x=485, y=216, move_back=True)

    def test_unknown_menu_never_random_clicks_and_resets_card_wait(self):
        controller, task = self.make_controller()
        controller.running = True
        frame = np.zeros((540, 960, 3), np.uint8)
        with patch("src.lw.activity.time.monotonic", return_value=100) as clock:
            task.ocr.return_value = [SimpleNamespace(name="选取卡牌", y=80)]
            controller.click_configured_text(frame)
            clock.return_value = 105
            task.ocr.return_value = []
            controller.click_configured_text(frame)
            clock.return_value = 120
            controller.click_configured_text(frame)
        task.executor.interaction.click.assert_not_called()
        self.assertIsNone(controller.unmatched_cards_since)

    def test_damage_numbers_label_alone_identifies_both_battle_modes(self):
        for label in ("伤害跳字: 开", "伤害跳字: 关"):
            controller, task = self.make_controller()
            controller.running = True
            with (patch.object(controller, "text", return_value=label),
                  patch.object(controller, "click_configured_text") as click):
                controller.tick()
            click.assert_not_called()
            self.assertGreater(controller.last_scene_seen, 0)

    def test_endless_battle_never_clicks_text_even_when_safe(self):
        controller, task = self.make_controller()
        controller.running = True
        task.config[PRIORITY] = "无尽挑战"
        with (patch.object(controller, "text", side_effect=["伤害跳字: 开 无尽挑战", "00:52"]),
              patch.object(controller, "click_configured_text") as click):
            controller.tick()
        click.assert_not_called()
        task.executor.interaction.click.assert_not_called()

    def test_endless_battle_can_move_without_clicking_mode_label(self):
        controller, task = self.make_controller()
        controller.running = True
        mask = np.zeros((540, 960), np.uint8)
        cv2.circle(mask, (480, 305), 60, 255, -1)
        with (patch.object(controller, "text", side_effect=["无尽挑战", "00:52"]),
              patch("src.lw.activity.danger_mask", return_value=mask),
              patch.object(controller, "click_configured_text") as click,
              patch.object(controller, "pulse") as pulse):
            controller.tick()
        pulse.assert_called_once()
        click.assert_not_called()

    def test_endless_hud_timer_miss_does_not_turn_into_menu_click(self):
        controller, task = self.make_controller()
        controller.running = True
        with (patch.object(controller, "text", side_effect=["无尽挑战", ""]),
              patch.object(controller, "click_configured_text") as click):
            controller.tick()
        click.assert_not_called()

    def test_danger_preempts_persistent_text_and_click_cooldown(self):
        controller, task = self.make_controller()
        controller.running = True
        task.config[PRIORITY] = "常驻文字"
        controller.next_text_click = float("inf")
        mask = np.zeros((540, 960), np.uint8)
        cv2.circle(mask, (480, 305), 70, 255, -1)
        with (patch.object(controller, "text", return_value="轨外回响"),
              patch.object(controller, "click_configured_text") as click,
              patch("src.lw.activity.danger_mask", return_value=mask),
              patch.object(controller, "pulse") as pulse):
            controller.tick()
            controller.tick()
        self.assertEqual(pulse.call_count, 2)
        click.assert_not_called()

    def test_click_cooldown_returns_no_action(self):
        controller, task = self.make_controller()
        controller.running = True
        task.config[PRIORITY] = "开始挑战"
        controller.next_text_click = float("inf")
        task.ocr.return_value = [SimpleNamespace(name="开始挑战", x=20, y=20,
                                                width=100, height=30)]
        self.assertFalse(controller.click_configured_text(np.zeros((540, 960, 3), np.uint8)))
        task.executor.interaction.click.assert_not_called()

    def test_any_page_clicks_configured_text_at_detected_coordinates(self):
        controller, task = self.make_controller()
        controller.running = True
        task.config[PRIORITY] = "无尽挑战/开始挑战"
        task.ocr.return_value = [SimpleNamespace(name="开始挑战", x=100, y=200,
                                                width=120, height=40)]
        controller.tick()
        task.executor.interaction.click.assert_called_once_with(x=160, y=220, move_back=True)
        task.executor.interaction.send_key_down.assert_not_called()

    def test_text_priority_and_bounded_repeat_without_scene_change(self):
        controller, task = self.make_controller()
        controller.running = True
        task.config[PRIORITY] = "乙/甲甲/乙乙"
        task.ocr.return_value = [SimpleNamespace(name=name, x=x, y=20, width=20, height=20)
                                for name, x in (("乙乙", 20), ("甲甲", 100))]
        with patch("src.lw.activity.time.monotonic", return_value=100) as clock:
            controller.tick()
            clock.return_value = 101
            controller.tick()
            self.assertEqual(task.executor.interaction.click.call_count, 1)
            clock.return_value = 103
            controller.tick()
        self.assertEqual(task.executor.interaction.click.call_count, 2)
        self.assertEqual(task.executor.interaction.click.call_args.kwargs,
                         {"x": 110, "y": 30, "move_back": True})
    def test_boss_ring_is_distinct_from_small_rings_and_rectangle(self):
        from src.lw.activity import boss_warning_mask

        for radius in (60, 85, 170):
            frame = np.zeros((540, 960, 3), np.uint8)
            cv2.circle(frame, (480, 265), radius, (70, 70, 240), 5)
            mask = boss_warning_mask(frame)
            self.assertEqual(bool(mask[265, 480]), radius == 170)
        frame = np.zeros((540, 960, 3), np.uint8)
        cv2.rectangle(frame, (280, 110), (680, 420), (0, 0, 255), 4)
        self.assertFalse(boss_warning_mask(frame).any())

    def test_dodge_counts_directions_without_converting_to_seconds(self):
        controller, task = self.make_controller()
        controller.running = True
        now = [0.0]
        with (patch("src.lw.activity.time.monotonic", side_effect=lambda: now[0]),
              patch("src.lw.activity.time.sleep", side_effect=lambda delay: now.__setitem__(0, now[0] + delay))):
            controller.pulse(("w", "d"), sprint=True)
        self.assertEqual(controller.dodge_count, 1)
        self.assertEqual(controller.direction_dodges, {"w": 1, "a": 0, "s": 0, "d": 1})
        self.assertAlmostEqual(controller.drift[0], controller.direction_seconds["d"] / 2**.5)
        with (patch("src.lw.activity.time.monotonic", side_effect=lambda: now[0]),
              patch("src.lw.activity.time.sleep", side_effect=lambda delay: now.__setitem__(0, now[0] + delay))):
            controller.pulse(("a",), sprint=False)
        self.assertEqual(controller.direction_dodges["a"], 0)

    def test_time_and_dodge_balance_both_influence_near_exits(self):
        mask = np.zeros((540, 960), np.uint8)
        cv2.circle(mask, (480, 300), 60, 255, -1)
        self.assertEqual(escape_keys(mask, (480, 300), dodge_drift=(4, 0)), ("a",))
        # Large seconds cannot drown out the independent dodge-count objective.
        keys = escape_keys(mask, (480, 300), drift=(1000, 0), dodge_drift=(0, 4))
        self.assertIn("a", keys)
        self.assertIn("w", keys)
        cv2.rectangle(mask, (450, 250), (700, 350), 255, -1)
        self.assertNotEqual(escape_keys(mask, (480, 300), dodge_drift=(-100, 0)), ("d",))


    def test_persistent_danger_does_not_stop_activity_after_four_seconds(self):
        controller, task = self.make_controller()
        controller.running = True
        mask = np.zeros((540, 960), np.uint8)
        cv2.circle(mask, (480, 305), 70, 255, -1)
        with (patch.object(controller, "text", return_value="轨外回响"),
              patch("src.lw.activity.danger_mask", return_value=mask),
              patch("src.lw.activity.time.monotonic", return_value=100) as clock,
              patch.object(controller, "pulse") as pulse):
            for now in (100, 105, 130, 400):
                clock.return_value = now
                controller.tick()
                self.assertTrue(controller.running)
            self.assertEqual(pulse.call_count, 4)
        controller.stop()
        self.assertFalse(controller.running)

    def test_slash_priorities_preserve_user_order(self):
        texts = ["生命值", "传说能力", "移速"]
        self.assertEqual(select_card(texts, "传说能力/生命值/移速"), 1)
        self.assertEqual(select_card(texts, "移速/传说能力"), 2)

    def test_drift_bias_returns_toward_origin_only_for_near_exits(self):
        mask = np.zeros((540, 960), np.uint8)
        cv2.circle(mask, (480, 300), 60, 255, -1)
        self.assertEqual(escape_keys(mask, (480, 300), drift=(3, 0)), ("a",))

    def test_sprint_releases_right_mouse_even_when_wait_fails(self):
        import win32con

        controller, task = self.make_controller()
        controller.running = True
        now = [0.0]
        task.executor.interaction.post.side_effect = [RuntimeError("test"), None]
        with (patch("src.lw.activity.time.monotonic", side_effect=lambda: now[0]),
              patch("src.lw.activity.time.sleep", side_effect=lambda delay: now.__setitem__(0, now[0] + delay))):
            with self.assertRaises(RuntimeError):
                controller.pulse(("a",), sprint=True)
        self.assertEqual(task.executor.interaction.post.call_args_list[-1].args[0],
                         win32con.WM_RBUTTONUP)
        task.executor.interaction.send_key_up.assert_called_once_with("a")

    def test_sprint_holds_direction_before_during_and_after_right_button(self):
        import win32con

        controller, task = self.make_controller()
        controller.running = True
        now, events = [0.0], []
        interaction = task.executor.interaction
        interaction.update_mouse_pos.side_effect = lambda *args: events.append(("prepare", now[0]))
        interaction.send_key_down.side_effect = lambda key: events.append(("down", now[0]))
        interaction.send_key_up.side_effect = lambda key: events.append(("up", now[0]))
        interaction.post.side_effect = lambda msg, *args: events.append((msg, now[0]))
        with (patch("src.lw.activity.time.monotonic", side_effect=lambda: now[0]),
              patch("src.lw.activity.time.sleep", side_effect=lambda delay: now.__setitem__(0, now[0] + delay))):
            controller.pulse(("a",), sprint=True)
        self.assertEqual([event[0] for event in events],
                         ["prepare", "down", win32con.WM_RBUTTONDOWN,
                          win32con.WM_RBUTTONUP, "up"])
        self.assertGreaterEqual(events[2][1] - events[1][1], 0.06)
        self.assertGreaterEqual(events[4][1] - events[3][1], 0.029)





    def test_move_duration_is_configurable_and_bounded(self):
        from src.lw.activity import movement_seconds

        for value, expected in ((0.5, 0.5), (5, 1), (-1, 0.05),
                                ("bad", 0.2), (float("nan"), 0.2)):
            self.assertEqual(movement_seconds({MOVE_SECONDS: value}), expected)

    def test_pulse_uses_configured_duration(self):
        controller, task = self.make_controller()
        controller.running = True
        task.config[MOVE_SECONDS] = 0.5
        now = [0.0]
        with (patch("src.lw.activity.time.monotonic", side_effect=lambda: now[0]),
              patch("src.lw.activity.time.sleep", side_effect=lambda delay: now.__setitem__(0, now[0] + delay))):
            controller.pulse(("a",))
        self.assertAlmostEqual(now[0], 0.5, places=2)
        task.executor.interaction.send_key_up.assert_called_once_with("a")

    def test_vertical_strip_exits_sideways_not_along_length(self):
        mask = np.zeros((540, 960), np.uint8)
        cv2.rectangle(mask, (450, 130), (510, 400), 255, -1)
        self.assertIn(escape_keys(mask, (480, 280), ("s",)), (("a",), ("d",)))

    def test_keyboard_minus_and_numpad_minus(self):
        from src.lw.activity import activity_key_pressed

        for key in (189, 109):
            with patch("win32api.GetAsyncKeyState",
                       side_effect=lambda vk: 0x8000 if vk == key else 0):
                self.assertTrue(activity_key_pressed(MagicMock(), "-"))

    def test_hotkey_poll_never_captures_or_moves(self):
        controller, task = self.make_controller()
        controller.armed_key = "5"
        controller.running = True
        with patch.object(controller, "tick") as tick:
            controller.poll()
            tick.assert_not_called()
        task.executor.method.get_frame.assert_not_called()

    def test_consecutive_danger_frames_keep_requesting_escape(self):
        controller, task = self.make_controller()
        controller.running = True
        mask = np.zeros((540, 960), np.uint8)
        cv2.circle(mask, (480, 305), 70, 255, -1)
        with (patch.object(controller, "text", return_value="轨外回响"),
              patch("src.lw.activity.danger_mask", return_value=mask),
              patch.object(controller, "pulse") as pulse):
            for _ in range(3):
                controller.tick()
            self.assertEqual(pulse.call_count, 3)

    def test_one_hud_miss_does_not_cancel_escape_but_expiry_does(self):
        controller, task = self.make_controller()
        controller.running = True
        mask = np.zeros((540, 960), np.uint8)
        cv2.circle(mask, (480, 305), 70, 255, -1)
        with (patch.object(controller, "text", side_effect=["轨外回响", "", ""]),
              patch("src.lw.activity.time.monotonic", return_value=100) as clock,
              patch("src.lw.activity.danger_mask", return_value=mask),
              patch.object(controller, "pulse") as pulse):
            controller.tick()
            clock.return_value = 100.3
            controller.tick()
            self.assertEqual(pulse.call_count, 2)
            clock.return_value = 101
            controller.tick()
            self.assertEqual(pulse.call_count, 2)

    def make_controller(self):
        task = MagicMock()
        task.config = {ENABLE: True, HOTKEY: "5"}
        task.enabled = True
        task._manual_key_triggers_enabled.return_value = True
        task._get_vk_code.side_effect = lambda key: {
            "5": 53, "mouse4": 5, "mouse5": 6, "w": 87, "a": 65, "s": 83, "d": 68,
        }.get(key)
        task._is_key_pressed.return_value = False
        task.executor.paused = False
        task.executor.current_task = None
        task.executor.exit_event.is_set.return_value = False
        task.executor.method.get_frame.return_value = np.zeros((1080, 1920, 3), np.uint8)
        controller = ActivityController(task)
        return controller, task

    def test_group_defaults_off_and_exposes_key(self):
        task = SimpleNamespace(default_config={}, config_type={}, config_description={})
        configure_activity(task)
        self.assertFalse(task.default_config[ENABLE])
        self.assertEqual(task.default_config[HOTKEY], "6")
        self.assertEqual(task.default_config[PRIORITY], "下一关/开始挑战")
        self.assertEqual(task.config_type[GROUP]["sub_configs"][True],
                         [ENABLE, HOTKEY, MOVE_SECONDS,
                          PRIORITY, FOOT_X, FOOT_Y])

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

    def test_other_task_blocks_input(self):
        controller, task = self.make_controller()
        self.assertTrue(controller.available())
        task.executor.current_task = object()
        self.assertFalse(controller.available())

    def test_background_pulse_releases_keys_on_error(self):
        controller, task = self.make_controller()
        controller.running = True
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
            controller.process()
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
        controller.running = True
        task.executor.interaction.send_key_down.side_effect = (
            lambda key: task.config.update({ENABLE: False})
        )
        controller.pulse(("w", "a"))
        task.executor.interaction.send_key_down.assert_called_once_with("w")
        task.executor.interaction.send_key_up.assert_called_once_with("w")


    def test_unknown_scene_and_missing_frame_never_move(self):
        controller, task = self.make_controller()
        with patch.object(controller, "text", return_value=""):
            controller.tick()
        task.executor.interaction.send_key_down.assert_not_called()
        controller.running = True
        task.executor.method.get_frame.return_value = None
        controller.tick()
        self.assertTrue(controller.running)


if __name__ == "__main__":
    unittest.main()
