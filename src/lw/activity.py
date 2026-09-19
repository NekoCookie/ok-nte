"""[lw] Screen-only Runaway Echoes warning detection and deterministic card selection."""

import math
import random
import re
import sys
import time

import cv2
import numpy as np


GROUP = "活动配置"
ENABLE = "轨外回响辅助"
HOTKEY = "活动启动停止键"
PRIORITY = "选卡优先级"
FOOT_X = "活动脚底横坐标比例"
FOOT_Y = "活动脚底纵坐标比例"
MOVE_SECONDS = "活动单次移动时长(s)"
def movement_seconds(config):
    try:
        value = float(config.get(MOVE_SECONDS, 0.2))
    except (TypeError, ValueError):
        return 0.2
    return min(1.0, max(0.05, value)) if math.isfinite(value) else 0.2


def activity_key_pressed(task, key):
    if key == "-":
        import win32api

        return any(win32api.GetAsyncKeyState(vk) & 0x8000 for vk in (0xBD, 0x6D))
    return task._is_key_pressed(key)


def configure_activity(task):
    task.default_config.update({
        GROUP: False, ENABLE: False, HOTKEY: "5", PRIORITY: "",
        FOOT_X: 0.5, FOOT_Y: 0.565, MOVE_SECONDS: 0.2,
    })
    task.config_type[GROUP] = {
        "sub_configs": {True: [ENABLE, HOTKEY, MOVE_SECONDS,
                               PRIORITY, FOOT_X, FOOT_Y]},
    }
    task.config_description.update({
        GROUP: "展开活动独立配置, 不影响其他配置大项",
        ENABLE: "实验功能, 默认关闭; 独立控制活动热键, 不受手动触发总开关影响; 复用方案输入方式",
        HOTKEY: "按一下启动, 再按一下停止; 支持5、mouse4、mouse5; 不要与其他宏重复",
        PRIORITY: "任意界面按文字从左到右优先点击, 支持/、逗号和换行; 如无尽挑战/开始挑战; 同一文字持续出现最多每2秒点击一次",
        FOOT_X: "角色脚底横坐标/画面宽度, 默认0.5; 不是地图中心; 镜头变化需校准",
        FOOT_Y: "角色脚底纵坐标/画面高度, 默认0.565; 不是地图中心或人物身体中心",
        MOVE_SECONDS: "每次移动按住多久, 默认0.2秒; 范围0.05~1.0秒; 越长位移越大但重新识别越慢; 可随时按热键停止",
    })


def select_card(texts, priority):
    """Only exact normalized names/phrases; no fuzzy or random fallback."""
    def normalize(text):
        return re.sub(r"\s+", "", text)

    names = [normalize(s) for s in re.split(r"[/,\uFF0C\n]", priority) if s.strip()]
    for name in names:
        if len(name) < 2:
            continue
        for index, text in enumerate(texts):
            if name in normalize(text):
                return index
    return None




