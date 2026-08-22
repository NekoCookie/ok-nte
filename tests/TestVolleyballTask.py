import unittest
from unittest.mock import Mock

from src.Labels import Labels
from src.tasks.VolleyballTask import VolleyballTask


class TestVolleyballTask(unittest.TestCase):
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
                self.info_set = Mock()
                self.click_match_end_button = Mock()

        task = MatchEndTask()
        return task

    def test_match_end_prefers_next_level_button(self):
        next_button = object()
        task = self.make_task(next_button=next_button, restart_button=object())

        self.assertTrue(VolleyballTask.handle_match_end(task))

        task.click_match_end_button.assert_called_once_with(next_button)
        task.info_set.assert_called_once_with(VolleyballTask.INFO_LEVEL_STATUS, "进入下一关")
        task.find_one.assert_not_called()

    def test_match_end_falls_back_to_restart_button(self):
        restart_button = object()
        task = self.make_task(restart_button=restart_button)

        self.assertTrue(VolleyballTask.handle_match_end(task))

        task.find_one.assert_called_once_with(Labels.volleyball_restart)
        task.click_match_end_button.assert_called_once_with(restart_button)
        task.info_set.assert_called_once_with(VolleyballTask.INFO_LEVEL_STATUS, "已到达最终关")

    def test_match_end_button_increments_match_count(self):
        class MatchCounter:
            INFO_MATCH_COUNT = VolleyballTask.INFO_MATCH_COUNT

            def __init__(self):
                self.match_count = 0
                self.operate_click = Mock()
                self.info_set = Mock()

        task = MatchCounter()
        button = object()

        VolleyballTask.click_match_end_button(task, button)

        task.operate_click.assert_called_once_with(button, after_sleep=0.5)
        self.assertEqual(task.match_count, 1)
        task.info_set.assert_called_once_with(VolleyballTask.INFO_MATCH_COUNT, 1)

    def test_missing_exit_keeps_active_match_state_without_result_button(self):
        task = Mock()
        task.handle_match_end.return_value = False
        skip_task = Mock()

        in_game = VolleyballTask.handle_missing_exit(task, True, skip_task)

        self.assertTrue(in_game)
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
                self.is_service = Mock()
                self.send_key = Mock()
                self.sleep = Mock()

        task = MatchStarter()

        self.assertFalse(VolleyballTask.begin_match(task))
        task.is_service.assert_not_called()
        task.send_key.assert_not_called()


if __name__ == "__main__":
    unittest.main()
