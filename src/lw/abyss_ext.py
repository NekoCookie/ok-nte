"""[lw] Off-Track Realm (abyss) screen parsing and station workflow helpers."""

import re
import time
from dataclasses import dataclass

import numpy as np

HALF_UPPER = "上行线"
HALF_LOWER = "下行线"
FULL_STARS = 3

EXIT_REPLAY = "replay"
EXIT_NEXT = "next"
EXIT_END = "end"

STATION_RE = re.compile(r"第\s*([0-9一二两三四五六七八九十]+)\s*站")
SEAL_RE = re.compile(r"印鉴.*?(\d+)\s*/\s*(\d+)")
FRACTION_RE = re.compile(r"^(\d+)\s*/\s*(\d+)$")
WAVE_RE = re.compile(r"波次[:：]?([0-9OoIl|]{1,2})\s*/\s*([0-9OoIl|]{1,2})")
WAVE_NO_SLASH_RE = re.compile(r"波次[:：]?([0-9Oo])([0-9Il|])(?![0-9])")
GO_RE = re.compile(r"前往")
TAB_RE = re.compile(r"轨外之境")
START_RE = re.compile(r"开始挑战")
POPUP_RE = re.compile(r"点击空白区域关闭")
RESTART_HALF_RE = re.compile(r"重启当前半场")
CONTINUE_RE = re.compile(r"继续挑战")
TRAVEL_RE = re.compile(r"^传送$")
NPC_RE = re.compile(r"浮游小姐")
OPTION_RES = {
    EXIT_NEXT: re.compile(r"去下一站"),
    EXIT_REPLAY: re.compile(r"再次游览"),
    EXIT_END: re.compile(r"结束行程"),
}

_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_OCR_DIGITS = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1"})


def parse_cn_number(text: str) -> int | None:
    """Parse 1-99 written as Arabic digits or simple Chinese numerals."""
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CN_DIGITS.get(left) if left else 1
        ones = _CN_DIGITS.get(right) if right else 0
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    if len(text) == 1:
        return _CN_DIGITS.get(text)
    return None


def _compact(text) -> str:
    return re.sub(r"\s+", "", getattr(text, "name", text) or "")


def _center_y(box) -> float:
    return box.y + box.height / 2


@dataclass(frozen=True)
class AbyssHud:
    station: int | None
    half: str | None
    wave: tuple[int, int] | None

    @property
    def finished(self) -> bool:
        return self.wave is not None and self.wave[1] > 0 and self.wave[0] >= self.wave[1]


def parse_hud(texts) -> AbyssHud | None:
    """Parse the top-left stage HUD, e.g. "第八站 下行线" and "怪物波次 1/1"."""
    joined = "".join(_compact(text) for text in texts or [])
    station_match = STATION_RE.search(joined)
    station = parse_cn_number(station_match.group(1)) if station_match else None
    half = HALF_UPPER if "上行" in joined else HALF_LOWER if "下行" in joined else None
    if station is None and half is None:
        return None
    wave = None
    wave_match = WAVE_RE.search(joined) or WAVE_NO_SLASH_RE.search(joined)
    if wave_match:
        done = int(wave_match.group(1).translate(_OCR_DIGITS))
        total = int(wave_match.group(2).translate(_OCR_DIGITS))
        wave = (done, total)
    return AbyssHud(station, half, wave)


@dataclass(frozen=True)
class AbyssRoute:
    seals: int
    total: int
    go_button: object

    @property
    def finished(self) -> bool:
        return self.seals >= self.total

    @property
    def station_count(self) -> int:
        return self.total // FULL_STARS


def parse_routes(texts) -> list[AbyssRoute]:
    """Pair each "印鉴收集 a/b" row with the nearest "前往" button below it."""
    texts = list(texts or [])
    seals = []
    for text in texts:
        name = _compact(text)
        if "印鉴" not in name:
            continue
        if match := SEAL_RE.search(name):
            seals.append((text, int(match.group(1)), int(match.group(2))))
            continue
        same_row = [
            other for other in texts
            if other is not text and other.x > text.x
            and abs(_center_y(other) - _center_y(text)) <= text.height
            and FRACTION_RE.match(_compact(other))
        ]
        if same_row:
            fraction = FRACTION_RE.match(_compact(min(same_row, key=lambda b: b.x)))
            seals.append((text, int(fraction.group(1)), int(fraction.group(2))))

    buttons = [text for text in texts if GO_RE.search(_compact(text))]
    routes = []
    for seal, done, total in sorted(seals, key=lambda item: item[0].y):
        below = [b for b in buttons if _center_y(b) >= _center_y(seal) - seal.height]
        if not below or total <= 0:
            continue
        button = min(below, key=lambda b: abs(_center_y(b) - _center_y(seal)))
        buttons.remove(button)
        routes.append(AbyssRoute(done, total, button))
    return routes