def boss_warning_mask(frame):
    """Require a large, supported ellipse outline, not merged danger area/depth."""
    image = cv2.resize(frame[:, :, :3], (960, 540))
    h, s, v = cv2.split(cv2.cvtColor(image, cv2.COLOR_BGR2HSV))
    red = (((h < 10) | (h > 174)) & (s > 65) & (v > 100)).astype(np.uint8) * 255
    red[:95] = 0
    red[435:] = 0
    contours, _ = cv2.findContours(red, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    result = np.zeros_like(red)
    supported = cv2.dilate(red, np.ones((7, 7), np.uint8))
    for contour in contours:
        if len(contour) < 250:
            continue
        ellipse = cv2.fitEllipse(contour)
        small, large = sorted(ellipse[1])
        if not (260 <= small <= large <= 650 and small / large >= .60):
            continue
        edge = np.zeros_like(red)
        cv2.ellipse(edge, ellipse, 255, 2)
        pixels = edge > 0
        if np.count_nonzero(pixels) and np.mean(supported[pixels] > 0) >= .60:
            cv2.ellipse(result, ellipse, 255, -1)
    return result




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


def escape_keys(mask, foot, previous=(), drift=(0.0, 0.0), dodge_drift=(0, 0)):
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
                candidates.append((distance, keys, (dx / length, dy / length)))
                break
    if not candidates:
        return ()
    shortest = min(item[0] for item in candidates)
    # Safety first: only bias comparably short exits toward the starting position.
    near = [item for item in candidates if item[0] <= shortest + 12]
    # Independently normalize time and counts; neither unit overwhelms the other.
    biases = [tuple(value / max(1.0, math.hypot(*vector)) for value in vector)
              for vector in (drift, dodge_drift)]
    return min(near, key=lambda item: (
        item[0] + (0 if item[1] == previous else 4)
        + 8 * sum(vector[0] * item[2][0] + vector[1] * item[2][1]
                  for vector in biases)
    ))[1]


class ActivityController:
    """One bounded tick, no permanent held input and no shared executor frame mutation."""

    def __init__(self, task):
        self.task = task
        self.running = False
        self.armed_key = None
        self.was_down = False
        self.next_tick = 0.0
        self.previous = ()
        self.status = ""
        self.last_status_log = 0.0
        self.last_scene_seen = float("-inf")
        self.safe_frames = 0
        self.direction_seconds = dict.fromkeys(("w", "a", "s", "d"), 0.0)
        self.drift = [0.0, 0.0]
        self.next_motion_summary = 0.0
        self.dodge_count = 0
        self.direction_dodges = dict.fromkeys(("w", "a", "s", "d"), 0)
        self.next_dodge = 0.0
        self.next_text_scan = 0.0
        self.next_text_click = 0.0
        self.text_waiting = False
        self.unmatched_cards_since = None
        self.observed_pause = False

    def install_pause_diagnostics(self):
        """Observe framework events synchronously to retain the caller, without patching it."""
        from ok.gui.Communicate import communicate
        from PySide6.QtCore import Qt

        def on_pause(paused):
            if not self.task.config.get(ENABLE, False):
                return
            frame = sys._getframe(1)
            callers = []
            for _ in range(5):
                if frame is None:
                    break
                callers.append(f"{frame.f_globals.get('__name__', '')}.{frame.f_code.co_name}")
                frame = frame.f_back
            self.task.log_info(
                f"活动执行器状态: {'暂停' if paused else '恢复'}, 来源={' <- '.join(callers)}"
            )

        communicate.executor_paused.connect(on_pause, Qt.ConnectionType.DirectConnection)
        self._pause_observer = on_pause

    def report(self, message, notify=False):
        """Expose state without logging OCR contents or flooding the log."""
        changed = message != self.status
        self.status = message
        if changed:
            self.task.info_set("活动状态", message)
        now = time.monotonic()
        if notify or (changed and now - self.last_status_log >= 2):
            self.task.log_info(f"活动辅助: {message}", notify=notify)
            self.last_status_log = now

    def stop(self, reason="已停止"):
        was_running = self.running
        self.running = False
        self.previous = ()
        self.last_scene_seen = float("-inf")
        self.safe_frames = 0
        self.next_text_scan = 0.0
        self.next_text_click = 0.0
        self.text_waiting = False
        self.unmatched_cards_since = None
        if was_running:
            self.report(reason, notify=True)

    def blocked_reason(self):
        task = self.task
        if task.executor.paused:
            return "程序已暂停"
        if task.executor.exit_event.is_set():
            return "程序正在退出"
        background = task.config.get(task.CONF_INPUT_MODE) == task.INPUT_BG
        if not background and not task.is_foreground():
            return "前台输入模式需要游戏位于前台"
        if task.executor.current_task not in (None, task):
            return "等待其他任务释放输入"
        return ""

    def available(self):
        task = self.task
        return (task.enabled and task.config.get(ENABLE, False)
                and not self.blocked_reason())

    def poll(self):
        task = self.task
        if not task.enabled or not task.config.get(ENABLE, False):
            self.stop("活动开关或任务已关闭")
            self.armed_key = None
            return False
        key = str(task.config.get(HOTKEY, "5")).strip().lower()
        # Never use a movement key as a toggle, including shifted aliases.
        vk = task._get_vk_code(key)
        if vk is None or vk in [task._get_vk_code(k) for k in ("w", "a", "s", "d")]:
            self.stop("启动键无效或与移动键冲突")
            if self.status != "启动键无效或与移动键冲突":
                self.report("启动键无效或与移动键冲突", notify=True)
            return False
        down = activity_key_pressed(task, key)
        if key != self.armed_key:
            self.stop()
            self.armed_key, self.was_down = key, down
            self.report(f"热键监听已就绪: {key}, 松开后按一次启动", notify=True)
            return down
        edge = down and not self.was_down
        self.was_down = down
        if edge:
            if self.running:
                self.stop()
            else:
                self.running = True
                self.direction_seconds = dict.fromkeys(("w", "a", "s", "d"), 0.0)
                self.drift = [0.0, 0.0]
                self.dodge_count = 0
                self.direction_dodges = dict.fromkeys(("w", "a", "s", "d"), 0)
                self.next_dodge = 0.0
                self.next_tick = 0.0
                self.report("已启用, 程序总暂停中, 请先恢复程序运行"
                            if task.executor.paused else "已启动, 等待识别活动画面", notify=True)
                self.observed_pause = bool(task.executor.paused)
            return True
        if not self.running:
            return down
        paused = bool(task.executor.paused)
        if paused != self.observed_pause:
            self.observed_pause = paused
            self.last_scene_seen = float("-inf")
            self.unmatched_cards_since = None
            self.next_text_scan = 0.0
            self.report("程序总暂停, 活动等待恢复" if paused
                        else "程序已恢复, 活动重新识别画面", notify=True)
        return True

    def process(self):
        """Run only from the framework executor; poll remains input-free and responsive."""
        if not self.running:
            return
        reason = self.blocked_reason()
        if reason:
            # A trigger task may occupy current_task for only one scheduler iteration.
            # Keep the toggle latched, but never send competing input.
            self.report(reason)
            return True
        if time.monotonic() < self.next_tick:
            return True
        self.next_tick = time.monotonic() + 0.03
        try:
            self.tick()
        except Exception as error:
            from ok.task.exceptions import CaptureException

            if isinstance(error, CaptureException):
                self.last_scene_seen = float("-inf")
                self.unmatched_cards_since = None
                self.next_tick = time.monotonic() + 0.5
                self.report("截图异常, 暂停输入并等待恢复")
            else:
                self.stop(f"异常停止: {type(error).__name__}")
        return True

    def text(self, frame, rect, threshold=0.8):
        boxes = self.task.ocr(*rect, frame=frame, threshold=threshold)
        return " ".join(box.name for box in boxes)

    def click_configured_text(self, frame):
        """One OCR rule on any page; click actual detected text, not fixed card slots."""
        priority = str(self.task.config.get(PRIORITY, ""))
        now = time.monotonic()
        if now < self.next_text_scan:
            return False
        self.next_text_scan = now + 0.4
        boxes = self.task.ocr(frame=frame, threshold=.8)
        card_page = any(
            "选取卡牌" in re.sub(r"\s+", "", box.name)
            and box.y < frame.shape[0] * .25 for box in boxes
        )
        if not card_page:
            self.unmatched_cards_since = None
        scale = 1
        index = select_card([box.name for box in boxes], priority)
        if index is None and "定时" in priority:
            # Generic scaled OCR, no card-specific coordinates or image templates.
            scaled = cv2.resize(frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            boxes = self.task.ocr(frame=scaled, threshold=.8)
            index = select_card([box.name for box in boxes], priority)
            scale = 2
        self.text_waiting = index is not None
        if index is None:
            if card_page:
                if self.unmatched_cards_since is None:
                    self.unmatched_cards_since = now
                if (now - self.unmatched_cards_since >= 10 and now >= self.next_text_click
                        and self.running and self.available() and time.monotonic() - now < 2):
                    x = random.choice((.275, .505, .73)) * frame.shape[1]
                    result = self.task.executor.interaction.click(
                        x=round(x), y=round(frame.shape[0] * .40), move_back=True,
                    )
                    self.next_text_click = time.monotonic() + 2
                    if result is not False:
                        self.unmatched_cards_since = None
                        self.report("选卡10秒未匹配, 已随机选择一张")
                        return True
            return False
        self.unmatched_cards_since = None
        if now < self.next_text_click:
            return False
        box = boxes[index]
        matched = next(word.strip() for word in re.split(r"[/,\uFF0C\n]", priority)
                       if len(re.sub(r"\s+", "", word)) >= 2
                       and re.sub(r"\s+", "", word) in re.sub(r"\s+", "", box.name))
        x, y = (box.x + box.width / 2) / scale, (box.y + box.height / 2) / scale
        if (not self.running or not self.available()
                or time.monotonic() - now > 2
                or not (0 <= x < frame.shape[1] and 0 <= y < frame.shape[0])):
            return False
        result = self.task.executor.interaction.click(x=round(x), y=round(y), move_back=True)
        self.next_text_click = time.monotonic() + (2 if result is not False else .5)
        self.report(f"已点击配置词: {matched}" if result is not False
                    else f"配置词点击被拦截: {matched}")
        return result is not False

    def tick(self):
        task = self.task
        captured_at = time.monotonic()
        frame = task.executor.method.get_frame()
        if frame is None:
            self.unmatched_cards_since = None
            self.last_scene_seen = float("-inf")
            self.report("截图暂不可用, 等待恢复")
            self.next_tick = time.monotonic() + 0.5
            return
        height, width = frame.shape[:2]
        if abs(width / height - 16 / 9) > 0.04:
            self.stop("仅支持16:9画面, 已停止")
            return
        # Require activity-specific HUD on this frame, not a cached scene assumption.
        if time.monotonic() - self.last_scene_seen >= 0.25:
            hud = self.text(frame, (0.84, 0.13, 0.995, 0.34), threshold=0.6)
            hud = re.sub(r"\s+", "", hud).upper()
            if ("伤害跳字" in hud or "轨外回响" in hud
                    or ("轨外" in hud and "BOSS" in hud)):
                self.last_scene_seen = time.monotonic()
            elif "无尽挑战" in hud:
                timer = self.text(frame, (0.44, 0.07, 0.56, 0.13), threshold=0.6)
                if re.search(r"\d{1,2}[:：]\d{2}", re.sub(r"\s+", "", timer)):
                    self.last_scene_seen = time.monotonic()
                else:
                    self.report("检测到局内标识, 等待计时确认; 禁止文字点击")
                    return
        if time.monotonic() - self.last_scene_seen > 0.6:
            self.previous = ()
            if not self.click_configured_text(frame):
                self.report("未识别到轨外回响界面, 暂不移动")
            return
        foot = (round(float(task.config.get(FOOT_X, 0.5)) * 960),
                round(float(task.config.get(FOOT_Y, 0.565)) * 540))
        self.unmatched_cards_since = None
        if not (100 <= foot[0] < 800 and 110 <= foot[1] < 420):
            self.stop("脚底坐标不在识别范围内, 请重新校准")
            return
        boss_mask = boss_warning_mask(frame)
        mask = cv2.bitwise_or(danger_mask(frame), boss_mask)
        dodge_drift = (self.direction_dodges["d"] - self.direction_dodges["a"],
                       self.direction_dodges["s"] - self.direction_dodges["w"])
        keys = escape_keys(mask, foot, self.previous, self.drift, dodge_drift)
        if time.monotonic() - captured_at > 0.5:
            self.previous = ()
            self.report("识别耗时超过500ms, 已丢弃旧画面移动指令")
            return
        if not keys:
            self.safe_frames += 1
            if self.safe_frames >= 2:
                self.previous = ()
            self.report("脚下危险但未找到安全出口" if mask[foot[1], foot[0]]
                        else "确认脱离中" if self.safe_frames < 2
                        else "监测中, 脚下未发现红区")
            return
        self.safe_frames = 0
        self.previous = keys
        self.report(f"躲避红区: {'+'.join(keys).upper()}")
        self.pulse(keys, sprint=bool(boss_mask[foot[1], foot[0]])
                   and time.monotonic() >= self.next_dodge)

    def pulse(self, keys, sprint=False):
        import win32api
        import win32con

        interaction = self.task.executor.interaction
        background = self.task.config.get(self.task.CONF_INPUT_MODE) == self.task.INPUT_BG
        held = []
        started = {}
        right_down = False
        try:
            # Resolve/activate the mouse target BEFORE holding direction. Do not let
            # mouse_down retarget or reactivate the window after direction key-down.
            right_pos = interaction.update_mouse_pos(-1, -1) if background and sprint else 0
            for key in keys:
                if not self.running or not self.available():
                    return
                held.append(key)
                if background:
                    interaction.send_key_down(key)
                else:
                    win32api.keybd_event(self.task._get_vk_code(key), 0, 0, 0)
                started[key] = time.monotonic()
            if sprint and self.running and self.available():
                lead_deadline = time.monotonic() + 0.06
                while time.monotonic() < lead_deadline:
                    if not self.running or not self.available():
                        return
                    time.sleep(0.01)
                right_down = True
                if background:
                    interaction.post(win32con.WM_RBUTTONDOWN, win32con.MK_RBUTTON, right_pos)
                else:
                    win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
                self.dodge_count += 1
                self.next_dodge = time.monotonic() + 1.0
                for key in started:
                    self.direction_dodges[key] += 1
            deadline = time.monotonic() + movement_seconds(self.task.config)
            while time.monotonic() < deadline and self.running and self.available():
                time.sleep(0.01)
        finally:
            if right_down:
                try:
                    if background:
                        interaction.post(win32con.WM_RBUTTONUP, 0, right_pos)
                    else:
                        win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
                except Exception as error:
                    self.stop(f"右键释放失败: {type(error).__name__}")
            # Preserve movement briefly after normal right release; never delay a stop.
            if right_down and self.running and self.available():
                tail_deadline = time.monotonic() + 0.03
                try:
                    while time.monotonic() < tail_deadline and self.running and self.available():
                        time.sleep(0.01)
                except Exception as error:
                    self.stop(f"移动收尾异常: {type(error).__name__}")
            ended = time.monotonic()
            for key, start in started.items():
                elapsed = max(0.0, ended - start)
                self.direction_seconds[key] += elapsed
                amount = elapsed / math.sqrt(max(1, len(started)))
                self.drift[0] += amount * ((key == "d") - (key == "a"))
                self.drift[1] += amount * ((key == "s") - (key == "w"))
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
            if started and ended >= self.next_motion_summary:
                summary = ", ".join(f"{key.upper()}={value:.2f}s"
                                    for key, value in self.direction_seconds.items())
                self.task.info_set("活动累计移动", summary)
                dodges = ", ".join(f"{key.upper()}={value}次"
                                   for key, value in self.direction_dodges.items())
                self.task.info_set("活动累计闪避", dodges)
                summary += f", 闪避总计={self.dodge_count}次, 各方向闪避: {dodges}"
                self.task.log_info(f"活动累计移动: {summary}")
                self.next_motion_summary = ended + 5
