import unittest
from unittest.mock import Mock, call, patch

from ok import TaskDisabledException

from src.Labels import Labels
from src.tasks.VolleyballTask import VolleyballTask


class TestVolleyballTask(unittest.TestCase):
    def test_lose_pattern_accepts_partial_ocr_result(self):
        self.assertIsNotNone(VolleyballTask.LOSE_TEXT_RE.search("LO"))
        self.assertIsNotNone(VolleyballTask.LOSE_TEXT_RE.search("LOSE"))

    def make_task(self, mode=None, next_button=None, restart_button=None, stars=0, lost=False):
        class MatchEndTask:
            CONF_MODE = VolleyballTask.CONF_MODE
            MODE_EXP = VolleyballTask.MODE_EXP
            MODE_AUTO = VolleyballTask.MODE_AUTO
            MODE_SUP = VolleyballTask.MODE_SUP
            INFO_LEVEL_STATUS = VolleyballTask.INFO_LEVEL_STATUS

            def __init__(self):
                self.config = {VolleyballTask.CONF_MODE: mode or VolleyballTask.MODE_EXP}
                self.find_one = Mock(
                    side_effect=lambda label: {
                        Labels.volleyball_restart: restart_button,
                        Labels.volleyball_next: next_button,
                    }[label]
                )
                self.get_box_by_name = Mock(return_value="stars_box")
                self.find_feature = Mock(return_value=[object() for _ in range(stars)])
                self.is_match_lost = Mock(return_value=lost)
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
        task.find_one.assert_called_once_with(Labels.volleyball_restart)

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
        task.find_one.assert_has_calls(
            [call(Labels.volleyball_restart), call(Labels.volleyball_next)]
        )

    def test_auto_mode_restarts_when_not_three_stars(self):
        restart_button = object()
        task = self.make_task(
            mode=VolleyballTask.MODE_AUTO,
            restart_button=restart_button,
            stars=2,
        )

        self.assertTrue(VolleyballTask.handle_match_end(task))

        task.handle_match_result.assert_called_once_with(restart_button, won=True, next_level=False)
        task.find_one.assert_called_once_with(Labels.volleyball_restart)

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
        task.find_one.assert_called_once_with(Labels.volleyball_restart)

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

    def test_missing_exit_keeps_active_match_state_without_result_button(self):
        task = Mock()
        task.handle_match_end.return_value = False
        skip_task = Mock()

        in_game = VolleyballTask.handle_missing_exit(task, True, skip_task)

        self.assertTrue(in_game)
        skip_task.check_skip.assert_not_called()

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
            SERVICE_RELEASE_CONFIRM_SECONDS = VolleyballTask.SERVICE_RELEASE_CONFIRM_SECONDS
            SERVICE_PHASE_WARNING_SECONDS = VolleyballTask.SERVICE_PHASE_WARNING_SECONDS
            SERVICE_PHASE_HARD_TIMEOUT_SECONDS = VolleyballTask.SERVICE_PHASE_HARD_TIMEOUT_SECONDS

            def __init__(self):
                self._service_phase_active = False
                self._service_phase_started_at = 0.0
                self._service_release_started_at = None
                self._service_phase_warning_logged = False
                self.is_service = Mock(return_value=True)
                self.log_info = Mock()
                self.send_key = Mock()
                self.sleep = Mock()

            check_service_phase_timeout = VolleyballTask.check_service_phase_timeout
            handle_service_release = VolleyballTask.handle_service_release
            reset_service_phase = VolleyballTask.reset_service_phase

        task = ServiceTask()

        with patch("src.tasks.VolleyballTask.time.monotonic", return_value=10.0):
            self.assertTrue(VolleyballTask.handle_service(task))

        task.send_key.assert_has_calls([call("j"), call("k")])
        task.sleep.assert_called_once_with(2.5)

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
            MODE_EXP = VolleyballTask.MODE_EXP
            MODE_AUTO = VolleyballTask.MODE_AUTO
            MODE_SUP = VolleyballTask.MODE_SUP
            POSITION_ADJUST_AFTER_HITS = VolleyballTask.POSITION_ADJUST_AFTER_HITS

            def __init__(self):
                self.config = {VolleyballTask.CONF_MODE: VolleyballTask.MODE_AUTO}
                self._play_count = VolleyballTask.POSITION_ADJUST_AFTER_HITS
                self.sleep = Mock()
                self.send_key = Mock()

        task = PlayTask()

        key, switch_key = VolleyballTask.play_once(task, "j", False)

        self.assertEqual((key, switch_key), ("j", False))
        self.assertEqual(task._play_count, 0)
        task.send_key.assert_has_calls([call("a", down_time=0.1), call("s", down_time=0.1)])

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
