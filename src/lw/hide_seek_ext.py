"""LW hide-and-seek matchmaking idle workflow helpers.  # [lw]"""

import re
import time


class HideSeekTaskMixin:
    """徊影憧憧活动匹配挂机流程, 与自动捕鱼同款循环结构.  # [lw]"""

    MATCH_BUTTON_ROI = (0.35, 0.82, 0.99, 0.99)
    SCORE_ROI = (0.50, 0.75, 0.995, 0.885)
    SCORE_FALLBACK_ROI = (0.30, 0.70, 0.995, 0.96)
    SCORE_READ_RETRIES = 3
    PAGE_CHECK_INTERVAL = 2.0
    START_MATCH_RE = re.compile(r"开始\s*匹配|start\s*match", re.IGNORECASE)
    # OCR 可能把 "62,000" 拆成 "62" 和 "000" 多个块, 取总额最大的匹配。  # [lw]
    SCORE_RE = re.compile(r"(\d{1,7})\s*/\s*(\d{1,8})")

    @staticmethod
    def is_start_match_text(name: str | None) -> bool:
        return bool(HideSeekTaskMixin.START_MATCH_RE.search(re.sub(r"\s+", "", name or "")))

    def _ocr_match_score(self, roi) -> tuple[int, int] | None:
        box = self.box_of_screen(*roi, name="hide_seek_score")
        texts = self.ocr(box=box)
        if not texts:
            return None
        joined = " ".join(re.sub(r"[\s,，]", "", text.name or "") for text in texts)
        best = None
        for match in self.SCORE_RE.finditer(joined):
            current, total = int(match.group(1)), int(match.group(2))
            if best is None or total > best[1]:
                best = (current, total)
        return best

    def read_match_score(self) -> tuple[int, int] | None:
        """OCR 匹配页活动积分, 返回 (当前, 总额) 或 None。

        回到匹配页后积分栏可能还没渲染完, 多帧重试, 先按精确区域
        再按更宽的区域兜底。识别失败只返回 None, 不影响点击流程。
        """
        for attempt in range(self.SCORE_READ_RETRIES):
            for roi in (self.SCORE_ROI, self.SCORE_FALLBACK_ROI):
                try:
                    score = self._ocr_match_score(roi)
                except Exception as exc:
                    self.log_debug(f"hide_seek score OCR failed: {exc}")
                    score = None
                if score is not None:
                    return score
            if attempt + 1 < self.SCORE_READ_RETRIES:
                self.next_frame()
                self.sleep(0.3)
        return None

    def find_start_match_button(self):
        box = self.box_of_screen(*self.MATCH_BUTTON_ROI, name="hide_seek_match")
        texts = self.ocr(box=box)
        for text in texts or []:
            if self.is_start_match_text(text.name):
                return text
        return None

    def wait_for_start_button(self, time_out=60):
        deadline = time.monotonic() + time_out
        while time.monotonic() < deadline:
            self.next_frame()
            if button := self.find_start_match_button():
                return button
            self.sleep(0.5)
        return None

    def wait_enter_match(self, retry_interval=10):
        """等待开始匹配按钮消失进入对局。

        按钮还在 = 页面仍可识别, 就一直点击重试, 永不判失败,
        直到按钮消失或用户手动停止任务。  # [lw]
        """
        click_count = 0
        last_click = 0.0
        while True:
            self.next_frame()
            if self.find_start_match_button() is None:
                return True
            now = time.monotonic()
            if click_count == 0 or now - last_click >= retry_interval:
                last_click = now
                click_count += 1
                self.operate_click(
                    self.find_start_match_button(),
                    action_name="hide_seek_start_match_retry",
                    interval=0,
                )
                self.log_warning(f"点击开始匹配后按钮仍在, 第 {click_count} 次重试点击")
            self.sleep(0.5)

    def wait_round_end(self, warn_interval=300):
        """等待对局结束回到匹配页。

        回不来也不中断任务, 只是隔 warn_interval 秒打一条警告,
        直到按钮重新出现或手动停止任务。"""
        next_warn = 0.0
        while True:
            self.next_frame()
            if self.find_start_match_button():
                return True
            now = time.monotonic()
            if now >= next_warn:
                next_warn = now + warn_interval
                self.log_warning("对局结束后仍未回到匹配页, 任务继续等待")
            self.sleep(self.PAGE_CHECK_INTERVAL)
