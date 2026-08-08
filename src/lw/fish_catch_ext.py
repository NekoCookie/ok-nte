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
    CATCH_RESULT_CLOSE_TEXT_ROI = (0.25, 0.78, 0.75, 0.94)
    CATCH_BAG_FULL_TEXT_ROI = (0.10, 0.25, 0.90, 0.60)
    CATCH_FISH_INVENTORY_ICON_ROI = (0.65, 0.80, 0.72, 0.95)
    FISH_SKILL_ROIS = {
        "q": (0.025, 0.80, 0.105, 0.96),
        "w": (0.105, 0.80, 0.185, 0.96),
        "e": (0.185, 0.80, 0.305, 0.96),
    }
    FISH_SKILL_ORDER = ("e", "w", "q")
    FISH_SKILL_COOLDOWNS = {"e": 10.0, "w": 5.0, "q": 1.5}
    START_TEXT_RE = re.compile(r"开始\s*[捕捉抓]鱼|start\s*(?:catch|fishing)", re.IGNORECASE)
    CATCH_RESULT_CLOSE_TEXT_RE = re.compile(r"点\s*击\s*空\s*白\s*区\s*域\s*关\s*闭")
    CATCH_BAG_FULL_TEXT_RE = re.compile(r"背包没有足够的空间[,，]?请先清理背包")
    TIMER_RE = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")

    FISH_HSV_SATURATION = 130
    FISH_HSV_VALUE = 210
    FISH_NEUTRAL_VALUE = 245
    FISH_MIN_AREA = 80
    FISH_MAX_WIDTH = 240
    FISH_MAX_HEIGHT = 110
    FISH_DETECT_CLOSE_KERNEL = 7
    FISH_ROUND_TIMEOUT = 70
    FISH_UI_CHECK_INTERVAL = 0.5
    FISH_SKILL_CHECK_INTERVAL = 0.2
    FISH_TIMER_MISSING_TIMEOUT = 2.0
    FISH_START_CONFIRM_SECONDS = 1.0
    CATCH_START_WAIT_SECONDS = 20.0
    CATCH_START_RETRY_LIMIT = 3
    CATCH_RESULT_CLOSE_ATTEMPTS = 5
    CATCH_RESULT_CLOSE_RETRY_DELAY = 0.4
    CATCH_RESULT_CLOSE_FALLBACK_POS = (0.503, 0.887)
    # The catch preparation panel has no keyboard shortcut for the fish
    # inventory.  Its fish icon is immediately left of the start button.  # [lw]
    CATCH_FISH_INVENTORY_BUTTON_POS = (0.681, 0.870)
    BLIND_CLICK_POSITION = (0.490, 0.404)

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
        icon = self.box_of_screen(
            *self.CATCH_FISH_INVENTORY_ICON_ROI,
            name="fish_catch_inventory_icon",
        )
        icon_image = icon.crop_frame(self.frame)
        if icon_image is None or icon_image.size == 0:
            return None
        icon_gray = cv2.cvtColor(icon_image, cv2.COLOR_BGR2GRAY)
        if float(np.mean(icon_gray < 100)) < 0.55:
            return None

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

    def has_catch_bag_full(self) -> bool:
        box = self.box_of_screen(*self.CATCH_BAG_FULL_TEXT_ROI, name="fish_catch_bag_full")
        texts = self.ocr(box=box)
        if not texts:
            return False
        texts = sorted(texts, key=lambda text: (text.y, text.x))
        normalized = "".join(re.sub(r"\s+", "", text.name or "") for text in texts)
        if self.CATCH_BAG_FULL_TEXT_RE.search(normalized):
            return True
        # OCR may drop punctuation or one character in the long banner.  The
        # four stable keywords still distinguish it from ordinary UI text.  # [lw]
        return all(keyword in normalized for keyword in ("背包", "足够", "空间", "清理"))

    def has_catch_result(self) -> bool:
        """Detect the fish-reward overlay shown after a round finishes.  # [lw]"""
        return bool(
            self.find_one(Labels.fish_sucess)
            or self.find_one(Labels.reward_popup)
            or self.find_catch_result_close_prompt()
        )

    def find_catch_result_close_prompt(self):
        box = self.box_of_screen(*self.CATCH_RESULT_CLOSE_TEXT_ROI, name="fish_catch_result_close")
        texts = self.ocr(box=box)
        if not texts:
            return None
        texts = sorted(texts, key=lambda text: (text.y, text.x))
        for text in texts:
            normalized = re.sub(r"\s+", "", text.name or "")
            if self.CATCH_RESULT_CLOSE_TEXT_RE.search(normalized):
                return text
        normalized_all = "".join(re.sub(r"\s+", "", text.name or "") for text in texts)
        if not self.CATCH_RESULT_CLOSE_TEXT_RE.search(normalized_all):
            return None
        x1 = min(text.x for text in texts)
        y1 = min(text.y for text in texts)
        x2 = max(text.x + text.width for text in texts)
        y2 = max(text.y + text.height for text in texts)
        return Box(x1, y1, x2 - x1, y2 - y1, name="fish_catch_close_prompt")

    def read_fish_skill_cooldown(self, key: str) -> float:
        """Read one fishing skill countdown, reusing the combat CD OCR pipeline.  # [lw]"""
        key = key.lower()
        if key not in self.FISH_SKILL_ROIS:
            return 0.0

        local_value = self.local_fish_skill_cooldown(key)
        if local_value is None:
            # A new fishing round starts with all three actions available.  Do
            # not let background digits in the icon artwork block the first
            # E -> W -> Q pass.  # [lw]
            return 0.0
        if local_value > 0.1:
            return local_value

        ocr_value = None
        try:
            from src.combat.BaseCombatTask import cd_regex, convert_cd
            from src.utils import game_filters as gf

            box = self.box_of_screen(*self.FISH_SKILL_ROIS[key], name=f"fish_skill_{key}")
            texts = self.ocr(
                box=box,
                frame_processor=gf.isolate_cd_to_black,
                match=cd_regex,
            )
            values = []
            for text in texts or []:
                value = convert_cd(text)
                if 0 <= value <= self.FISH_SKILL_COOLDOWNS[key] + 2:
                    values.append(value)
            if values:
                ocr_value = min(values)
        except Exception as exc:
            self.log_debug(f"捕鱼技能 {key} CD OCR failed: {exc}")

        if ocr_value is None:
            return local_value
        return max(ocr_value, local_value)

    def local_fish_skill_cooldown(self, key: str) -> float | None:
        """Return the local cooldown estimate, or None before the first cast."""
        last_cast = getattr(self, "_fish_skill_last_cast", {}).get(key)
        if last_cast is None:
            return None
        return max(0.0, self.FISH_SKILL_COOLDOWNS[key] - (time.monotonic() - last_cast))

    def next_fish_skill(self) -> str | None:
        """Return the next ready key while preserving E -> W -> Q order.  # [lw]"""
        cooldowns = {
            key: self.read_fish_skill_cooldown(key)
            for key in self.FISH_SKILL_ORDER
            if self.local_fish_skill_cooldown(key) is None
            or self.local_fish_skill_cooldown(key) <= 0.1
        }
        for key in self.FISH_SKILL_ORDER:
            if cooldowns[key] <= 0.1:
                self.log_debug(f"捕鱼技能优先级选择 {key}, CD={cooldowns[key]:.1f}s")
                return key
        return None

    def cast_fish_skill(self, key: str) -> bool:
        """Select a fishing skill and release it at the configured catch point.  # [lw]"""
        self.send_key(key, down_time=0.03, action_name=f"fish_catch_select_{key}", interval=0.15)
        self.sleep(0.05)
        result = self.operate_click(
            *self.BLIND_CLICK_POSITION,
            down_time=0.01,
            action_name="fish_catch_target",
        )
        succeeded = result is not False
        if succeeded:
            if not hasattr(self, "_fish_skill_last_cast"):
                self._fish_skill_last_cast = {}
            self._fish_skill_last_cast[key] = time.monotonic()
        return succeeded

    def close_catch_result(self) -> bool:
        """Close the reward overlay through its documented blank-area action.  # [lw]"""
        if not self.has_catch_result():
            return False
        self.log_info("检测到捕鱼结算界面, 点击空白区域关闭")
        for attempt in range(self.CATCH_RESULT_CLOSE_ATTEMPTS):
            if attempt > 0 and not self.has_catch_result():
                break
            prompt = self.find_catch_result_close_prompt()
            if prompt is not None and attempt % 2 == 0:
                self.operate_click(prompt, action_name="close_fish_catch_result", interval=0)
            else:
                self.operate_click(
                    *self.CATCH_RESULT_CLOSE_FALLBACK_POS,
                    action_name="close_fish_catch_result_fallback",
                    interval=0,
                )
            if self.wait_until(
                lambda: not self.has_catch_result(),
                time_out=2,
                settle_time=0.15,
                raise_if_not_found=False,
            ):
                break
            self.sleep(self.CATCH_RESULT_CLOSE_RETRY_DELAY)
        return True

    def wait_for_catch_start(self, time_out: float | None = None):
        """Retry known transition states before declaring the round unrecoverable.  # [lw]"""
        deadline = time.monotonic() + float(time_out or self.CATCH_START_WAIT_SECONDS)
        while time.monotonic() < deadline:
            self.next_frame()
            if self.has_catch_result():
                self.close_catch_result()
                continue
            if button := self.find_catch_start_button():
                return button
            self.sleep(0.4)
        return None

    def sell_catch_fish(self) -> bool:
        """Sell the catch using the same fish-hold flow as automatic fishing.  # [lw]"""
        fish_sell = self.wait_until(
            lambda: self.find_one(Labels.fish_sell),
            pre_action=lambda: self.operate_click(
                *self.CATCH_FISH_INVENTORY_BUTTON_POS,
                interval=2,
                action_name="fish_catch_open_sell",
            ),
            time_out=10,
            settle_time=0.5,
            raise_if_not_found=False,
        )
        if not fish_sell:
            self.log_warning("未进入鱼获出售界面")
            return False

        fish_hold = self.wait_until(
            lambda: self.find_one(Labels.fish_hold),
            pre_action=lambda: self.operate_click(0.076, 0.386, interval=2),
            time_out=10,
            settle_time=0.5,
            raise_if_not_found=False,
        )
        if not fish_hold:
            self.log_warning("未进入鱼舱界面")
            return False

        if not self.find_one(Labels.fish_one_click_sell):
            self.log_info("鱼舱内没有可出售鱼获")
            return True
        sold = self.wait_click_confirm(
            lambda: self.operate_click(0.556, 0.898, interval=2),
            raise_if_not_found=False,
        )
        if not sold:
            self.log_warning("一键出售未完成")
        return bool(sold)

    def handle_catch_bag_full(self) -> bool:
        """Leave the minigame, sell fish, then return to its start screen.  # [lw]"""
        self.log_warning("捕鱼检测到背包空间不足, 退出并清理鱼获")
        self.send_key("esc", action_name="fish_catch_bag_full_escape", interval=0)
        if not self.wait_for_catch_start(time_out=15):
            self.log_warning("背包满后未回到开始捕鱼界面")
            return False

        sold = self.sell_catch_fish()
        self.send_key("esc", action_name="fish_catch_close_sell", interval=0)
        returned = self.wait_for_catch_start(time_out=20) is not None
        if not returned:
            self.log_warning("清理鱼获后未回到开始捕鱼界面")
        return sold and returned

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
        next_skill_check = 0.0
        started = False
        timer_missing_since = None
        start_button_since = None
        self._fish_skill_last_cast = {}

        while time.monotonic() < deadline:
            self.next_frame()
            now = time.monotonic()

            if now >= next_ui_check:
                next_ui_check = now + self.FISH_UI_CHECK_INTERVAL
                if self.has_catch_bag_full():
                    if self.handle_catch_bag_full():
                        return True
                    self.log_warning("捕鱼清理鱼获失败, 停止本轮并等待人工处理")
                    return False
                if self.has_catch_result():
                    self.close_catch_result()
                    return True
                timer = self.read_catch_timer()
                if timer is not None:
                    started = True
                    timer_missing_since = None
                    start_button_since = None
                elif started:
                    timer_missing_since = timer_missing_since or now
                    if now - timer_missing_since >= self.FISH_TIMER_MISSING_TIMEOUT:
                        if self.find_catch_start_button():
                            start_button_since = start_button_since or now
                            if now - start_button_since >= self.FISH_START_CONFIRM_SECONDS:
                                self.log_info("捕鱼场景结束")
                                return True
                        else:
                            start_button_since = None

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

            if now < next_skill_check:
                self.sleep(min(0.1, next_skill_check - now))
                continue
            next_skill_check = now + self.FISH_SKILL_CHECK_INTERVAL
            skill = self.next_fish_skill()
            if skill is None:
                self.sleep(0.1)
                continue
            self.cast_fish_skill(skill)

        self.log_warning(f"捕鱼场景超过 {timeout:.0f} 秒, 结束本轮")
        return True
