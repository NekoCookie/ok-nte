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

            def __init__(self):
                self.config = {VolleyballTask.CONF_MODE: VolleyballTask.MODE_EXP}
                self.find_next_level_button = Mock(return_value=next_button)
                self.find_one = Mock(return_value=restart_button)
                self.operate_click = Mock()

        task = MatchEndTask()
        return task

    def test_match_end_prefers_next_level_button(self):
        next_button = object()
        task = self.make_task(next_button=next_button, restart_button=object())

        VolleyballTask.handle_match_end(task)

        task.operate_click.assert_called_once_with(next_button, after_sleep=0.5)
        task.find_one.assert_not_called()

    def test_match_end_falls_back_to_restart_button(self):
        restart_button = object()
        task = self.make_task(restart_button=restart_button)

        VolleyballTask.handle_match_end(task)

        task.find_one.assert_called_once_with(Labels.volleyball_restart)
        task.operate_click.assert_called_once_with(restart_button, after_sleep=0.5)


if __name__ == "__main__":
    unittest.main()
