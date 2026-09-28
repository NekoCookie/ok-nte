"""[lw] Standalone full-screen OCR text clicker, independent of the activity assist."""

import math
import re
import time

WORD_SPLIT_RE = re.compile(r"[/,，、;；\n]")


def _normalize(text) -> str:
    return re.sub(r"\s+", "", text or "")


def parse_words(text) -> list[str]:
    """Split the priority list; words shorter than 2 chars are too ambiguous to click."""
    words = [_normalize(part) for part in WORD_SPLIT_RE.split(str(text or ""))]
    return [word for word in words if len(word) >= 2]


def pick_text(names, words) -> tuple[int, str] | None:
    """Return (box index, matched word); earlier words win, then earlier OCR boxes."""
    normalized = [_normalize(name) for name in names]
    for word in words:
        for index, name in enumerate(normalized):
            if word in name:
                return index, word
    return None


class OcrClickTaskMixin:
    """[lw] Loop: OCR the whole screen, click the highest-priority configured word."""

    CONF_WORDS = "点击文字"
    CONF_SCAN_INTERVAL = "识别间隔(秒)"
    CONF_CLICK_INTERVAL = "点击间隔(秒)"
    CONF_MAX_MINUTES = "最长运行(分钟)"
    OCR_THRESHOLD = 0.8

    def configure_ocr_click(self):
        self.default_config.update({
            self.CONF_WORDS: "",
            self.CONF_SCAN_INTERVAL: 0.4,
            self.CONF_CLICK_INTERVAL: 2.0,
            self.CONF_MAX_MINUTES: 0,
        })
        self.config_description.update({
            self.CONF_WORDS: "全屏OCR, 按文字从左到右优先点击, 支持/、逗号和换行; "
                             "如 无尽挑战/开始挑战; 每项至少2个字, 忽略空格",
            self.CONF_SCAN_INTERVAL: "每次OCR识别之间的等待, 默认0.4秒; 范围0.1~10秒",
            self.CONF_CLICK_INTERVAL: "两次点击之间的最短间隔, 默认2秒; 范围0.5~60秒; "
                                      "文字持续出现时按此间隔重复点击",
            self.CONF_MAX_MINUTES: "到时自动停止, 0为不限, 手动停止任务即可结束",
        })

    def _ocr_click_float(self, key, default, low, high) -> float:
        try:
            value = float(self.config.get(key, default))
        except (TypeError, ValueError):
            return default
        return min(high, max(low, value)) if math.isfinite(value) else default

    def ocr_click_run(self):
        words = parse_words(self.config.get(self.CONF_WORDS, ""))
        if not words:
            self.log_error("未配置点击文字, 请在任务设置中填写后再启动", notify=True)
            return
        scan_interval = self._ocr_click_float(self.CONF_SCAN_INTERVAL, 0.4, 0.1, 10.0)
        click_interval = self._ocr_click_float(self.CONF_CLICK_INTERVAL, 2.0, 0.5, 60.0)
        max_minutes = self._ocr_click_float(self.CONF_MAX_MINUTES, 0.0, 0.0, 24 * 60.0)
        deadline = time.monotonic() + max_minutes * 60 if max_minutes > 0 else math.inf
        self.log_info(f"OCR识别点击启动, 优先级: {' > '.join(words)}")
        self.info_set("点击次数", 0)
        clicks = 0
        next_click = 0.0
        while time.monotonic() < deadline:
            self.next_frame()
            boxes = self.ocr(threshold=self.OCR_THRESHOLD) or []
            picked = pick_text([box.name for box in boxes], words)
            if picked is None:
                self.info_set("状态", "未识别到配置文字")
            elif time.monotonic() >= next_click:
                index, word = picked
                result = self.operate_click(boxes[index], action_name="ocr_click_word")
                next_click = time.monotonic() + (click_interval if result is not False else 0.5)
                if result is not False:
                    clicks += 1
                    self.info_set("点击次数", clicks)
                    self.info_set("状态", f"已点击: {word}")
                    self.log_info(f"OCR识别点击: {word}")
                else:
                    self.info_set("状态", f"点击被拦截: {word}")
            self.sleep(scan_interval)
        self.log_info(f"OCR识别点击到达最长运行时间, 共点击 {clicks} 次", notify=True)
