import unittest
from unittest.mock import Mock, call, patch

from ok import TaskDisabledException

from src.tasks.VolleyballTask import VolleyballTask


class TestVolleyballTask(unittest.TestCase):
    def test_lose_pattern_accepts_partial_ocr_result(self):
        self.assertIsNotNone(VolleyballTask.LOSE_TEXT_RE.search("LO"))
        self.assertIsNotNone(VolleyballTask.LOSE_TEXT_RE.search("LOSE"))
        self.assertIsNotNone(VolleyballTask.WIN_TEXT_RE.search("WIN"))

    def make_task(
        self,
        mode=None,
        next_button="next_button",
        restart_button="restart_button",
        stars=0,
        lost=False,
        won=True,
    ):
        class MatchEndTask:
            CONF_MODE = VolleyballTask.CONF_MODE
            MODE_EXP = VolleyballTask.MODE_EXP
            MODE_AUTO = VolleyballTask.MODE_AUTO
            MODE_SUP = VolleyballTask.MODE_SUP
            INFO_LEVEL_STATUS = VolleyballTask.INFO_LEVEL_STATUS

            def __init__(self):
                self.config = {VolleyballTask.CONF_MODE: mode or VolleyballTask.MODE_EXP}
                self.get_match_end_button = Mock(
                    side_effect=lambda next_level: next_button if next_level else restart_button
                )
                self.has_three_stars = Mock(return_value=stars == 3)
                self.is_match_lost = Mock(return_value=lost)
                self.is_match_won = Mock(return_value=won)
                self.info_set = Mock()
                self.handle_match_result = Mock()
                self.sleep = Mock()

            has_three_stars = VolleyballTask.has_three_stars

        task = MatchEndTask()
        return task

    def test_experience_mode_restarts_without_advancing(self):
        next_button = object()
        restart_button = object()
        task = self.make_task(next_button=next_button, restart_button=restart_button)

        self.assertTrue(VolleyballTask.handle_match_end(task))

        task.handle_match_result.assert_called_once_with(restart_button, won=True, next_level=False)
        task.get_match_end_button.assert_called_once_with(next_level=False)

    def test_auto_mode_advances_only_after_three_stars(self):
        next_button = object()
        task = self.make_task(
            mode=VolleyballTask.MODE_AUTO,
            next_button=next_button,
            restart_button=object(),
            stars=3,
        )

        self.assertTrue(VolleyballTask.handle_match_end(task))

        task.handle_match_result.assert_called_once_with(next_button, won=True, next_level=True)
        task.get_match_end_button.assert_called_once_with(next_level=True)

    def test_auto_mode_restarts_when_not_three_stars(self):
        restart_button = object()
        task = self.make_task(
            mode=VolleyballTask.MODE_AUTO,
            restart_button=restart_button,
            stars=2,
        )

        self.assertTrue(VolleyballTask.handle_match_end(task))

        task.handle_match_result.assert_called_once_with(restart_button, won=True, next_level=False)
        task.get_match_end_button.assert_called_once_with(next_level=False)

    def test_auto_mode_restarts_after_lost_match(self):
        restart_button = object()
        task = self.make_task(
            mode=VolleyballTask.MODE_AUTO,
            restart_button=restart_button,
            stars=3,
            lost=True,
        )

        self.assertTrue(VolleyballTask.handle_match_end(task))

        task.handle_match_result.assert_called_once_with(restart_button, won=False, next_level=False)
        task.get_match_end_button.assert_called_once_with(next_level=False)

    def test_result_requires_a_win_or_loss_screen(self):
        task = self.make_task(won=False)

        self.assertFalse(VolleyballTask.handle_match_end(task))

        task.handle_match_result.assert_not_called()
        task.get_match_end_button.assert_not_called()

    def test_result_text_without_match_end_actions_is_not_a_match_end(self):
        task = self.make_task(restart_button=None)

        self.assertFalse(VolleyballTask.handle_match_end(task))

        task.handle_match_result.assert_not_called()
        task.get_match_end_button.assert_called_once_with(next_level=False)

    def test_auto_mode_never_restarts_a_three_star_win_when_next_is_not_found(self):
        task = self.make_task(
            mode=VolleyballTask.MODE_AUTO,
            next_button=None,
            stars=3,
        )

        self.assertFalse(VolleyballTask.handle_match_end(task))

        task.handle_match_result.assert_not_called()
        task.get_match_end_button.assert_called_once_with(next_level=True)

    def test_match_loss_restarts_without_marking_final_level(self):
        restart_button = object()
        task = self.make_task(restart_button=restart_button)
        task.is_match_lost.return_value = True

        self.assertTrue(VolleyballTask.handle_match_end(task))

        task.handle_match_result.assert_called_once_with(
            restart_button,
            won=False,
            next_level=False,
        )

    def test_three_gold_stars_are_required_to_advance(self):
        task = Mock()
        task.STAR_ROIS = VolleyballTask.STAR_ROIS
        task.STAR_GOLD_COLOR = VolleyballTask.STAR_GOLD_COLOR
        task.STAR_GOLD_THRESHOLD = VolleyballTask.STAR_GOLD_THRESHOLD
        task.box_of_screen.side_effect = ["star_1", "star_2", "star_3"]
        task.calculate_color_percentage.side_effect = [0.24, 0.24, 0.24]

        self.assertTrue(VolleyballTask.has_three_stars(task))

        task.box_of_screen.side_effect = ["star_1", "star_2", "star_3"]
        task.calculate_color_percentage.side_effect = [0.24, 0.02, 0.24]
        self.assertFalse(VolleyballTask.has_three_stars(task))

    def test_match_end_button_is_located_by_action_text(self):
        task = Mock()
        task.RESULT_ACTIONS_ROI = VolleyballTask.RESULT_ACTIONS_ROI
        task.NEXT_LEVEL_ACTION_RE = VolleyballTask.NEXT_LEVEL_ACTION_RE
        task.RESTART_ACTION_RE = VolleyballTask.RESTART_ACTION_RE
        task.box_of_screen.return_value = "actions"
        task.ocr.return_value = ["restart_button"]

        self.assertEqual(
            VolleyballTask.get_match_end_button(task, next_level=False),
            "restart_button",
        )
        task.ocr.assert_called_once_with(
            box="actions",
            match=VolleyballTask.RESTART_ACTION_RE,
        )

    def test_match_end_button_increments_match_count(self):
        class MatchCounter:
            INFO_MATCH_COUNT = VolleyballTask.INFO_MATCH_COUNT
            INFO_WIN_COUNT = VolleyballTask.INFO_WIN_COUNT
            INFO_LOSS_COUNT = VolleyballTask.INFO_LOSS_COUNT

            def __init__(self):
                self.match_count = 0
                self.win_count = 0
                self.loss_count = 0
                self._match_result_recorded = False
                self.operate_click = Mock()
                self.info_set = Mock()

        task = MatchCounter()
        button = object()

        VolleyballTask.click_match_end_button(task, button, won=False)

        task.operate_click.assert_called_once_with(button, after_sleep=0.5)
        self.assertEqual(task.match_count, 1)
        self.assertEqual(task.win_count, 0)
        self.assertEqual(task.loss_count, 1)
        task.info_set.assert_any_call(VolleyballTask.INFO_MATCH_COUNT, 1)
        task.info_set.assert_any_call(VolleyballTask.INFO_LOSS_COUNT, 1)

    def test_result_is_not_counted_twice_while_result_page_is_visible(self):
        class MatchCounter:
            INFO_MATCH_COUNT = VolleyballTask.INFO_MATCH_COUNT
            INFO_WIN_COUNT = VolleyballTask.INFO_WIN_COUNT
            INFO_LOSS_COUNT = VolleyballTask.INFO_LOSS_COUNT

            def __init__(self):
                self.match_count = 0
                self.win_count = 0
                self.loss_count = 0
                self._match_result_recorded = False
                self.operate_click = Mock()
                self.info_set = Mock()

        task = MatchCounter()
        button = object()

        VolleyballTask.click_match_end_button(task, button, won=True)
        VolleyballTask.click_match_end_button(task, button, won=True)

        self.assertEqual(task.match_count, 1)
        self.assertEqual(task.win_count, 1)
        self.assertEqual(task.loss_count, 0)

    def test_loss_status_is_not_final_level(self):
        class ResultHandler:
            INFO_LEVEL_STATUS = VolleyballTask.INFO_LEVEL_STATUS

            def __init__(self):
                self.info_set = Mock()
                self.click_match_end_button = Mock()
                self.reset_service_phase = Mock()

        task = ResultHandler()
        button = object()

        VolleyballTask.handle_match_result(task, button, won=False, next_level=False)

        task.info_set.assert_called_once_with(VolleyballTask.INFO_LEVEL_STATUS, "本局失败")
        task.click_match_end_button.assert_called_once_with(button, False)

    def test_win_without_advancing_reports_restarting_the_current_level(self):
        class ResultHandler:
            INFO_LEVEL_STATUS = VolleyballTask.INFO_LEVEL_STATUS

            def __init__(self):
                self.info_set = Mock()
                self.click_match_end_button = Mock()
                self.reset_service_phase = Mock()

        task = ResultHandler()

        VolleyballTask.handle_match_result(task, object(), won=True, next_level=False)

        task.info_set.assert_called_once_with(VolleyballTask.INFO_LEVEL_STATUS, "重开当前关")

    def test_missing_exit_checks_for_dialog_skip_during_an_active_match(self):
        task = Mock()
        task.handle_match_end.return_value = False
        skip_task = Mock()

        in_game = VolleyballTask.handle_missing_exit(task, True, skip_task)

        self.assertTrue(in_game)
        skip_task.check_skip.assert_called_once_with()

    def test_missing_exit_checks_for_dialog_skip_before_match_starts(self):
        task = Mock()
        task.handle_match_end.return_value = False
        skip_task = Mock()

        in_game = VolleyballTask.handle_missing_exit(task, False, skip_task)

        self.assertFalse(in_game)
        skip_task.check_skip.assert_called_once_with()

    def test_missing_exit_marks_match_inactive_after_result_button_is_handled(self):
        task = Mock()
        task.handle_match_end.return_value = True
        skip_task = Mock()

        in_game = VolleyballTask.handle_missing_exit(task, True, skip_task)

        self.assertFalse(in_game)
        skip_task.check_skip.assert_not_called()

    def test_match_start_does_not_send_keys_before_exit_is_stable(self):
        class MatchStarter:
            def __init__(self):
                self.find_exit = Mock()
                self.wait_until = Mock(return_value=False)
                self.log_info = Mock()
                self.handle_service = Mock()

        task = MatchStarter()

        self.assertFalse(VolleyballTask.begin_match(task))
        task.handle_service.assert_not_called()

    def test_service_is_handled_after_the_match_has_already_started(self):
        class ServiceTask:
            CONF_SERVE_DELAY = VolleyballTask.CONF_SERVE_DELAY
            DEFAULT_SERVE_DELAY = VolleyballTask.DEFAULT_SERVE_DELAY
            MIN_SERVE_DELAY = VolleyballTask.MIN_SERVE_DELAY
            MAX_SERVE_DELAY = VolleyballTask.MAX_SERVE_DELAY
            SERVICE_RELEASE_CONFIRM_SECONDS = VolleyballTask.SERVICE_RELEASE_CONFIRM_SECONDS
            SERVICE_PHASE_WARNING_SECONDS = VolleyballTask.SERVICE_PHASE_WARNING_SECONDS
            SERVICE_PHASE_HARD_TIMEOUT_SECONDS = VolleyballTask.SERVICE_PHASE_HARD_TIMEOUT_SECONDS

            def __init__(self):
                self.config = {self.CONF_SERVE_DELAY: 2.8}
                self._service_phase_active = False
                self._service_phase_started_at = 0.0
                self._service_release_started_at = None
                self._service_phase_warning_logged = False
                self.is_service = Mock(return_value=True)
                self.log_info = Mock()
                self.send_key = Mock()
                self.sleep = Mock()

            check_service_phase_timeout = VolleyballTask.check_service_phase_timeout
            get_serve_delay = VolleyballTask.get_serve_delay
            handle_service_release = VolleyballTask.handle_service_release
            reset_service_phase = VolleyballTask.reset_service_phase

        task = ServiceTask()

        with patch("src.tasks.VolleyballTask.time.monotonic", return_value=10.0):
            self.assertTrue(VolleyballTask.handle_service(task))

        task.send_key.assert_has_calls([call("j"), call("k")])
        task.sleep.assert_called_once_with(2.8)

    def test_serve_delay_is_read_when_each_new_service_phase_starts(self):
        class ServiceTask:
            CONF_SERVE_DELAY = VolleyballTask.CONF_SERVE_DELAY
            DEFAULT_SERVE_DELAY = VolleyballTask.DEFAULT_SERVE_DELAY
            MIN_SERVE_DELAY = VolleyballTask.MIN_SERVE_DELAY
            MAX_SERVE_DELAY = VolleyballTask.MAX_SERVE_DELAY

            def __init__(self):
                self.config = {self.CONF_SERVE_DELAY: 2.5}
                self._service_phase_active = False
                self._service_phase_started_at = 0.0
                self._service_release_started_at = None
                self._service_phase_warning_logged = False
                self.is_service = Mock(return_value=True)
                self.log_info = Mock()
                self.log_warning = Mock()
                self.send_key = Mock()
                self.sleep = Mock()

            get_serve_delay = VolleyballTask.get_serve_delay

        task = ServiceTask()

        with patch("src.tasks.VolleyballTask.time.monotonic", return_value=10.0):
            VolleyballTask.handle_service(task)
        task._service_phase_active = False
        task.config[VolleyballTask.CONF_SERVE_DELAY] = 3.1
        with patch("src.tasks.VolleyballTask.time.monotonic", return_value=20.0):
            VolleyballTask.handle_service(task)

        self.assertEqual(task.sleep.call_args_list, [call(2.5), call(3.1)])

    def test_serve_delay_uses_a_safe_range_and_invalid_value_falls_back(self):
        class DelayTask:
            CONF_SERVE_DELAY = VolleyballTask.CONF_SERVE_DELAY
            DEFAULT_SERVE_DELAY = VolleyballTask.DEFAULT_SERVE_DELAY
            MIN_SERVE_DELAY = VolleyballTask.MIN_SERVE_DELAY
            MAX_SERVE_DELAY = VolleyballTask.MAX_SERVE_DELAY

            def __init__(self, delay):
                self.config = {self.CONF_SERVE_DELAY: delay}
                self.log_warning = Mock()

        for configured_delay, expected_delay in [(0.1, 0.5), (8, 5.0), ("bad", 2.5)]:
            task = DelayTask(configured_delay)
            self.assertEqual(VolleyballTask.get_serve_delay(task), expected_delay)

    def test_serve_delay_config_rejects_values_outside_the_safe_range(self):
        task = object.__new__(VolleyballTask)

        self.assertIsNone(task.validate_config(VolleyballTask.CONF_SERVE_DELAY, 2.5))
        for invalid_delay in (0.1, 8, "bad"):
            self.assertEqual(
                task.validate_config(VolleyballTask.CONF_SERVE_DELAY, invalid_delay),
                VolleyballTask.SERVE_DELAY_RANGE_ERROR,
            )

    def test_play_interval_uses_a_safe_range_and_invalid_value_falls_back(self):
        class IntervalTask:
            CONF_PLAY_INTERVAL = VolleyballTask.CONF_PLAY_INTERVAL
            DEFAULT_PLAY_INTERVAL = VolleyballTask.DEFAULT_PLAY_INTERVAL
            MIN_PLAY_INTERVAL = VolleyballTask.MIN_PLAY_INTERVAL
            MAX_PLAY_INTERVAL = VolleyballTask.MAX_PLAY_INTERVAL

            def __init__(self, interval):
                self.config = {self.CONF_PLAY_INTERVAL: interval}
                self.log_warning = Mock()

        for configured_interval, expected_interval in [(0.05, 0.1), (3, 2.0), ("bad", 0.5)]:
            task = IntervalTask(configured_interval)
            self.assertEqual(VolleyballTask.get_play_interval(task), expected_interval)

    def test_play_interval_config_rejects_values_outside_the_safe_range(self):
        task = object.__new__(VolleyballTask)

        self.assertIsNone(task.validate_config(VolleyballTask.CONF_PLAY_INTERVAL, 0.5))
        for invalid_interval in (0.05, 3, "bad"):
            self.assertEqual(
                task.validate_config(VolleyballTask.CONF_PLAY_INTERVAL, invalid_interval),
                VolleyballTask.PLAY_INTERVAL_RANGE_ERROR,
            )

    def test_active_service_phase_blocks_duplicate_inputs_after_four_seconds(self):
        class ServiceTask:
            SERVICE_RELEASE_CONFIRM_SECONDS = VolleyballTask.SERVICE_RELEASE_CONFIRM_SECONDS
            SERVICE_PHASE_WARNING_SECONDS = VolleyballTask.SERVICE_PHASE_WARNING_SECONDS
            SERVICE_PHASE_HARD_TIMEOUT_SECONDS = VolleyballTask.SERVICE_PHASE_HARD_TIMEOUT_SECONDS

            def __init__(self):
                self._service_phase_active = True
                self._service_phase_started_at = 9.0
                self._service_release_started_at = None
                self._service_phase_warning_logged = False
                self.is_service = Mock(return_value=True)
                self.log_info = Mock()
                self.log_warning = Mock()
                self.send_key = Mock()
                self.sleep = Mock()

            check_service_phase_timeout = VolleyballTask.check_service_phase_timeout
            handle_service_release = VolleyballTask.handle_service_release
            reset_service_phase = VolleyballTask.reset_service_phase

        task = ServiceTask()

        with patch("src.tasks.VolleyballTask.time.monotonic", return_value=13.1):
            self.assertTrue(VolleyballTask.handle_service(task))

        task.send_key.assert_not_called()

    def test_service_phase_releases_only_after_stable_non_service(self):
        class ServiceTask:
            SERVICE_RELEASE_CONFIRM_SECONDS = VolleyballTask.SERVICE_RELEASE_CONFIRM_SECONDS
            SERVICE_PHASE_WARNING_SECONDS = VolleyballTask.SERVICE_PHASE_WARNING_SECONDS
            SERVICE_PHASE_HARD_TIMEOUT_SECONDS = VolleyballTask.SERVICE_PHASE_HARD_TIMEOUT_SECONDS

            def __init__(self):
                self._service_phase_active = True
                self._service_phase_started_at = 1.0
                self._service_release_started_at = None
                self._service_phase_warning_logged = False
                self.log_info = Mock()
                self.log_warning = Mock()

            check_service_phase_timeout = VolleyballTask.check_service_phase_timeout
            reset_service_phase = VolleyballTask.reset_service_phase

        task = ServiceTask()

        self.assertTrue(VolleyballTask.handle_service_release(task, 2.0))
        self.assertTrue(VolleyballTask.handle_service_release(task, 2.4))
        self.assertFalse(VolleyballTask.handle_service_release(task, 2.5))
        task.log_info.assert_called_once_with("service phase cleared")

    def test_service_phase_stops_after_hard_timeout(self):
        class ServiceTask:
            SERVICE_RELEASE_CONFIRM_SECONDS = VolleyballTask.SERVICE_RELEASE_CONFIRM_SECONDS
            SERVICE_PHASE_WARNING_SECONDS = VolleyballTask.SERVICE_PHASE_WARNING_SECONDS
            SERVICE_PHASE_HARD_TIMEOUT_SECONDS = VolleyballTask.SERVICE_PHASE_HARD_TIMEOUT_SECONDS

            def __init__(self):
                self._service_phase_active = True
                self._service_phase_started_at = 0.0
                self._service_release_started_at = None
                self._service_phase_warning_logged = False
                self.is_service = Mock(return_value=True)
                self.log_info = Mock()
                self.log_warning = Mock()
                self.send_key = Mock()
                self.sleep = Mock()

            check_service_phase_timeout = VolleyballTask.check_service_phase_timeout
            handle_service_release = VolleyballTask.handle_service_release
            reset_service_phase = VolleyballTask.reset_service_phase

        task = ServiceTask()

        with patch(
            "src.tasks.VolleyballTask.time.monotonic",
            return_value=VolleyballTask.SERVICE_PHASE_HARD_TIMEOUT_SECONDS,
        ):
            with self.assertRaisesRegex(TaskDisabledException, "Serve UI did not clear"):
                VolleyballTask.handle_service(task)

        task.send_key.assert_not_called()

    def test_play_once_adjusts_position_after_four_hits(self):
        class PlayTask:
            CONF_MODE = VolleyballTask.CONF_MODE
            CONF_POSITION_ADJUST = VolleyballTask.CONF_POSITION_ADJUST
            MODE_EXP = VolleyballTask.MODE_EXP
            MODE_AUTO = VolleyballTask.MODE_AUTO
            MODE_SUP = VolleyballTask.MODE_SUP
            DEFAULT_POSITION_ADJUST = VolleyballTask.DEFAULT_POSITION_ADJUST
            POSITION_ADJUST_AFTER_HITS = VolleyballTask.POSITION_ADJUST_AFTER_HITS

            def __init__(self):
                self.config = {
                    VolleyballTask.CONF_MODE: VolleyballTask.MODE_AUTO,
                    VolleyballTask.CONF_POSITION_ADJUST: True,
                }
                self._play_count = VolleyballTask.POSITION_ADJUST_AFTER_HITS
                self.sleep = Mock()
                self.send_key = Mock()

        task = PlayTask()

        key, switch_key = VolleyballTask.play_once(task, "j", False)

        self.assertEqual((key, switch_key), ("j", False))
        self.assertEqual(task._play_count, 0)
        task.send_key.assert_has_calls([call("a", down_time=0.1), call("s", down_time=0.1)])

    def test_play_once_skips_position_adjustment_when_disabled(self):
        class PlayTask:
            CONF_MODE = VolleyballTask.CONF_MODE
            CONF_PLAY_INTERVAL = VolleyballTask.CONF_PLAY_INTERVAL
            CONF_POSITION_ADJUST = VolleyballTask.CONF_POSITION_ADJUST
            MODE_EXP = VolleyballTask.MODE_EXP
            MODE_AUTO = VolleyballTask.MODE_AUTO
            MODE_SUP = VolleyballTask.MODE_SUP
            DEFAULT_PLAY_INTERVAL = VolleyballTask.DEFAULT_PLAY_INTERVAL
            MIN_PLAY_INTERVAL = VolleyballTask.MIN_PLAY_INTERVAL
            MAX_PLAY_INTERVAL = VolleyballTask.MAX_PLAY_INTERVAL
            DEFAULT_POSITION_ADJUST = VolleyballTask.DEFAULT_POSITION_ADJUST
            POSITION_ADJUST_AFTER_HITS = VolleyballTask.POSITION_ADJUST_AFTER_HITS

            def __init__(self):
                self.config = {
                    VolleyballTask.CONF_MODE: VolleyballTask.MODE_AUTO,
                    VolleyballTask.CONF_PLAY_INTERVAL: 0.3,
                    VolleyballTask.CONF_POSITION_ADJUST: False,
                }
                self._play_count = VolleyballTask.POSITION_ADJUST_AFTER_HITS
                self.log_warning = Mock()
                self.sleep = Mock()
                self.send_key = Mock(return_value=True)

            get_play_interval = VolleyballTask.get_play_interval

        task = PlayTask()

        key, switch_key = VolleyballTask.play_once(task, "j", False)

        self.assertEqual((key, switch_key), ("k", True))
        self.assertEqual(task._play_count, 0)
        task.sleep.assert_not_called()
        task.send_key.assert_called_once_with("j", interval=0.3)

    def test_service_requires_both_serve_action_keys_to_be_highlighted(self):
        task = Mock()
        task.SERVICE_ACTION_ROIS = VolleyballTask.SERVICE_ACTION_ROIS
        task.SERVICE_ACTION_WHITE_THRESHOLD = VolleyballTask.SERVICE_ACTION_WHITE_THRESHOLD
        task.box_of_screen.side_effect = ["toss_key", "serve_key"]
        task.calculate_color_percentage.side_effect = [0.05, 0.06]

        self.assertTrue(VolleyballTask.is_service(task))

        self.assertEqual(
            task.box_of_screen.call_args_list,
            [call(*roi) for roi in task.SERVICE_ACTION_ROIS],
        )

    def test_service_rejects_a_partially_highlighted_action_pair(self):
        task = Mock()
        task.SERVICE_ACTION_ROIS = VolleyballTask.SERVICE_ACTION_ROIS
        task.SERVICE_ACTION_WHITE_THRESHOLD = VolleyballTask.SERVICE_ACTION_WHITE_THRESHOLD
        task.box_of_screen.side_effect = ["toss_key", "serve_key"]
        task.calculate_color_percentage.side_effect = [0.05, 0.0]

        self.assertFalse(VolleyballTask.is_service(task))

    def test_missing_exit_checks_service_but_blocks_regular_controls(self):
        class StopLoop(Exception):
            pass

        task = Mock()
        task.find_exit.return_value = False
        task.handle_missing_exit.return_value = True
        task.handle_service.return_value = False
        task.sleep.side_effect = StopLoop

        with self.assertRaises(StopLoop):
            VolleyballTask.auto_play(task)

        task.handle_service.assert_called_once_with()
        task.is_spike.assert_not_called()
        task.play_once.assert_not_called()


if __name__ == "__main__":
    unittest.main()
