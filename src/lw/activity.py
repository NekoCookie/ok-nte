"""[lw] Screen-only Runaway Echoes warning detection and deterministic card selection."""

import math
import re
import time

import cv2
import numpy as np


GROUP = "活动配置"
ENABLE = "轨外回响辅助"
HOTKEY = "活动启动停止键"
PRIORITY = "选卡优先级"
FOOT_X = "活动脚底横坐标比例"
FOOT_Y = "活动脚底纵坐标比例"


def configure_activity(task):
    task.default_config.update({
        GROUP: False, ENABLE: False, HOTKEY: "5", PRIORITY: "",
        FOOT_X: 0.5, FOOT_Y: 0.565,
    })
    task.config_type[GROUP] = {
        "sub_configs": {True: [ENABLE, HOTKEY, PRIORITY, FOOT_X, FOOT_Y]},
    }
    task.config_description.update({
        GROUP: "展开活动独立配置, 不影响其他配置大项",
        ENABLE: "实验功能, 默认关闭; 受启用手动触发按键总开关控制, 复用方案输入方式",
        HOTKEY: "按一下启动, 再按一下停止; 支持5、mouse4、mouse5; 不要与其他宏重复",
        PRIORITY: "按优先顺序填写卡牌名称, 用英文逗号分隔; 空白或未匹配时等待手选, 不随机选卡",
        FOOT_X: "固定跟随镜头的角色脚底横坐标/画面宽度; 默认0.5, 镜头变化需重新校准",
        FOOT_Y: "固定跟随镜头的角色脚底纵坐标/画面高度; 默认0.565, 不是人物中心",
    })


def select_card(texts, priority):
    """Only exact normalized names/phrases; no fuzzy or random fallback."""
    def normalize(text):
        return re.sub(r"\s+", "", text)

    names = [normalize(s) for s in re.split(r"[,\uFF0C\n]", priority) if s.strip()]
    for name in names:
        if len(name) < 2:
            continue
        for index, text in enumerate(texts):
            if name in normalize(text):
                return index
    return None


def danger_mask(frame):
    """Work at 960x540, fill warning outlines and conservatively merge overlaps."""
    image = cv2.resize(frame[:, :, :3], (960, 540))
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    red = (((h < 9) | (h > 174)) & (s > 95) & (v > 110)).astype(np.uint8) * 255
    red[:100] = 0
    red[430:] = 0
    red[:, :80] = 0
    red[:, 820:] = 0
    mask = np.zeros_like(red)
    closed = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        # Reject thin health bars and small weapon glows. Merged warnings may be irregular.
        if area < 650 or height < 24 or width < 35:
            continue
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        if hull_area > 100000 or area / max(1, hull_area) < 0.20:
            continue
        cv2.drawContours(mask, [hull], -1, 255, cv2.FILLED)
    # Recover circular outer boundaries even when an overlapping strip breaks contours.
    circles = cv2.HoughCircles(
        cv2.GaussianBlur(red, (5, 5), 0), cv2.HOUGH_GRADIENT,
        dp=1, minDist=35, param1=80, param2=27, minRadius=25, maxRadius=150,
    )
    if circles is not None:
        angles = np.linspace(0, 2 * math.pi, 120, endpoint=False)
        for cx, cy, radius in circles[0]:
            xs = np.clip((cx + radius * np.cos(angles)).astype(int), 0, 959)
            ys = np.clip((cy + radius * np.sin(angles)).astype(int), 0, 539)
            if np.mean(closed[ys, xs] > 0) >= 0.55:
                cv2.circle(mask, (round(cx), round(cy)), round(radius), 255, -1)
    return cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (19, 19)))


DIRECTIONS = (
    (0, -1, ("w",)), (0, 1, ("s",)), (-1, 0, ("a",)), (1, 0, ("d",)),
    (-1, -1, ("w", "a")), (1, -1, ("w", "d")),
    (-1, 1, ("s", "a")), (1, 1, ("s", "d")),
)


def escape_keys(mask, foot, previous=()):
    x, y = foot
    if not (0 <= x < 960 and 0 <= y < 540) or not mask[y, x]:
        return ()
    candidates = []
    for dx, dy, keys in DIRECTIONS:
        length = math.hypot(dx, dy)
        safe_run = 0
        for distance in range(1, 241):
            px, py = round(x + dx / length * distance), round(y + dy / length * distance)
            if not (100 <= px < 800 and 110 <= py < 420):
                break
            safe_run = safe_run + 1 if mask[py, px] == 0 else 0
            if safe_run >= 22:
                candidates.append((distance + (0 if keys == previous else 8), keys))
                break
    return min(candidates, default=(0, ()))[1]