def select_route(routes) -> AbyssRoute | None:
    return next((route for route in routes if not route.finished), None)


@dataclass(frozen=True)
class StationCard:
    number: int
    box: object
    stars: int | None


# Medal centers relative to the "第X站" label center, as ratios of the frame size.
STAR_SLOT_DX = (-0.0295, 0.0, 0.0295)
STAR_SLOT_DY = 0.039
STAR_SLOT_HALF_W = 0.009
STAR_SLOT_HALF_H = 0.016
STAR_GOLD_THRESHOLD = 0.08


def gold_ratio(patch_bgr) -> float:
    if patch_bgr is None or patch_bgr.size == 0:
        return 0.0
    b = patch_bgr[..., 0].astype(np.int16)
    g = patch_bgr[..., 1].astype(np.int16)
    r = patch_bgr[..., 2].astype(np.int16)
    return float(((r >= 200) & (g >= 140) & (b <= 110)).mean())


def count_card_stars(frame, label_box, bottom_limit: float = 0.86) -> int | None:
    """Count gold medals under a station label, or None when the medals are cut off."""
    height, width = frame.shape[:2]
    cx = label_box.x + label_box.width / 2
    cy = _center_y(label_box) + STAR_SLOT_DY * height
    half_w, half_h = STAR_SLOT_HALF_W * width, STAR_SLOT_HALF_H * height
    if cy + half_h > bottom_limit * height:
        return None
    stars = 0
    for dx in STAR_SLOT_DX:
        x = cx + dx * width
        patch = frame[int(cy - half_h):int(cy + half_h), int(x - half_w):int(x + half_w)]
        if gold_ratio(patch) >= STAR_GOLD_THRESHOLD:
            stars += 1
    return stars


def parse_station_cards(texts, frame) -> list[StationCard]:
    cards = {}
    for text in texts or []:
        match = STATION_RE.search(_compact(text))
        number = parse_cn_number(match.group(1)) if match else None
        if number is None or number in cards:
            continue
        cards[number] = StationCard(number, text, count_card_stars(frame, text))
    return [cards[number] for number in sorted(cards)]


def select_station(cards) -> StationCard | None:
    return next(
        (card for card in cards if card.stars is not None and card.stars < FULL_STARS), None
    )


# Pink check marks after the three HUD objectives, as (y center, x0, x1) frame ratios.
HUD_CHECK_ROWS = (0.358, 0.406, 0.453)
HUD_CHECK_X = (0.135, 0.205)
HUD_CHECK_HALF_H = 0.018
HUD_CHECK_THRESHOLD = 0.015


def pink_ratio(patch_bgr) -> float:
    if patch_bgr is None or patch_bgr.size == 0:
        return 0.0
    b = patch_bgr[..., 0].astype(np.int16)
    g = patch_bgr[..., 1].astype(np.int16)
    r = patch_bgr[..., 2].astype(np.int16)
    return float(((r >= 200) & (g <= 130) & (b >= 90) & (b <= 210) & (r - g >= 90)).mean())


def hud_check_marks(frame) -> list[bool]:
    height, width = frame.shape[:2]
    x0, x1 = int(HUD_CHECK_X[0] * width), int(HUD_CHECK_X[1] * width)
    marks = []
    for row in HUD_CHECK_ROWS:
        y0 = int((row - HUD_CHECK_HALF_H) * height)
        y1 = int((row + HUD_CHECK_HALF_H) * height)
        marks.append(pink_ratio(frame[y0:y1, x0:x1]) >= HUD_CHECK_THRESHOLD)
    return marks


def count_hud_checks(frame) -> int:
    return sum(hud_check_marks(frame))


