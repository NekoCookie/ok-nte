"""[lw] OCR click task word parsing and priority selection."""

import unittest

from src.lw.ocr_click_ext import parse_words, pick_text


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


if __name__ == "__main__":
    unittest.main()
