import unittest
from unittest import mock

from src.tasks.daily.CinemaDateTask import CinemaDateTask


def make_task(ocr_result):
    task = object.__new__(CinemaDateTask)
    task.box_of_screen = mock.MagicMock()
    task.ocr = mock.MagicMock(return_value=ocr_result)
    task.scroll_and_is_end = mock.MagicMock(return_value=True)
    task._find_selectable_target = mock.MagicMock(return_value=[])
    task._top_selectable_target = mock.MagicMock(return_value=mock.MagicMock())
    task.wait_click_confirm = mock.MagicMock(return_value=True)
    task.log_info = mock.MagicMock()
    return task


class TestCinemaDateTarget(unittest.TestCase):
    def test_unavailable_named_target_does_not_date_another_character(self):
        task = make_task(ocr_result=[])

        self.assertFalse(task._select_date("黑羽"))

        task._top_selectable_target.assert_not_called()
        task.wait_click_confirm.assert_not_called()

    def test_empty_target_still_dates_the_top_selectable_character(self):
        task = make_task(ocr_result=[])

        self.assertTrue(task._select_date(""))

        task._top_selectable_target.assert_called_once_with()
        task.wait_click_confirm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