def station_cleared(hud: AbyssHud | None, frame) -> bool:
    """The lower half is cleared when its waves are full or "defeat all" is checked.

    The yellow "0/1" wave counter is often misread, so the pink check after the
    first objective is the independent completion signal.
    """
    if hud is None or hud.half != HALF_LOWER:
        return False
    return hud.finished or hud_check_marks(frame)[0]


def parse_dialog_options(texts) -> dict:
    options = {}
    for text in texts or []:
        name = _compact(text)
        for key, pattern in OPTION_RES.items():
            if key not in options and pattern.search(name):
                options[key] = text
    return options


def choose_station_exit(stars, replays_used, max_replays, station, station_count, options):
    """Replay an unfinished station within budget, otherwise continue or end the trip."""
    if stars < FULL_STARS and replays_used < max_replays and EXIT_REPLAY in options:
        return EXIT_REPLAY
    is_last = station is not None and station_count and station >= station_count
    if EXIT_NEXT in options and not is_last:
        return EXIT_NEXT
    return EXIT_END if EXIT_END in options else None


class AbyssAbort(Exception):
    """The abyss run cannot recover automatically and must stop."""


class AbyssTaskMixin:
    """[lw] Screen-driven Off-Track Realm workflow built on RU navigation and combat."""

    CONF_COMBAT_WAIT = "未进战斗重启等待(秒)"
    CONF_MAX_RESTARTS = "单个半场最多重启次数"
    CONF_MAX_REPLAYS = "不满星重打次数"
    CONF_USE_ULT = "使用终结技"

    TAB_ROI = (0.10, 0.12, 0.98, 0.19)
    TAB_FALLBACK = (0.79, 0.15)
    ROUTE_ROI = (0.10, 0.20, 0.98, 0.95)
    STATION_LIST_ROI = (0.83, 0.20, 0.97, 0.90)
    STATION_SCROLL_POS = (0.89, 0.55)
    STATION_SCROLL_STEP = 3
    STATION_MAX_SCROLLS = 8
    START_ROI = (0.60, 0.87, 0.98, 0.97)
    HUD_ROI = (0.02, 0.22, 0.22, 0.34)
    POPUP_ROI = (0.30, 0.78, 0.70, 0.90)
    ESC_MENU_ROI = (0.15, 0.55, 0.85, 0.65)
    NPC_ROI = (0.15, 0.05, 0.90, 0.85)
    DIALOG_ROI = (0.60, 0.50, 0.98, 0.85)
    TRAVEL_ROI = (0.72, 0.84, 0.99, 0.96)
    # ESC stage-menu captions are not clickable; the round icon sits above the caption.
    ESC_MENU_ICON_DY = 0.143

    UPPER_TRANSITION_TIMEOUT = 15
    STATION_LIST_TIMEOUT = 90
    WALK_POLL_INTERVAL = 0.3
    NO_TEAM_TIMEOUT = 60
    LEAVE_TIMEOUT = 30
    NPC_ATTEMPTS = 3

    def configure_abyss(self):
        self.default_config.update({
            self.CONF_COMBAT_WAIT: 8.0,
            self.CONF_MAX_RESTARTS: 3,
            self.CONF_MAX_REPLAYS: 2,
            self.CONF_USE_ULT: True,
        })
        self.config_description.update({
            self.CONF_COMBAT_WAIT: "每个半场往前走超过该秒数仍未进入战斗, 按ESC重启当前半场",
            self.CONF_MAX_RESTARTS: "同一半场连续重启超过该次数后停止任务并通知",
            self.CONF_MAX_REPLAYS: "站点通关但不满3星时, 找乘务员选择再次游览的最多次数",
        })

    def _abyss_int(self, key, default, low, high):
        try:
            value = int(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    def _abyss_combat_wait(self) -> float:
        try:
            value = float(self.config.get(self.CONF_COMBAT_WAIT, 8.0))
        except (TypeError, ValueError):
            value = 8.0
        return max(3.0, min(60.0, value))

    def _abyss_ocr(self, roi, match=None, frame=None):
        return self.ocr(box=self.box_of_screen(*roi), match=match, frame=frame) or []

    # ---------- entry ----------

    def abyss_run(self):
        self._abyss_station_count = 0
        self._abyss_cleared = 0
        self.info_set("完成站点", 0)
        self.abyss_prepare_start()
        if not self.abyss_in_stage():
            route = self.abyss_open_route()
            if route is None:
                return
            if not self.abyss_enter_first_unfinished_station():
                return
        replays = 0
        while True:
            hud = self.abyss_play_station()
            stars = self.abyss_read_stars()
            self.log_info(f"第{hud.station}站通关, 星数 {stars}/{FULL_STARS}")
            choice = self.abyss_leave_station(hud, stars, replays)
            if choice == EXIT_REPLAY:
                replays += 1
                continue
            self._abyss_cleared += 1
            self.info_set("完成站点", self._abyss_cleared)
            replays = 0
            if choice != EXIT_NEXT:
                break
        self.log_info(f"轨外之境结束, 本次完成 {self._abyss_cleared} 个站点", notify=True)

    def abyss_prepare_start(self):
        """Return to a playable screen when the task starts on an overlay.

        The stage ESC menu is resumed with "继续挑战" so a mid-stage start keeps its
        progress; other panels are closed by RU ``ensure_main``.
        """
        if self._abyss_ocr(self.ESC_MENU_ROI, CONTINUE_RE):
            self.log_info("启动时处于关卡ESC菜单, 继续挑战")
            self._abyss_click_menu_entry(CONTINUE_RE)
            self.wait_in_team(time_out=10, raise_if_not_found=False)
        self.ensure_main()

    def abyss_in_stage(self) -> bool:
        return bool(self.is_in_team()) and self.abyss_read_hud() is not None

    # ---------- navigation ----------

    def abyss_open_route(self) -> AbyssRoute | None:
        self.ensure_main()
        self.open_f1_domain_page()
        tabs = self._abyss_ocr(self.TAB_ROI, TAB_RE)
        if tabs:
            self.operate_click(tabs[0])
        else:
            self.operate_click(*self.TAB_FALLBACK)
        routes = self.wait_until(
            lambda: parse_routes(self._abyss_ocr(self.ROUTE_ROI)), time_out=8, settle_time=0.5
        )
        if not routes:
            raise AbyssAbort("未识别到轨外之境路线列表")
        for route in routes:
            self.log_info(f"路线印鉴 {route.seals}/{route.total}")
        route = select_route(routes)
        if route is None:
            self.log_info("所有路线印鉴已满, 无需挑战", notify=True)
            return None
        self._abyss_station_count = route.station_count
        self.operate_click(route.go_button)
        return route

    def abyss_read_station_cards(self) -> list[StationCard]:
        frame = self.frame
        texts = self._abyss_ocr(self.STATION_LIST_ROI, STATION_RE, frame=frame)
        return parse_station_cards(texts, frame)

    def _abyss_advance_to_station_list(self):
        """Handle the map teleport or entrance interaction that can precede the list."""
        if travel := self._abyss_ocr(self.TRAVEL_ROI, TRAVEL_RE):
            self.log_info("点击传送前往轨外之境")
            self.operate_click(travel[0], action_name="abyss_travel", interval=3)
        elif self.is_in_team() and self.find_interac():
            self.send_key("f", action_name="abyss_entry", interval=3)

    def abyss_enter_first_unfinished_station(self) -> bool:
        if not self.wait_until(
            self.abyss_read_station_cards,
            pre_action=self._abyss_advance_to_station_list,
            time_out=self.STATION_LIST_TIMEOUT,
            settle_time=0.5,
        ):
            raise AbyssAbort("未识别到站点列表")
        snap_box = self.box_of_screen(*self.STATION_LIST_ROI)
        x, y = self.STATION_SCROLL_POS
        for step in (-self.STATION_SCROLL_STEP, self.STATION_SCROLL_STEP):
            for _ in range(self.STATION_MAX_SCROLLS + 1):
                cards = self.abyss_read_station_cards()
                self.log_info(
                    "站点星数: " + ", ".join(f"{c.number}:{c.stars}" for c in cards)
                )
                if card := select_station(cards):
                    self.log_info(f"选择第{card.number}站, 当前星数 {card.stars}")
                    self.operate_click(card.box)
                    return self.abyss_start_challenge()
                if self.scroll_and_is_end(x, y, step, snap_box, after_sleep=0.6):
                    break
        self.log_info("当前路线没有未满星的站点", notify=True)
        return False

    def abyss_start_challenge(self) -> bool:
        buttons = self.wait_until(
            lambda: self._abyss_ocr(self.START_ROI, START_RE), time_out=8, settle_time=0.3
        )
        if not buttons:
            raise AbyssAbort("未识别到开始挑战按钮")
        self.wait_until(
            lambda: not self._abyss_ocr(self.START_ROI, START_RE),
            pre_action=lambda: self.operate_click(buttons[0], interval=2),
            time_out=15,
        )
        self.wait_in_team(time_out=60)
        return True

    # ---------- stage ----------

    def abyss_read_hud(self, frame=None) -> AbyssHud | None:
        return parse_hud(self._abyss_ocr(self.HUD_ROI, frame=frame))

    def abyss_close_popup(self) -> bool:
        popup = self._abyss_ocr(self.POPUP_ROI, POPUP_RE)
        if not popup:
            return False
        self.log_info("关闭站点增益说明")
        self.operate_click(popup[0], after_sleep=0.8)
        return True

    def abyss_fight(self):
        self.lw_combat_run()
        self.wait_in_team(time_out=10, raise_if_not_found=False)

    def _abyss_open_stage_menu(self):
        # ESC toggles the stage menu, so never press it while the menu is already open.
        if not self._abyss_ocr(self.ESC_MENU_ROI, RESTART_HALF_RE):
            self.send_key("esc", action_name="abyss_esc", interval=2)

    def abyss_restart_half(self):
        self.log_info("重启当前半场")
        button = self.wait_until(
            lambda: self._abyss_ocr(self.ESC_MENU_ROI, RESTART_HALF_RE),
            pre_action=self._abyss_open_stage_menu,
            time_out=8,
            settle_time=0.3,
        )
        if not button:
            raise AbyssAbort("未打开ESC菜单中的重启当前半场")
        if not self._abyss_click_menu_entry(RESTART_HALF_RE):
            raise AbyssAbort("点击重启当前半场后菜单未关闭")
        self.wait_click_confirm(time_out=2, raise_if_not_found=False)
        self.wait_in_team(time_out=60)

    def _abyss_menu_icon_point(self, caption) -> tuple[float, float]:
        x = (caption.x + caption.width / 2) / self.width
        y = (caption.y + caption.height / 2) / self.height - self.ESC_MENU_ICON_DY
        return x, y

    def _abyss_click_menu_entry(self, pattern) -> bool:
        """Click a stage-menu icon until its caption disappears."""

        def click_icon():
            if captions := self._abyss_ocr(self.ESC_MENU_ROI, pattern):
                self.operate_click(
                    *self._abyss_menu_icon_point(captions[0]),
                    action_name="abyss_menu_icon",
                    interval=1.5,
                )

        return bool(self.wait_until(
            lambda: not self._abyss_ocr(self.ESC_MENU_ROI, pattern),
            pre_action=click_icon,
            time_out=8,
            settle_time=0.3,
        ))

    def abyss_play_station(self) -> AbyssHud:
        """Fight both halves until the lower half reports all waves cleared."""
        max_restarts = self._abyss_int(self.CONF_MAX_RESTARTS, 3, 0, 20)
        combat_wait = self._abyss_combat_wait()
        restarts = 0
        current_half = None
        upper_done_since = None
        no_team_since = None
        while True:
            self.abyss_close_popup()
            if self.in_combat():
                self.abyss_fight()
                upper_done_since = None
                continue
            if not self.is_in_team():
                no_team_since = no_team_since or time.time()
                if time.time() - no_team_since > self.NO_TEAM_TIMEOUT:
                    self.log_warning("长时间未回到队伍画面, 尝试重启当前半场")
                    no_team_since = None
                    restarts = self._abyss_count_restart(restarts, max_restarts)
                    self.abyss_restart_half()
                else:
                    self.sleep(0.5)
                continue
            no_team_since = None
            frame = self.frame
            hud = self.abyss_read_hud(frame)
            if hud is None or hud.half is None:
                self.sleep(0.5)
                continue
            if hud.half != current_half:
                current_half = hud.half
                restarts = 0
                self.info_set("当前站点", f"第{hud.station}站 {hud.half}")
            if station_cleared(hud, frame):
                return hud
            if hud.finished:
                upper_done_since = upper_done_since or time.time()
                if time.time() - upper_done_since < self.UPPER_TRANSITION_TIMEOUT:
                    self.sleep(0.3)
                    continue
                self.log_warning("上半场已完成但未进入下半场")
            upper_done_since = None
            if self.abyss_walk_until_combat(combat_wait):
                self.abyss_fight()
                continue
            self.log_warning(f"{hud.half} {combat_wait:.0f}s 内未进入战斗")
            restarts = self._abyss_count_restart(restarts, max_restarts)
            self.abyss_restart_half()

    def abyss_walk_until_combat(self, time_out: float) -> bool:
        """Run forward until combat; a buff popup pauses the walk and restarts the timer."""
        self.middle_click(after_sleep=0.2)
        deadline = time.time() + time_out
        held = False
        try:
            while time.time() < deadline:
                if self.in_combat():
                    return True
                if self.abyss_close_popup():
                    if held:
                        self.send_key_up("w")
                        held = False
                    deadline = time.time() + time_out
                    continue
                if not held:
                    self.send_key_down("w")
                    self.sleep(0.1)
                    self.send_key("lshift")
                    held = True
                self.sleep(self.WALK_POLL_INTERVAL)
            return bool(self.in_combat())
        finally:
            if held:
                self.send_key_up("w")

    def _abyss_count_restart(self, restarts, max_restarts) -> int:
        restarts += 1
        self.info_set("本半场重启次数", restarts)
        if restarts > max_restarts:
            raise AbyssAbort(f"同一半场已重启 {max_restarts} 次仍未完成")
        return restarts

    def abyss_read_stars(self) -> int:
        stars = 0
        for _ in range(3):
            self.sleep(0.4)
            stars = max(stars, count_hud_checks(self.frame))
        return stars

    # ---------- station exit ----------

    def abyss_find_npc(self):
        texts = self._abyss_ocr(self.NPC_ROI, NPC_RE)
        return texts[0] if texts else None

    def abyss_read_dialog_options(self) -> dict:
        return parse_dialog_options(self._abyss_ocr(self.DIALOG_ROI))

    def abyss_talk_to_npc(self) -> dict:
        for attempt in range(self.NPC_ATTEMPTS):
            if not self.find_interac():
                self.rotate_and_find(self.abyss_find_npc, self.find_interac)
                self.walk_to_box(
                    self.abyss_find_npc,
                    time_out=20,
                    end_condition=self.find_interac,
                    y_offset=0.1,
                    x_threshold=0.15,
                )
            if self.find_interac():
                self.send_key("f", after_sleep=1)
                options = self.wait_until(self.abyss_read_dialog_options, time_out=5)
                if options:
                    return options
            self.log_warning(f"第{attempt + 1}次寻找乘务员失败")
        raise AbyssAbort("未能与乘务员对话")

    def abyss_leave_station(self, hud: AbyssHud, stars: int, replays: int) -> str:
        options = self.abyss_talk_to_npc()
        max_replays = self._abyss_int(self.CONF_MAX_REPLAYS, 2, 0, 20)
        choice = choose_station_exit(
            stars, replays, max_replays, hud.station, self._abyss_station_count, options
        )
        if choice is None:
            raise AbyssAbort("乘务员对话中没有可用选项")
        self.log_info(f"乘务员选项: {choice}")
        self.wait_until(
            lambda: not self.abyss_read_dialog_options(),
            pre_action=lambda: self.operate_click(options[choice], interval=2),
            time_out=10,
        )
        if choice == EXIT_END:
            self.wait_in_team(time_out=60, raise_if_not_found=False)
        elif not self.wait_until(
            lambda: not self._abyss_cleared_stage_visible(), time_out=self.LEAVE_TIMEOUT
        ):
            raise AbyssAbort("选择乘务员选项后仍停留在已通关画面")
        return choice

    def _abyss_cleared_stage_visible(self) -> bool:
        if not self.is_in_team():
            return False
        frame = self.frame
        return station_cleared(self.abyss_read_hud(frame), frame)
