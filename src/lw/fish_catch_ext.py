"""LW fish-catching workflow and vision helpers.  # [lw]"""

import re
import time

import cv2
import numpy as np
from ok import Box, WaitFailedException

from src.Labels import Labels


class FishCatchingTaskMixin:
    """捕鱼小游戏的独立流程, 不改动 RU 自动钓鱼任务.  # [lw]"""

    CATCH_ROI = (0.20, 0.11, 0.81, 0.66)
    START_BUTTON_ROI = (0.68, 0.80, 0.99, 0.97)
    START_BUTTON_VISUAL_ROI = (0.72, 0.84, 0.98, 0.93)
    TIMER_ROI = (0.40, 0.025, 0.60, 0.105)
    START_TEXT_RE = re.compile(r"开始\s*[捕捉抓]鱼|start\s*(?:catch|fishing)", re.IGNORECASE)
    TIMER_RE = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")

    FISH_HSV_SATURATION = 130
    FISH_HSV_VALUE = 210
    FISH_NEUTRAL_VALUE = 245
    FISH_MIN_AREA = 80
    FISH_MAX_WIDTH = 240
    FISH_MAX_HEIGHT = 110
    FISH_DETECT_CLOSE_KERNEL = 7
    FISH_CLICK_INTERVAL = 0.5
    FISH_ROUND_TIMEOUT = 70
    FISH_UI_CHECK_INTERVAL = 0.5
    FISH_TIMER_MISSING_TIMEOUT = 2.0
    CATCH_RESULT_CLOSE_POS = (0.50, 0.90)
    BLIND_CLICK_POINTS = (
        (0.392, 0.323),
        (0.370, 0.290),
        (0.415, 0.290),
        (0.370, 0.350),
        (0.415, 0.350),
        (0.392, 0.275),
        (0.392, 0.370),
        (0.358, 0.323),
        (0.426, 0.323),
    )

    @staticmethod
    def detect_fish_components(image: np.ndarray | None) -> list[tuple[int, int, int, int]]:
        """Return neon fish component boxes as ``(x, y, width, height)``.

        The fishing scene renders fish as bright, highly saturated outlines.  A
        small morphological close joins the outline fragments while geometry
        and fill filters reject water highlights and UI noise.
        """
        if image is None or image.size == 0:
            return []
        if image.ndim != 3 or image.shape[2] != 3:
            return []

        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        saturation_mask = (hsv[:, :, 1] >= FishCatchingTaskMixin.FISH_HSV_SATURATION) & (
            hsv[:, :, 2] >= FishCatchingTaskMixin.FISH_HSV_VALUE
        )
        neutral_highlight_mask = hsv[:, :, 2] >= FishCatchingTaskMixin.FISH_NEUTRAL_VALUE
        mask = np.where(saturation_mask | neutral_highlight_mask, 255, 0).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8))
        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_CLOSE,
            np.ones(
                (
                    FishCatchingTaskMixin.FISH_DETECT_CLOSE_KERNEL,
                    FishCatchingTaskMixin.FISH_DETECT_CLOSE_KERNEL,
                ),
                dtype=np.uint8,
            ),
        )

        _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        candidates: list[tuple[int, int, int, int, int]] = []
        for x, y, width, height, area in stats[1:]:
            x, y, width, height, area = map(int, (x, y, width, height, area))
            if area < FishCatchingTaskMixin.FISH_MIN_AREA:
                continue
            if not (10 <= width <= FishCatchingTaskMixin.FISH_MAX_WIDTH):
                continue
            if not (8 <= height <= FishCatchingTaskMixin.FISH_MAX_HEIGHT):
                continue
            aspect = width / max(1, height)
            if not (0.2 <= aspect <= 10):
                continue
            fill = area / max(1, width * height)
            if fill >= 0.9:
                continue
            candidates.append((x, y, width, height, area))

        # A single fish can still produce two nearby components.  Keep the
        # larger component when their centers and extents substantially overlap.
        candidates.sort(key=lambda item: item[4], reverse=True)
        result: list[tuple[int, int, int, int]] = []
        for x, y, width, height, _ in candidates:
            center_x = x + width / 2
            center_y = y + height / 2
            duplicate = False
            for old_x, old_y, old_width, old_height in result:
                old_center_x = old_x + old_width / 2
                old_center_y = old_y + old_height / 2
                near_x = abs(center_x - old_center_x) <= max(width, old_width) * 0.45
                near_y = abs(center_y - old_center_y) <= max(height, old_height) * 0.65
                if near_x and near_y:
                    duplicate = True
                    break
            if not duplicate:
                result.append((x, y, width, height))
        return result

    def detect_fish_targets(self) -> list[Box]:
        roi = self.box_of_screen(*self.CATCH_ROI, name="fish_catch_roi")
        image = roi.crop_frame(self.frame)
        targets = []
        for x, y, width, height in self.detect_fish_components(image):
            target = Box(
                roi.x + x,
                roi.y + y,
                width,
                height,
                name="fish_target",
            )
            targets.append(target)
        if targets:
            self.draw_boxes(boxes=targets, color="yellow")
        return targets

    def find_catch_start_button(self):
        box = self.box_of_screen(*self.START_BUTTON_ROI, name="fish_catch_start")
        texts = self.ocr(box=box, match=self.START_TEXT_RE)
        if texts:
            return texts[0]
        return self.find_one(Labels.fish_start, box=box) or self.find_catch_start_button_visual()

    def find_catch_start_button_visual(self):
        """Fallback for the light start button when OCR misses its text."""
        button = self.box_of_screen(*self.START_BUTTON_VISUAL_ROI, name="fish_catch_start_visual")
        image = button.crop_frame(self.frame)
        if image is None or image.size == 0:
            return None
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if float(np.mean(gray >= 210)) >= 0.25:
            return button
        return None

    def read_catch_timer(self) -> int | None:
        box = self.box_of_screen(*self.TIMER_ROI, name="fish_catch_timer")
        texts = self.ocr(box=box, match=self.TIMER_RE)
        for text in texts or []:
            match = self.TIMER_RE.search(text.name or "")
            if match:
                value = int(match.group(1))
                if 0 <= value <= 99:
                    return value
        return None

    def has_catch_result(self) -> bool:
        """Detect the fish-reward overlay shown after a round finishes.  # [lw]"""
        return bool(self.find_one(Labels.fish_sucess) or self.find_one(Labels.reward_popup))

    def fish_click_interval(self) -> float:
        """Read the configured interval with a conservative lower bound.  # [lw]"""
        key = getattr(self, "CONF_CLICK_INTERVAL", "捕鱼点击间隔")
        try:
            value = float(self.config.get(key, self.FISH_CLICK_INTERVAL))
        except (AttributeError, TypeError, ValueError):
            value = self.FISH_CLICK_INTERVAL
        return max(0.05, value)

    def next_blind_click_position(self) -> tuple[float, float]:
        index = getattr(self, "_blind_click_index", 0)
        position = self.BLIND_CLICK_POINTS[index % len(self.BLIND_CLICK_POINTS)]
        self._blind_click_index = index + 1
        return position

    def close_catch_result(self) -> bool:
        """Close the reward overlay through its documented blank-area action.  # [lw]"""
        if not self.has_catch_result():
            return False
        self.log_info("检测到捕鱼结算界面, 点击空白区域关闭")
        self.operate_click(
            *self.CATCH_RESULT_CLOSE_POS,
            action_name="close_fish_catch_result",
            interval=1,
        )
        self.wait_until(
            lambda: not self.has_catch_result(),
            time_out=8,
            settle_time=0.2,
            raise_if_not_found=False,
        )
        return True

    def ensure_catch_prepare(self):
        if self.has_catch_result():
            self.close_catch_result()
        if self.find_catch_start_button():
            return True
        self.enter_catch_from_interaction()
        self.wait_until(
            self.find_catch_start_button,
            time_out=15,
            settle_time=0.5,
            raise_if_not_found=True,
        )
        return True

    def enter_catch_from_interaction(self):
        self.log_info("寻找捕鱼交互点")
        self.wait_until(self.find_interac, time_out=10, raise_if_not_found=True)
        confirm_box = self.box_of_screen(0.927, 0.827, 0.975, 0.912)
        button = self.wait_until(
            lambda: self.find_confirm(box=confirm_box),
            time_out=10,
            pre_action=lambda: self.send_key("f", interval=2, action_name="fish_catch_interact"),
            settle_time=0.5,
            raise_if_not_found=True,
        )

        def click_extra_confirm():
            extra_box = self.box_of_screen(0.656, 0.618, 0.700, 0.699)
            extra = self.find_confirm(box=extra_box)
            if extra:
                self.operate_click(extra, action_name="fish_catch_extra_confirm", interval=2)

        self.wait_until(
            self.find_catch_start_button,
            time_out=30,
            pre_action=lambda: self.operate_click(button, action_name="fish_catch_confirm", interval=2),
            post_action=click_extra_confirm,
            settle_time=0.5,
            raise_if_not_found=True,
        )

    def click_catch_start(self):
        button = self.find_catch_start_button()
        if button is None:
            self.log_error("未检测到开始捕鱼按钮")
            raise WaitFailedException()
        self.operate_click(button, action_name="start_fish_catch", interval=1)
        self.log_info("已点击开始捕鱼")

    def run_fish_catch_round(self, timeout: float | None = None):
        timeout = float(timeout or self.FISH_ROUND_TIMEOUT)
        deadline = time.monotonic() + timeout
        load_deadline = time.monotonic() + min(timeout, 10.0)
        next_ui_check = 0.0
        timer_missing_since = None
        started = False
        click_interval = self.fish_click_interval()
        self._blind_click_index = 0

        while time.monotonic() < deadline:
            self.next_frame()
            now = time.monotonic()

            if now >= next_ui_check:
                next_ui_check = now + self.FISH_UI_CHECK_INTERVAL
                if self.has_catch_result():
                    self.close_catch_result()
                    return True
                timer = self.read_catch_timer()
                if timer is not None:
                    started = True
                    timer_missing_since = None
                elif started and self.find_catch_start_button():
                    self.log_info("捕鱼场景结束")
                    return True
                elif started:
                    timer_missing_since = timer_missing_since or now
                    if now - timer_missing_since >= self.FISH_TIMER_MISSING_TIMEOUT:
                        self.log_warning("捕鱼计时器消失, 关闭结算并结束本轮")
                        self.operate_click(
                            *self.CATCH_RESULT_CLOSE_POS,
                            action_name="close_fish_catch_result_fallback",
                            interval=1,
                        )
                        return True

            if not started:
                timer = self.read_catch_timer()
                if timer is not None:
                    started = True
                elif now < load_deadline:
                    self.sleep(0.1)
                    continue
                else:
                    self.log_warning("点击开始捕鱼后等待场景加载超时")
                    return False

            self.operate_click(
                *self.next_blind_click_position(),
                down_time=0.01,
                action_name="fish_catch_target",
            )
            self.sleep(click_interval)

        self.log_warning(f"捕鱼场景超过 {timeout:.0f} 秒, 结束本轮")
        return True