class ActivityController:
    """One bounded tick, no permanent held input and no shared executor frame mutation."""

    def __init__(self, task):
        self.task = task
        self.running = False
        self.armed_key = None
        self.was_down = False
        self.next_tick = 0.0
        self.card_latched = False
        self.card_missing = 0
        self.card_candidate = None
        self.previous = ()
        self.escape_started = None

    def stop(self):
        self.running = False
        self.previous = ()
        self.escape_started = None
        self.card_candidate = None
        self.card_latched = False
        self.card_missing = 0

    def available(self):
        task = self.task
        background = task.config.get(task.CONF_INPUT_MODE) == task.INPUT_BG
        return (task.enabled and task.config.get(ENABLE, False)
                and task._manual_key_triggers_enabled()
                and not task.executor.paused and not task.executor.exit_event.is_set()
                and (background or task.is_foreground())
                and task.executor.current_task in (None, task))

    def poll(self):
        task = self.task
        if not self.available():
            self.stop()
            self.armed_key = None
            return False
        key = str(task.config.get(HOTKEY, "5")).strip().lower()
        # Never use a movement key as a toggle, including shifted aliases.
        vk = task._get_vk_code(key)
        if vk is None or vk in [task._get_vk_code(k) for k in ("w", "a", "s", "d")]:
            self.stop()
            return False
        down = task._is_key_pressed(key)
        if key != self.armed_key:
            self.stop()
            self.armed_key, self.was_down = key, down
            return down
        edge = down and not self.was_down
        self.was_down = down
        if edge:
            if self.running:
                self.stop()
            else:
                self.running = True
            task.log_info("活动辅助: 启动" if self.running else "活动辅助: 停止")
            return True
        if not self.running:
            return down
        if time.monotonic() < self.next_tick:
            return True
        self.next_tick = time.monotonic() + 0.08
        try:
            self.tick()
        except Exception as error:
            self.stop()
            task.log_info(f"活动辅助异常, 已停止: {type(error).__name__}")
        return True

    def text(self, frame, rect):
        boxes = self.task.ocr(*rect, frame=frame, threshold=0.8)
        return " ".join(box.name for box in boxes)

    def tick(self):
        task = self.task
        captured_at = time.monotonic()
        frame = task.executor.method.get_frame()
        if frame is None:
            self.stop()
            return
        height, width = frame.shape[:2]
        if abs(width / height - 16 / 9) > 0.04:
            self.stop()
            task.log_info("活动辅助: 仅支持16:9画面")
            return
        # OCR happens while every movement key is already released.
        title = self.text(frame, (0.40, 0.12, 0.60, 0.19))
        if "选取卡牌" in re.sub(r"\s+", "", title):
            self.previous = ()
            self.escape_started = None
            self.card_missing = 0
            if self.card_latched:
                return
            texts = [self.text(frame, (left, 0.25, left + 0.19, 0.74))
                     for left in (0.18, 0.41, 0.635)]
            index = select_card(texts, str(task.config.get(PRIORITY, "")))
            candidate = (index, tuple(re.sub(r"\s+", "", text) for text in texts))
            if (index is not None and candidate == self.card_candidate and self.available()
                    and time.monotonic() - captured_at < 2):
                task.executor.interaction.click(
                    x=round(width * (0.275, 0.505, 0.73)[index]), y=round(height * 0.40),
                )
                self.card_latched = True
            self.card_candidate = candidate
            self.next_tick = time.monotonic() + 0.4
            return
        self.card_candidate = None
        # Require activity-specific HUD on this frame, not a cached scene assumption.
        hud = self.text(frame, (0.84, 0.24, 0.995, 0.34))
        if "轨外回响" not in re.sub(r"\s+", "", hud):
            self.previous = ()
            return
        self.card_missing += 1
        if self.card_missing >= 2:
            self.card_latched = False
        foot = (round(float(task.config.get(FOOT_X, 0.5)) * 960),
                round(float(task.config.get(FOOT_Y, 0.565)) * 540))
        if not (100 <= foot[0] < 800 and 110 <= foot[1] < 420):
            self.stop()
            task.log_info("活动辅助: 脚底坐标不在识别范围内, 请重新校准")
            return
        keys = escape_keys(danger_mask(frame), foot, self.previous)
        if time.monotonic() - captured_at > 0.5:
            self.previous = ()
            return
        self.previous = keys
        if not keys:
            self.escape_started = None
            return
        now = time.monotonic()
        if self.escape_started is None:
            self.escape_started = now
        if now - self.escape_started > 4:
            self.stop()
            task.log_info("活动辅助: 持续未脱离危险区, 已停止, 请检查位置或障碍")
            return
        self.pulse(keys)

    def pulse(self, keys):
        import win32api
        import win32con

        interaction = self.task.executor.interaction
        background = self.task.config.get(self.task.CONF_INPUT_MODE) == self.task.INPUT_BG
        held = []
        try:
            if self.task._is_key_pressed(self.armed_key) and not self.was_down:
                self.was_down = True
                self.stop()
                return
            for key in keys:
                if not self.available():
                    return
                held.append(key)
                if background:
                    interaction.send_key_down(key)
                else:
                    win32api.keybd_event(self.task._get_vk_code(key), 0, 0, 0)
            deadline = time.monotonic() + 0.08
            while time.monotonic() < deadline and self.available():
                if self.task._is_key_pressed(self.armed_key) and not self.was_down:
                    self.was_down = True
                    self.stop()
                    break
                time.sleep(0.01)
        finally:
            for key in reversed(held):
                try:
                    if background:
                        interaction.send_key_up(key)
                    else:
                        win32api.keybd_event(
                            self.task._get_vk_code(key), 0, win32con.KEYEVENTF_KEYUP, 0,
                        )
                except Exception as error:
                    self.stop()
                    self.task.log_info(f"活动移动松键失败: {type(error).__name__}")
