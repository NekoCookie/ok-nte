import unittest
from types import SimpleNamespace

from src.lw.hide_seek_ext import HideSeekTaskMixin
from src.tasks.HideSeekTask import HideSeekTask


class TestHideSeekTask(unittest.TestCase):
    def test_task_uses_the_lw_matchmaking_mixin(self):
        self.assertTrue(issubclass(HideSeekTask, HideSeekTaskMixin))

    def test_start_match_ocr_accepts_chinese_and_english_labels(self):
        self.assertTrue(HideSeekTaskMixin.is_start_match_text("开始 匹配"))
        self.assertTrue(HideSeekTaskMixin.is_start_match_text("Start Match"))
        self.assertFalse(HideSeekTaskMixin.is_start_match_text("取消匹配"))

    def test_score_ocr_reassembles_split_digits_and_selects_the_largest_total(self):
        task = object.__new__(HideSeekTaskMixin)
        task.box_of_screen = lambda *args, **kwargs: args
        task.ocr = lambda **kwargs: [
            SimpleNamespace(name="1200/5000"),
            SimpleNamespace(name="62,000"),
            SimpleNamespace(name="/100,000"),
        ]

        self.assertEqual(task._ocr_match_score(HideSeekTaskMixin.SCORE_ROI), (62000, 100000))


if __name__ == "__main__":
    unittest.main()
