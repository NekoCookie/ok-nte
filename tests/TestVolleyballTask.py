import unittest
from unittest.mock import Mock, call, patch

from src.Labels import Labels
from src.tasks.VolleyballTask import VolleyballTask


class TestVolleyballTask(unittest.TestCase):
    def test_lose_pattern_accepts_partial_ocr_result(self):
        self.assertIsNotNone(VolleyballTask.LOSE_TEXT_RE.search("LO"))
        self.assertIsNotNone(VolleyballTask.LOSE_TEXT_RE.search("LOSE"))

    def make_task(self, next_button=None, restart_button=None):
        class MatchEndTask:
            CONF_MODE = VolleyballTask.CONF_MODE
            MODE_EXP = VolleyballTask.MODE_EXP
            MODE_SUP = VolleyballTask.MODE_SUP
            INFO_LEVEL_STATUS = VolleyballTask.INFO_LEVEL_STATUS

            def __init__(self):
                self.config = {VolleyballTask.CONF_MODE: VolleyballTask.MODE_EXP}
                self.find_next_level_button = Mock(return_value=next_button)
                self.find_one = Mock(return_value=restart_button)
                self.is_match_lost = Mock(return_value=False)
                self.info_set = Mock()
                self.handle_match_result = Mock()

        task = MatchEndTask()
        return task

    def test_match_end_prefers_next_level_button(self):
        next_button = object()
        task = self.make_task(next_button=next_button, restart_button=object())

        self.assertTrue(VolleyballTask.handle_match_end(task))

        task.handle_match_result.assert_called_once_with(next_button, won=True, next_level=True)
        task.find_one.assert_not_called()

    def test_match_end_falls_back_to_restart_button(self):
        restart_button = object()
        task = self.make_task(restart_button=restart_button)

        self.assertTrue(VolleyballTask.handle_match_end(task))

        task.find_one.assert_called_once_with(Labels.volleyball_restart)
        task.handle_match_result.assert_called_once_with(restart_button, won=True, next_level=False)

    def test_match_loss_restarts_without_marking_final_level(self):
        restart_button = object()
        task = self.make_task(restart_button=restart_button)
        task.is_match_lost.return_value = True

        self.assertTrue(VolleyballTask.handle_match_end(task))

        task.handle_match_result.assert_called_once_with(restart_button, won=False, next_level=False)

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
            SERVICE_RETRY_INTERVAL = VolleyballTask.SERVICE_RETRY_INTERVAL

            def __init__(self):
                self._last_serve_time = 0.0
                self.is_service = Mock(return_value=True)
                self.log_info = Mock()
                self.send_key = Mock()
                self.sleep = Mock()

        task = ServiceTask()

        with patch("src.tasks.VolleyballTask.time.monotonic", return_value=10.0):
            self.assertTrue(VolleyballTask.handle_service(task))

        task.send_key.assert_has_calls([call("j"), call("k")])
        task.sleep.assert_called_once_with(2.5)

    def test_active_service_waits_before_retrying_the_serve(self):
        class ServiceTask:
            SERVICE_RETRY_INTERVAL = VolleyballTask.SERVICE_RETRY_INTERVAL

            def __init__(self):
                self._last_serve_time = 9.0
                self.is_service = Mock(return_value=True)
                self.log_info = Mock()
                self.send_key = Mock()
                self.sleep = Mock()

        task = ServiceTask()

        with patch("src.tasks.VolleyballTask.time.monotonic", return_value=10.0):
            self.assertTrue(VolleyballTask.handle_service(task))

        task.send_key.assert_not_called()


if __name__ == "__main__":
    unittest.main()
