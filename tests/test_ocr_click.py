"""[lw] OCR click task word parsing and priority selection."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.lw.ocr_click_ext import OcrClickTaskMixin, parse_words, pick_text


class _Stop(Exception):
    pass


class _FakeTask(OcrClickTaskMixin):
    def __init__(self, words, screens):
        self.default_config, self.config_description = {}, {}
        self.configure_ocr_click()
        self.config = dict(self.default_config, **{self.CONF_CLICK_INTERVAL: 0.5})
        self.config[self.CONF_WORDS] = words
        self.screens = iter(screens)
        self.edits = {}
        self.sleeps = 0
        self.operate_click = MagicMock(return_value=True)
        self.log_info = self.log_error = self.info_set = MagicMock()
        self.next_frame = MagicMock()
        self.in_combat = MagicMock(return_value=False)
        self.lw_combat_run = MagicMock()

    def ocr(self, threshold):
        return [SimpleNamespace(name=name) for name in next(self.screens)]

    def sleep(self, seconds):
        self.sleeps += 1
        self.config.update(self.edits.pop(self.sleeps, {}))
        if self.sleeps >= 3:
            raise _Stop


class TestOcrClick(unittest.TestCase):
    def test_parse_words_splits_separators_and_drops_short_words(self):
        self.assertEqual(
            parse_words("无尽 挑战/开始挑战，确认\n领取、再来一次;是"),
            ["无尽挑战", "开始挑战", "确认", "领取", "再来一次"],
        )
        self.assertEqual(parse_words(None), [])

    def test_earlier_word_wins_over_earlier_box(self):
        names = ["开始挑战", "无 尽挑战"]
        self.assertEqual(pick_text(names, ["无尽挑战", "开始挑战"]), (1, "无尽挑战"))

    def test_no_match_returns_none(self):
        self.assertIsNone(pick_text(["设置", "返回"], ["开始挑战"]))

    def test_words_added_mid_run_take_effect(self):
        task = _FakeTask("下一关", [["开始挑战"], ["开始挑战"], ["开始挑战"]])
        task.edits = {1: {task.CONF_WORDS: "下一关/开始挑战"}}
        with self.assertRaises(_Stop):
            task.ocr_click_run()
        clicked = [call.args[0].name for call in task.operate_click.call_args_list]
        self.assertEqual(clicked, ["开始挑战"])

    def test_combat_is_fought_before_resuming_ocr_clicks(self):
        task = _FakeTask("开始挑战", [["开始挑战"]] * 3)
        task.in_combat.side_effect = [True] + [False] * 3
        with self.assertRaises(_Stop):
            task.ocr_click_run()
        task.lw_combat_run.assert_called_once()
        self.assertEqual(task.operate_click.call_count, 1)

    def test_auto_combat_can_be_disabled(self):
        task = _FakeTask("开始挑战", [["开始挑战"]] * 3)
        task.config[task.CONF_AUTO_COMBAT] = False
        task.in_combat.return_value = True
        with self.assertRaises(_Stop):
            task.ocr_click_run()
        task.lw_combat_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
