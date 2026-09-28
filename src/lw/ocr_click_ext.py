"""[lw] Standalone full-screen OCR text clicker, independent of the activity assist."""

import math
import re
import time

WORD_SPLIT_RE = re.compile(r"[/,\uFF0C\u3001;\uFF1B\n]")


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
    CONF_AUTO_COMBAT = "进入战斗自动战斗"
    CONF_USE_ULT = "使用终结技"
    CONF_WALK_SECONDS = "未进战斗向前走(秒)"
    OCR_THRESHOLD = 0.8
    WALK_POLL_INTERVAL = 0.3
    WALK_TEXT_SCAN_INTERVAL = 1.0

    def configure_ocr_click(self):
        self.default_config.update({
            self.CONF_WORDS: "",
            self.CONF_SCAN_INTERVAL: 0.4,
            self.CONF_CLICK_INTERVAL: 2.0,
            self.CONF_MAX_MINUTES: 0,
            self.CONF_AUTO_COMBAT: True,
            self.CONF_USE_ULT: True,
            self.CONF_WALK_SECONDS: 10.0,
        })
        self.config_description.update({
            self.CONF_WORDS: "全屏OCR, 按文字从左到右优先点击, 支持/、逗号和换行; "
                             "如 无尽挑战/开始挑战; 每项至少2个字, 忽略空格",
            self.CONF_SCAN_INTERVAL: "每次OCR识别之间的等待, 默认0.4秒; 范围0.1~10秒",
            self.CONF_CLICK_INTERVAL: "两次点击之间的最短间隔, 默认2秒; 范围0.5~60秒; "
                                      "文字持续出现时按此间隔重复点击",
            self.CONF_MAX_MINUTES: "到时自动停止, 0为不限, 手动停止任务即可结束",
            self.CONF_AUTO_COMBAT: "本任务运行时框架不调度自动战斗, 开启后识别到战斗由本任务接管战斗, "
                                   "脱战后继续OCR点击",
            self.CONF_WALK_SECONDS: "在队伍画面且没有可点文字时, 同自动深渊按住W加冲刺向前走找战斗; "
                                    "走满该秒数仍未进战斗就停下, 直到下次战斗或点击后再走; "
                                    "0为关闭, 最大60秒",
        })

    def _ocr_click_float(self, key, default, low, high) -> float:
        try:
            value = float(self.config.get(key, default))
        except (TypeError, ValueError):
            return default
        return min(high, max(low, value)) if math.isfinite(value) else default

    def ocr_click_run(self):
        """Re-read config every scan so words/intervals edited mid-run apply immediately."""
        if not parse_words(self.config.get(self.CONF_WORDS, "")):
            self.log_error("未配置点击文字, 请在任务设置中填写后再启动", notify=True)
            return
        started = time.monotonic()
        self.info_set("点击次数", 0)
        clicks = 0
        next_click = 0.0
        last_words = None
        # One walk per combat/click, so an idle field never turns into endless running.
        walk_spent = False
        while True:
            words = parse_words(self.config.get(self.CONF_WORDS, ""))
            if words != last_words:
                self.log_info(f"OCR识别点击优先级: {' > '.join(words) or '(空)'}")
                last_words = words
            scan_interval = self._ocr_click_float(self.CONF_SCAN_INTERVAL, 0.4, 0.1, 10.0)
            click_interval = self._ocr_click_float(self.CONF_CLICK_INTERVAL, 2.0, 0.5, 60.0)
            max_minutes = self._ocr_click_float(self.CONF_MAX_MINUTES, 0.0, 0.0, 24 * 60.0)
            if max_minutes > 0 and time.monotonic() - started >= max_minutes * 60:
                break
            self.next_frame()
            if self.config.get(self.CONF_AUTO_COMBAT, True) and self.in_combat():
                self.info_set("状态", "战斗中")
                self.log_info("OCR识别点击: 进入战斗, 开始自动战斗")
                self.lw_combat_run()
                self.log_info("OCR识别点击: 脱离战斗, 继续识别")
                walk_spent = False
                continue
            boxes = (self.ocr(threshold=self.OCR_THRESHOLD) or []) if words else []
            picked = pick_text([box.name for box in boxes], words)
            walk_seconds = self._ocr_click_float(self.CONF_WALK_SECONDS, 10.0, 0.0, 60.0)
            if picked is None and walk_seconds > 0 and not walk_spent and self.is_in_team():
                self.info_set("状态", "向前走找战斗")
                if self.ocr_click_walk(walk_seconds, words) == "timeout":
                    walk_spent = True
                    self.log_info(f"OCR识别点击: 向前走 {walk_seconds:.0f}s 未进入战斗, 停止前进")
                continue
            if picked is None:
                self.info_set("状态", "未识别到配置文字" if words else "点击文字为空, 等待配置")
            elif time.monotonic() >= next_click:
                index, word = picked
                result = self.operate_click(boxes[index], action_name="ocr_click_word")
                next_click = time.monotonic() + (click_interval if result is not False else 0.5)
                if result is not False:
                    walk_spent = False
                    clicks += 1
                    self.info_set("点击次数", clicks)
                    self.info_set("状态", f"已点击: {word}")
                    self.log_info(f"OCR识别点击: {word}")
                else:
                    self.info_set("状态", f"点击被拦截: {word}")
            self.sleep(scan_interval)
        self.log_info(f"OCR识别点击到达最长运行时间, 共点击 {clicks} 次", notify=True)

    def ocr_click_walk(self, time_out: float, words) -> str:
        """Sprint forward like the abyss task; stop on combat, a clickable word or timeout."""
        self.middle_click(after_sleep=0.2)
        deadline = time.monotonic() + time_out
        next_text_scan = time.monotonic() + self.WALK_TEXT_SCAN_INTERVAL
        held = False
        try:
            while time.monotonic() < deadline:
                self.next_frame()
                if self.in_combat():
                    return "combat"
                if not self.is_in_team():
                    return "left_team"
                if words and time.monotonic() >= next_text_scan:
                    next_text_scan = time.monotonic() + self.WALK_TEXT_SCAN_INTERVAL
                    boxes = self.ocr(threshold=self.OCR_THRESHOLD) or []
                    if pick_text([box.name for box in boxes], words) is not None:
                        return "text"
                if not held:
                    self.send_key_down("w")
                    held = True
                    self.sleep(0.1)
                    self.send_key("lshift")
                self.sleep(self.WALK_POLL_INTERVAL)
            return "timeout"
        finally:
            if held:
                self.send_key_up("w")
