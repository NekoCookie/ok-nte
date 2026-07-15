import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.tasks.DailyTask import DailyTask


class TestDailyStamina(unittest.TestCase):
    @staticmethod
    def _make_task(*, used_stamina: int, daily_activity: int, target_stamina: int):
        task = object.__new__(DailyTask)
        task.config = {DailyTask.DAILY_STAMINA_TARGET: target_stamina}
        task._open_activity = Mock(return_value=True)
        task.box_of_screen = Mock(side_effect=["mission_box", "activity_box"])
        task.ocr = Mock(
            side_effect=[
                [SimpleNamespace(name=str(daily_activity))],
                [SimpleNamespace(name=f"{used_stamina}/180")],
            ]
        )
        task.log_info = Mock()
        task.info_set = Mock()
        task.operate = Mock()
        task.sleep = Mock()
        return task

    def test_full_daily_activity_does_not_skip_unfinished_stamina_target(self):
        task = self._make_task(used_stamina=0, daily_activity=100, target_stamina=320)

        self.assertFalse(DailyTask.check_activity(task))
        task.info_set.assert_any_call("used stamina", 0)
        task.info_set.assert_any_call("daily activity", 100)

    def test_stamina_target_skips_even_if_daily_activity_is_unfinished(self):
        task = self._make_task(used_stamina=180, daily_activity=0, target_stamina=180)

        self.assertTrue(DailyTask.check_activity(task))


if __name__ == "__main__":
    unittest.main()
