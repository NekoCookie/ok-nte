import random
import re
import time
from typing import List

import cv2
import numpy as np
from ok import Logger, safe_get

from src import text_white_color
from src.char.BaseChar import BaseChar, Element, Priority
from src.char.CharFactory import get_char_by_name, get_char_by_pos
from src.char.custom.CustomCharManager import CustomCharManager
from src.char.Healer import Healer
from src.combat.CombatCheck import CombatCheck
from src.sound_trigger.SoundCombatContext import SoundCombatContext
from src.utils import game_filters as gf
from src.utils import image_utils as iu

logger = Logger.get_logger(__name__)
cd_regex = re.compile(r"\d{1,2}\.\d")


class NotInCombatException(Exception):
    """未处于战斗状态异常。"""

    pass


class CharDeadException(NotInCombatException):
    """角色死亡异常。"""

    pass


class CharUnavailableException(NotInCombatException):
    pass


class TeamChangedException(NotInCombatException):
    pass


class BaseCombatTask(CombatCheck):
    """基础战斗任务类，封装了游戏"鸣潮"中角色自动化操作的通用逻辑。"""

    hot_key_verified = False  # 热键是否已验证
    freeze_durations = []  # 记录冻结/卡肉的持续时间
    # 锚定技能/大招 CD 时, 若 OCR 读不到数字且图标不亮(无旧锚点)的保守占位:
    # 当成仍在冷却, 宁可多冷却也不误判可用(避免空切)。
    UNKNOWN_CD_SECONDS = 20.0
    # 技能就绪模板匹配阈值: OCR 读不到数字时, 拿当前技能图标和该角色"就绪模板"带遮罩匹配,
    # 置信度 >= 此值判就绪(锚 0)。实测就绪 0.95~1.00 / CD 0.07~0.22, 0.7 两边大余量。
    SKILL_READY_TEMPLATE_THRESHOLD = 0.7
    # CD 诊断开关: 平时 False(不影响实战); 想观察"切早/切晚/空切"或采技能样本时翻成 True。
    # 开启后会打 cd-truth 切上场对照日志, 并把技能图标存到 logs/box_debug(含同步磁盘写)。
    SKILL_CD_DIAG = False

    element_ring = (
        Element.WHITE,
        Element.GREEN,
        Element.RED,
        Element.PURPLE,
        Element.BLUE,
        Element.YELLOW,
    )
    element_ring_index = {element: index for index, element in enumerate(element_ring)}
    _element_template_cache = {}
    LOAD_CHARS_WEAK_RETRY = 2
    LOAD_CHARS_WEAK_RETRY_INTERVAL = 0.25
    LOAD_CHARS_SNAPSHOT_RETRY_WINDOW = 0.8
    LOAD_CHARS_SNAPSHOT_RETRY_INTERVAL = 0.08
    TEAM_CHANGE_CHECK_INTERVAL = 0.3
    TEAM_CHANGE_CONFIRM_INTERVAL = 0.8
    TEAM_SIGNATURE_CHECK_INTERVAL = 1.0
    TEAM_SIGNATURE_CONFIRM_INTERVAL = 0.5
    TEAM_SIGNATURE_MATCH_THRESHOLD = 0.6
    CHAR_UNAVAILABLE_BASE_COOLDOWN = 8.0
    CHAR_UNAVAILABLE_MAX_COOLDOWN = 30.0

    def __init__(self, *args, **kwargs):
        """初始化战斗任务。

        Args:
            *args: 传递给父类的参数。
            **kwargs: 传递给父类的关键字参数。
        """
        super().__init__(*args, **kwargs)
        self.chars: list[BaseChar] = []
        self.mouse_pos = None  # 当前鼠标位置
        self.combat_start = 0  # 战斗开始时间戳

        self.add_text_fix({"Ｅ": "e"})
        self.use_ultimate = True
        self.vibrate_chars_index: list[int] = []
        self.chars_slot_mat = [None, None, None, None]
        self.element_ring_reaction_counts = {}
        self._last_team_change_check = 0.0
        self._last_team_signature_check = 0.0
        self._pending_team_change = None
        self._pending_team_signature_change = None
        self._team_change_checking = False
        self.unavailable_char_until = {}
        self.unavailable_char_failures = {}
        self.clear_element_ring_reactions()

    @property
    def team_size(self):
        """获取当前队伍人数。

        Returns:
            int: 当前队伍中的角色数量。
        """
        return len(self.chars)

    def get_next_char_index(self):
        """获取下一个角色的索引。

        Returns:
            int: 下一个角色的索引。
        """
        current_index = self.get_current_char().index
        next_index = (current_index + 1) % len(self.chars)
        return next_index

    def get_longest_idle_char_index(self) -> int:
        """获取最久没有登场角色的索引。

        Returns:
            int: 角色的索引。如果没有角色，返回 -1。
        """
        if not self.chars:
            return -1
        min_time = float("inf")
        min_index = -1
        for char in self.chars:
            if char is None or self.is_char_unavailable(char):
                continue
            if char.last_switch_time < min_time:
                min_time = char.last_switch_time
                min_index = char.index
        return min_index

    def reset_unavailable_chars(self):
        self.unavailable_char_until.clear()
        self.unavailable_char_failures.clear()

    def is_char_unavailable(self, char: "BaseChar | None") -> bool:
        if char is None:
            return False
        until = self.unavailable_char_until.get(char.index)
        if until is None:
            return False
        if time.time() < until:
            return True
        self.unavailable_char_until.pop(char.index, None)
        return False

    def mark_char_unavailable(self, char: "BaseChar | None", reason: str):
        if char is None:
            return
        failures = self.unavailable_char_failures.get(char.index, 0) + 1
        cooldown = min(
            self.CHAR_UNAVAILABLE_BASE_COOLDOWN * failures,
            self.CHAR_UNAVAILABLE_MAX_COOLDOWN,
        )
        self.unavailable_char_failures[char.index] = failures
        self.unavailable_char_until[char.index] = time.time() + cooldown
        self.log_info(
            f"mark char unavailable {self._get_char_log_name(char)} "
            f"slot {char.index + 1} for {cooldown:.1f}s: {reason}"
        )

    def _get_element_ring_pair(self, element_a: Element, element_b: Element):
        index_a = self.element_ring_index.get(element_a)
        index_b = self.element_ring_index.get(element_b)
        if index_a is None or index_b is None or index_a == index_b:
            return None
        ring_size = len(self.element_ring)
        if (index_a + 1) % ring_size == index_b:
            return element_a, element_b
        if (index_b + 1) % ring_size == index_a:
            return element_b, element_a
        return None

    def clear_element_ring_reactions(self):
        self.element_ring_reaction_counts = {
            (self.element_ring[i], self.element_ring[(i + 1) % len(self.element_ring)]): 0
            for i in range(len(self.element_ring))
        }

    def record_element_ring_reaction(self, char_a: "BaseChar", char_b: "BaseChar") -> bool:
        if char_a is None or char_b is None:
            return False
        pair = self._get_element_ring_pair(char_a.element, char_b.element)
        if pair is None:
            return False
        self.element_ring_reaction_counts[pair] = self.element_ring_reaction_counts.get(pair, 0) + 1
        return True

    def find_element_ring_reaction_target(self, source_char: "BaseChar") -> "BaseChar | None":
        if source_char is None:
            return None
        source_element_index = self.element_ring_index.get(source_char.element)
        if source_element_index is None:
            return None

        ring_size = len(self.element_ring)
        previous_element = self.element_ring[(source_element_index - 1) % ring_size]
        next_element = self.element_ring[(source_element_index + 1) % ring_size]

        previous_target = None
        next_target = None
        for char in self.chars:
            if char is None or char.index == source_char.index:
                continue
            if char.element == previous_element and (
                previous_target is None or char.last_switch_time < previous_target.last_switch_time
            ):
                previous_target = char
            elif char.element == next_element and (
                next_target is None or char.last_switch_time < next_target.last_switch_time
            ):
                next_target = char

        if previous_target is None:
            return next_target
        if next_target is None:
            return previous_target

        previous_pair = self._get_element_ring_pair(source_char.element, previous_target.element)
        next_pair = self._get_element_ring_pair(source_char.element, next_target.element)
        previous_count = self.element_ring_reaction_counts.get(previous_pair, 0)
        next_count = self.element_ring_reaction_counts.get(next_pair, 0)
        if previous_count <= next_count:
            return previous_target
        return next_target

    def add_freeze_duration(self, start, duration=-1.0, freeze_time=0.1):
        """添加冻结持续时间。用于精确计算技能冷却等。

        Args:
            start (float): 冻结开始时间。
            duration (float, optional): 冻结持续时间。如果为-1.0, 则根据当前时间计算。默认为 -1.0。
            freeze_time (float, optional): 认为发生冻结的最小持续时间。默认为 0.1。
        """
        if duration < 0:
            duration = time.time() - start
        if start > 0 and duration > freeze_time:
            current_time = time.time()
            self.freeze_durations = [
                item for item in self.freeze_durations if item[0] > current_time - 60
            ]
            self.freeze_durations.append((start, duration, freeze_time))

    def time_elapsed_accounting_for_freeze(self, start, intro_motion_freeze=False):
        """计算扣除冻结时间后经过的时间。

        Args:
            start (float): 开始时间戳。
            intro_motion_freeze (bool, optional): 是否考虑角色入场动画的特殊冻结。默认为 False。

        Returns:
            float: 扣除冻结后实际经过的时间 (秒)。
        """
        if start < 0:
            return 10000
        to_minus = 0
        for freeze_start, duration, freeze_time in self.freeze_durations:
            if start < freeze_start:
                if intro_motion_freeze:
                    if freeze_time == -100:
                        freeze_time = 0
                elif freeze_time == -100:
                    continue
                to_minus += duration - freeze_time
        if to_minus != 0:
            self.run_with_interval(
                lambda: self.log_debug(f"time_elapsed_accounting_for_freeze to_minus {to_minus}"),
                0.5,
            )
        return time.time() - start - to_minus

    def refresh_cd(self):
        if self.scene.cd_refreshed:
            return
        index = self.get_current_char().index
        cds = self.cds.get(index)
        if cds is None:
            cds = {}
            self.cds[index] = cds
        # 诊断(SKILL_CD_DIAG):切上场瞬间(覆盖锚点前)记下"下场最后推算",待在场首次读到真实CD对照。
        if self.SKILL_CD_DIAG and getattr(self, "_last_refresh_index", None) != index:
            self._capture_switch_in_estimate(index, cds)
        now = time.time()
        cds["time"] = now  # 兼容旧字段; 实际推算用每个 box 独立的 <box>_time
        texts = self.ocr(
            0.8594, 0.8847, 0.9578, 0.9139, frame_processor=gf.isolate_cd_to_black, match=cd_regex
        )
        ocr_cds = {"skill": None, "ultimate": None}
        for text in texts:
            cd = convert_cd(text)
            if text.x < self.width_of_screen(0.89):
                ocr_cds["skill"] = cd
            elif text.x > self.width_of_screen(0.925):
                ocr_cds["ultimate"] = cd
        # 关键: 不要把"OCR 没读到数字"当成 CD=0。读不到时用图标高亮区分:
        #   图标亮 = 已就绪 -> 锚 0; 图标暗 = 仍在冷却但数字没识别(坏帧) -> 保留上次可信锚点。
        for box, ocr_cd in ocr_cds.items():
            if self.SKILL_CD_DIAG:
                self._dump_box_debug(box, ocr_cd)
            if ocr_cd is not None:
                cds[box] = ocr_cd
                cds[box + "_time"] = now
            elif self._box_ready_no_number(box):
                cds[box] = 0
                cds[box + "_time"] = now
            elif box not in cds:
                # 从未成功锚定过 + 此刻坏帧: 保守占位为冷却中, 等下一帧重锚。
                cds[box] = self.UNKNOWN_CD_SECONDS
                cds[box + "_time"] = now
            # else: 保留 cds[box] / cds[box+"_time"] 不变, 继续按上次锚点倒计时
        if self.SKILL_CD_DIAG:
            self._report_switch_in_cd_truth(index, cds, now)
            self._last_refresh_index = index
        self.scene.cd_refreshed = True
        # self.log_debug(f"cd refreshed: {cds} {time.time() - cds['time']}")

    def _box_ready_no_number(self, box):
        """OCR 读不到 CD 数字时判该格是否就绪。
        技能: 该角色有就绪模板 → 带遮罩模板匹配(只比白图标、忽略透明区透出的场景, 准且场景鲁棒);
              无模板的角色 → 退回原 box_highlighted。
        大招: 仍用 box_highlighted(大招实际走头像菱形, 这条线不改)。"""
        if box == "skill":
            ready = self._skill_ready_by_template()
            if ready is not None:
                return ready
        return bool(self.box_highlighted(box))

    def _skill_ready_by_template(self):
        """当前在场角色的技能图标(扩到整圆)与其就绪模板带遮罩匹配, 返回 True/False;
        无模板或异常返回 None(调用方退回 box_highlighted)。
        匹配原生裁块(不缩放裁块, 否则 1px 缩放就会把分数打废); 小模板在大裁块上滑动,
        只有当前分辨率比模板还低、模板放不下时才把模板缩小。"""
        try:
            char = self.get_current_char()
            if char is None:
                return None
            entry = self._load_skill_ready_template(getattr(char, "char_name", ""))
            if entry is None:
                return None
            inner, mask = entry
            frame = self.frame
            if frame is None:
                return None
            box_obj = self.get_box_by_name("box_skill")
            fh, fw = frame.shape[:2]
            cx = box_obj.x + box_obj.width / 2.0
            cy = box_obj.y + box_obj.height / 2.0
            half = box_obj.width * 1.1
            x1, x2 = max(0, int(cx - half)), min(fw, int(cx + half))
            y1, y2 = max(0, int(cy - half)), min(fh, int(cy + half))
            crop = frame[y1:y2, x1:x2]
            if crop is None or crop.size == 0:
                return None
            ch, cw = crop.shape[:2]
            ih, iw = inner.shape[:2]
            if ih >= ch or iw >= cw:  # 分辨率比模板低, 模板放不下 → 把模板缩到能滑动
                s = min((ch - 4) / ih, (cw - 4) / iw)
                if s <= 0:
                    return None
                inner = cv2.resize(inner, (max(8, int(iw * s)), max(8, int(ih * s))))
                mask = cv2.resize(mask, (inner.shape[1], inner.shape[0]))
            r = cv2.matchTemplate(crop, inner, cv2.TM_CCOEFF_NORMED, mask=mask)
            r[~np.isfinite(r)] = 0
            return float(r.max()) >= self.SKILL_READY_TEMPLATE_THRESHOLD
        except Exception as e:
            self.log_debug(f"skill ready template match failed: {e}")
            return None

    def _load_skill_ready_template(self, char_name):
        """加载并缓存角色技能就绪模板: 返回 (内裁模板, 白图标遮罩) 或 None。
        遮罩 = 模板里的白色图标像素(亮度阈值), 匹配时只比图标、不比透明区(场景)。"""
        cache = getattr(self, "_skill_ready_tmpl_cache", None)
        if cache is None:
            cache = {}
            self._skill_ready_tmpl_cache = cache
        if char_name in cache:
            return cache[char_name]
        entry = None
        try:
            import os

            if char_name:
                path = os.path.join("assets", "skill_ready", f"{char_name}.png")
                if os.path.exists(path):
                    # 中文路径 cv2.imread 读不了(Windows), 用 np.fromfile + imdecode。
                    full = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if full is not None and full.size > 0:
                        th, tw = full.shape[:2]
                        m = max(6, int(min(tw, th) * 0.08))
                        inner = full[m:th - m, m:tw - m]
                        g = cv2.cvtColor(inner, cv2.COLOR_BGR2GRAY)
                        _, mk = cv2.threshold(g, 170, 255, cv2.THRESH_BINARY)
                        mk3 = cv2.cvtColor(mk, cv2.COLOR_GRAY2BGR)
                        entry = (inner, mk3)
                        logger.info(f"loaded skill ready template for {char_name}")
        except Exception as e:
            self.log_debug(f"load skill ready template {char_name} failed: {e}")
        cache[char_name] = entry
        return entry

    def _capture_switch_in_estimate(self, index, cds):
        """临时诊断:切上场瞬间,用覆盖前的下场锚点算出"下场最后推算 CD",挂起待对照。验证完即删。"""
        try:
            est = {}
            for box in ("skill", "ultimate"):
                if box in cds and (box + "_time") in cds:
                    elapsed = self.time_elapsed_accounting_for_freeze(cds[box + "_time"])
                    est[box] = cds[box] - elapsed
            self._switch_in_pending = {"index": index, "est": est} if est else None
        except Exception as e:
            self.log_debug(f"capture switch-in est failed: {e}")
            self._switch_in_pending = None

    def _report_switch_in_cd_truth(self, index, cds, now):
        """临时诊断:角色切上场后,在场首次读到真实 CD 的那一刻,把"下场最后推算"与"在场真实"
        并排打出,直接暴露切早(推算可用·实际仍冷却=空切)/切晚(推算冷却·实际已就绪=浪费)。
        每个 box 只在确实重锚到在场真实读数(本帧 _time==now)时对照一次。验证完即删。"""
        pending = getattr(self, "_switch_in_pending", None)
        if not pending or pending.get("index") != index:
            return
        try:
            est = pending["est"]
            for box in list(est.keys()):
                if cds.get(box + "_time") != now:
                    continue  # 本帧没读到在场真实(坏帧),留到下一帧再对照
                e = est[box]
                real = cds.get(box, 0)
                e_rdy, r_rdy = e <= 0, real <= 0
                flag = "准"
                if e_rdy and not r_rdy:
                    flag = "切早(推算可用·实际冷却=空切)"
                elif not e_rdy and r_rdy:
                    flag = "切晚(推算冷却·实际就绪=浪费)"
                self.log_info(
                    f"cd-truth char{index + 1} {box} 切上场对照: "
                    f"下场推算={e:.1f}({'可用' if e_rdy else '冷却'}) vs "
                    f"在场真实={real:.1f}({'就绪' if r_rdy else '冷却'}) "
                    f"误差={e - real:+.1f}s [{flag}]"
                )
                del est[box]
            if not est:
                self._switch_in_pending = None
        except Exception as ex:
            self.log_debug(f"switch-in cd truth log failed: {ex}")
            self._switch_in_pending = None

    def _dump_box_debug(self, box, ocr_cd):
        """诊断(SKILL_CD_DIAG 开关下才调用):把当前在场角色的技能/大招图标(扩到整个圆形)截图存盘,
        文件名带角色名/OCR结果/白占比, 用来采就绪模板或研究就绪/CD区分。节流每角色每 box 1.5s、
        总数封顶。含同步磁盘写, 所以只在开关开启时跑。"""
        try:
            import os

            import cv2

            n = getattr(self, "_box_dbg_n", 0)
            if n >= 300:
                return
            cur = self.get_current_char()
            idx = cur.index
            cname = (getattr(cur, "char_name", "") or type(cur).__name__).replace("/", "_")
            now = time.time()
            times = getattr(self, "_box_dbg_times", None)
            if times is None:
                times = {}
                self._box_dbg_times = times
            key = (idx, box)
            if now - times.get(key, 0) < 1.5:
                return
            times[key] = now
            box_obj = self.get_box_by_name("box_" + box)
            pct = self.calculate_color_percentage(text_white_color, box_obj)
            frame = self.frame
            if frame is None:
                return
            fh, fw = frame.shape[:2]
            cx = box_obj.x + box_obj.width / 2.0
            cy = box_obj.y + box_obj.height / 2.0
            half = box_obj.width * 1.1
            x1, x2 = max(0, int(cx - half)), min(fw, int(cx + half))
            y1, y2 = max(0, int(cy - half)), min(fh, int(cy + half))
            crop = frame[y1:y2, x1:x2]
            if crop is None or crop.size == 0:
                return
            self._box_dbg_n = n + 1
            ocr_tag = f"cd{ocr_cd}" if ocr_cd is not None else "cdNONE"
            d = os.path.join("logs", "box_debug")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(
                d, f"{self._box_dbg_n:04d}_char{idx + 1}_{cname}_{box}_{ocr_tag}_w{pct:.3f}.png"
            )
            cv2.imwrite(path, crop)
        except Exception as e:
            self.log_debug(f"box debug dump failed: {e}")

    def get_cd(self, box_name, char_index=None):
        self.refresh_cd()
        if char_index is None:
            char_index = self.get_current_char().index
        if cds := self.cds.get(char_index):
            if box_name not in cds:
                return self.UNKNOWN_CD_SECONDS
            anchor_time = cds.get(box_name + "_time", cds.get("time"))
            time_elapsed = self.time_elapsed_accounting_for_freeze(anchor_time)
            result = cds[box_name] - time_elapsed
            self._log_cd_estimate(box_name, char_index, cds, result)
            return result
        else:
            return 0

    def _log_cd_estimate(self, box_name, char_index, cds, result):
        """临时诊断:打印技能/大招 CD 时间推算的每个环节,定位推算误差来源。
        节流(每角色每 box 2s 一条)。验证完即删。
        口径与 time_elapsed_accounting_for_freeze 完全一致:
          剩余CD = 锚点CD - (墙钟流逝 - 冻结扣除)
        """
        try:
            now = time.time()
            log_times = getattr(self, "_cd_estimate_log_times", None)
            if log_times is None:
                log_times = {}
                self._cd_estimate_log_times = log_times
            key = (char_index, box_name)
            if now - log_times.get(key, 0) < 2.0:
                return
            log_times[key] = now
            anchor = cds.get(box_name + "_time", cds.get("time", 0))
            raw_elapsed = now - anchor
            anchor_cd = cds.get(box_name, 0)
            parts = []
            to_minus = 0.0
            for fs, dur, ft in self.freeze_durations:
                if anchor < fs:
                    if ft == -100:
                        parts.append(f"入场@{now - fs:.1f}s前(dur{dur:.2f},跳过不扣)")
                        continue
                    deduct = dur - ft
                    to_minus += deduct
                    parts.append(f"@{now - fs:.1f}s前 dur{dur:.2f} 扣{deduct:.2f}")
            detail = "; ".join(parts) if parts else "无"
            on_field = "在场OCR" if raw_elapsed < 1.0 else "下场推算"
            self.log_info(
                f"cd-est char{char_index + 1} {box_name}({on_field}): "
                f"锚CD={anchor_cd:.1f} 锚于{raw_elapsed:.1f}s前 "
                f"墙钟流逝={raw_elapsed:.1f} 冻结扣={to_minus:.2f} "
                f"有效流逝={raw_elapsed - to_minus:.1f} => 剩余CD={result:.1f} "
                f"{'可用' if result <= 0 else '冷却'} | 冻结明细[{detail}]"
            )
        except Exception as e:
            self.log_debug(f"cd estimate log failed: {e}")

    def revive_action(self):
        # TODO: 復活邏輯
        pass

    def raise_not_in_combat(self, message, exception_type=None):
        """抛出未在战斗状态的异常。

        Args:
            message (str): 异常信息。
            exception_type (Exception, optional): 要抛出的异常类型。默认为 NotInCombatException。
        """
        logger.error(message)
        if self.reset_to_false(reason=message):
            logger.error(f"reset to false failed: {message}")
        if exception_type is None:
            exception_type = NotInCombatException
        raise exception_type(message)

    def available(self, name, check_color=True, check_cd=True):
        """检查指定名称的技能或动作是否可用 (通过颜色百分比和冷却时间判断)。

        Args:
            name (str): 技能或动作的名称 (例如 'skill', 'ultimate')。

        Returns:
            bool: 如果可用则返回 True, 否则 False。
        """
        if check_color:
            current = self.box_highlighted(name)
        else:
            current = 1
        if current > 0 and (not check_cd or not self.has_cd(name)):
            return True

    def box_highlighted(self, name):
        current = self.calculate_color_percentage(
            text_white_color, self.get_box_by_name(f"box_{name}")
        )
        if current > 0:
            current = 1
        else:
            current = 0
        return current

    def combat_once(self, wait_combat_time=200, raise_if_not_found=True):
        """执行一次完整的战斗流程。

        Args:
            wait_combat_time (int, optional): 等待进入战斗状态的超时时间 (秒)。默认为 200。
            raise_if_not_found (bool, optional): 如果未找到战斗状态是否抛出异常。默认为 True。
        """
        self.wait_until(
            self.in_combat, time_out=wait_combat_time, raise_if_not_found=raise_if_not_found
        )
        self.reset_unavailable_chars()
        self.load_chars()
        self.switch_to_combat_start_char()
        self.info["Combat Count"] = self.info.get("Combat Count", 0) + 1
        try:
            while self.in_combat():
                logger.debug(f"combat_once loop {self.chars}")
                self.get_current_char().perform()
        except CharDeadException as e:
            raise e
        except NotInCombatException as e:
            logger.info(f"combat_once out of combat break {e}")
        self.combat_end()
        self.wait_in_team_and_world(time_out=10, raise_if_not_found=False)

    def _get_char_log_name(self, char: "BaseChar"):
        from src.char.custom.CustomChar import CustomChar

        if type(char) in (BaseChar, CustomChar):
            return char.char_name
        else:
            return char.name

    def _decide_switch_to(self, current_char: "BaseChar", free_intro=False, require_intro=False):
        has_intro = free_intro or current_char.is_cycle_full()
        switch_to = current_char

        if require_intro and not has_intro:
            return switch_to, has_intro

        max_priority = Priority.MIN

        for char in self.chars:
            if char is None:
                continue
            if char != current_char and self.is_char_unavailable(char):
                logger.debug(f"skip unavailable char {char}")
                continue

            if char == current_char:
                priority = Priority.CURRENT_CHAR
            else:
                priority = char.get_switch_priority(current_char, has_intro)
                logger.debug(f"switch_next_char priority: {char} {priority}")

            if priority > max_priority or (
                priority == max_priority and char.last_perform < switch_to.last_perform
            ):
                if priority == max_priority:
                    logger.debug("switch priority equal, determine by last perform")
                max_priority = priority
                switch_to = char

        if has_intro and max_priority < Priority.FAST_SWITCH:
            # 辅助大招就绪待铺时,先上场铺大招 buff,不被环合反应覆盖
            # (按优先级切到该辅助开大);没有大招待铺时环合照常走。
            if not self._any_support_ultimate_pending(current_char):
                reaction_target = self.find_element_ring_reaction_target(current_char)
                if reaction_target and not self.is_char_unavailable(reaction_target):
                    return reaction_target, has_intro

        return switch_to, has_intro

    def _any_support_ultimate_pending(self, current_char):
        """是否有(非当前场上的)辅助大招就绪待铺,用于让"先铺大招 buff"压过环合反应。"""
        from src.char.MainDps import BuffSupport

        for char in self.chars:
            if char is None or char is current_char:
                continue
            if isinstance(char, BuffSupport) and char.ultimate_buff_pending():
                return True
        return False

    def _committing_to_ready_support(self, switch_to):
        """正在切向的目标若是支援(辅助/治疗),就不让环合在它落地前把它改道走——它既然赢了
        决策被选中切过去,就让它落地放完大招/技能再被抢,避免落地前被薅走形成空切。环合反应
        留到下一次切人再走。决策层优先级不受影响(治疗仍最低,不会越级抢初次决策)。

        注意:不能用 has_confirmed_resource() 判——治疗的资源判定会随别的辅助资源实时翻转,
        切到一半就翻成 False、守卫失效,正是之前没修好的原因。"""
        from src.char.MainDps import BuffSupport

        return isinstance(switch_to, BuffSupport)

    def _find_switch_target(self, current_char: "BaseChar", free_intro=False):
        switch_to_self_count = 0
        while True:
            switch_to, has_intro = self._decide_switch_to(current_char, free_intro)
            if switch_to != current_char:
                return switch_to, has_intro

            switch_to_self_count += 1
            if switch_to_self_count > 5:
                switch_to = safe_get(self.chars, self.get_longest_idle_char_index())
                if switch_to is not None and switch_to != current_char:
                    logger.warning(
                        f"switch_next_char forced to next char {switch_to} "
                        f"after repeated self selection"
                    )
                    return switch_to, has_intro
                return current_char, has_intro

            logger.warning(
                f"{current_char} can't find next char to switch to, "
                "performing too fast add a normal attack"
            )
            current_char.continues_normal_attack(0.2)

    def _set_current_char(self, current_char: "BaseChar | None", switch_to: "BaseChar", has_intro):
        self.in_animation = False
        self.unavailable_char_until.pop(switch_to.index, None)
        self.unavailable_char_failures.pop(switch_to.index, None)
        if current_char:
            current_char.switch_out()
            if has_intro:
                current_char.last_outro_time = time.time()
        switch_to.is_current_char = True
        switch_to.has_intro = has_intro

    def _switch_to_char(
        self,
        switch_to: "BaseChar",
        current_char: "BaseChar | None" = None,
        has_intro=False,
        post_action=None,
        free_intro=False,
        retry_intro=False,
        log_prefix="switch char",
        time_out=10,
    ):
        current_char_name = self._get_char_log_name(current_char) if current_char else "None"
        switch_to.has_intro = has_intro
        last_decide_time = 0.0
        start_time = time.time()

        logger.info(
            f"{log_prefix} {current_char_name} -> {self._get_char_log_name(switch_to)}, "
            f"has_intro {has_intro}"
        )

        while True:
            self.check_combat()
            current_time = time.time()
            switch_to_name = self._get_char_log_name(switch_to)

            if self.is_char_at_index(switch_to.index):
                self._set_current_char(current_char, switch_to, has_intro)
                break

            if (
                retry_intro
                and not has_intro
                and current_time - last_decide_time > 0.12
                and not self._committing_to_ready_support(switch_to)
            ):
                last_decide_time = current_time
                new_switch_to, new_has_intro = self._decide_switch_to(
                    current_char, free_intro, require_intro=True
                )
                if new_has_intro and new_switch_to != current_char:
                    switch_to = new_switch_to
                    has_intro = new_has_intro
                    switch_to.has_intro = True
                    switch_to_name = self._get_char_log_name(switch_to)
                    logger.info(
                        f"{log_prefix} updated target to {switch_to_name}, "
                        f"has_intro {switch_to.has_intro}"
                    )

            if not self.is_in_team():
                logger.info(
                    f"not in world while switching {current_char_name} -> {switch_to_name},"
                    f" {current_time - start_time}"
                )
                if current_time - start_time > self.switch_char_time_out:
                    self.raise_not_in_combat(
                        f"switch too long failed {current_char_name} -> {switch_to_name},"
                        f" {current_time - start_time}"
                    )
                self.sleep(0.01)
                continue

            self.click(action_name="switch_char_click", interval=0.25)
            self.sleep(0.001)
            self.send_key(switch_to.index + 1, action_name="switch_char_send", interval=0.25)

            if current_time - start_time > time_out:
                if self.debug:
                    self.screenshot(f"switch_not_detected_{current_char_name}_to_{switch_to_name}")
                self.mark_char_unavailable(switch_to, f"{log_prefix} failed")
                raise CharUnavailableException(f"{log_prefix} failed {switch_to_name}")

            self.sleep(0.01)

        if has_intro and current_char:
            self.record_element_ring_reaction(current_char, switch_to)

        if post_action:
            logger.debug(f"post_action {post_action}")
            post_action(switch_to, has_intro)

        logger.info(f"{log_prefix} end {(time.time() - start_time):.3f}s")

    def switch_next_char(self, current_char: "BaseChar", post_action=None, free_intro=False):
        """切换到下一个最优角色。

        Args:
            current_char (BaseChar): 当前角色对象。
            post_action (callable, optional): 切换后执行的动作 (回调函数)。默认为 None。
            free_intro (bool, optional): 是否强制认为拥有入场技 (通常在协奏值满时)。默认为 False。
        """
        if self.team_size <= 1:
            self.click(action_name="switch_char_click", interval=0.1)
            return

        current_char.wait_switch_cd()

        switch_to, has_intro = self._find_switch_target(current_char, free_intro)

        if switch_to is None or switch_to == current_char:
            logger.warning(f"{current_char} failed to find a valid switch target")
            return

        self._switch_to_char(
            switch_to,
            current_char=current_char,
            has_intro=has_intro,
            post_action=post_action,
            free_intro=free_intro,
            retry_intro=True,
            log_prefix="switch_next_char",
        )

    def switch_to_combat_start_char(self):
        # 进入/重启战斗(含深渊换层 reload)时,清掉可能从上一场残留的大招动画标志。
        # 否则起始角色已在场时本方法会提前 return,残留的 in_animation=True 会让该角色的
        # click_ultimate 误判"正在大招动画中"、不发招直接空等 unfreeze,卡住十几秒。
        self.in_animation = False
        start_chars = [
            char for char in self.chars if char is not None and getattr(char, "start_combat", False)
        ]
        if not start_chars:
            return

        switch_to = random.choice(start_chars)
        current_char = self.get_current_char(raise_exception=False)
        if current_char == switch_to:
            logger.info(f"combat start char already current {switch_to}")
            return

        self._switch_to_char(
            switch_to,
            current_char=current_char,
            log_prefix="switch to combat start char",
            time_out=self.switch_char_time_out,
        )

    def get_ultimate_key(self):
        """获取终结技技能的按键。

        Returns:
            str: 终结技技能的按键字符串。
        """
        return self.key_config["Ultimate Key"]

    def get_skill_key(self):
        """获取技能的按键。

        Returns:
            str: 技能的按键字符串。
        """
        return self.key_config["Skill Key"]

    def get_arc_key(self):
        """获取弧盘技能的按键。

        Returns:
            str: 弧盘技能的按键字符串。
        """
        return self.key_config["Arc Key"]

    def has_skill_cd(self):
        """检查技能是否在冷却中。

        Returns:
            bool: 如果在冷却中则返回 True, 否则 False。
        """
        return self.has_cd("skill")

    def has_ult_cd(self):
        """检查终结技技能是否在冷却中。

        Returns:
            bool: 如果在冷却中则返回 True, 否则 False。
        """
        return self.has_cd("ultimate")

    def has_cd(self, box_name, char_index=None):
        """检查指定UI区域是否处于冷却状态 (通过检测特定颜色的点和数字)。

        Args:
            box_name (str): UI区域的名称 (例如 'skill', 'ultimate')。

        Returns:
            bool: 如果在冷却中则返回 True, 否则 False。
        """
        return self.get_cd(box_name, char_index) > 0

    def get_current_char(self, raise_exception=False) -> "BaseChar":
        """获取当前操作的角色对象。

        Args:
            raise_exception (bool, optional): 如果找不到当前角色是否抛出异常。默认为 True。

        Returns:
            BaseChar: 当前角色对象 (`BaseChar`) 或 None。
        """
        for char in self.chars:
            if char and char.is_current_char:
                return char
        if raise_exception and not self.in_team()[0]:
            self.raise_not_in_combat("can find current char!!")
        return None

    def _normalize_team_snapshot(self, in_team, current_index, count, source="team"):
        if not in_team or current_index == -1 or count <= 0:
            return None

        if count > 4:
            logger.warning(f"{source} char count {count} larger than 4, set to 4")
            count = 4

        if current_index >= count:
            self.log_info(
                f"{source} invalid team snapshot ignored: "
                f"count {count} current_index {current_index}"
            )
            return None

        return current_index, count

    def _get_valid_team_snapshot(self, source="team", retry=False, reject_snapshot=None):
        end_time = time.perf_counter() + self.LOAD_CHARS_SNAPSHOT_RETRY_WINDOW
        attempt = 0
        while True:
            in_team, current_index, count = self.in_team()
            snapshot = self._normalize_team_snapshot(in_team, current_index, count, source=source)
            if snapshot is not None and not (reject_snapshot and reject_snapshot(snapshot)):
                if attempt:
                    self.log_info(f"{source} valid snapshot recovered after {attempt} retries")
                return snapshot

            if not retry or time.perf_counter() >= end_time:
                return None

            attempt += 1
            time.sleep(self.LOAD_CHARS_SNAPSHOT_RETRY_INTERVAL)

    def combat_end(self):
        """战斗结束时调用的清理方法。"""
        SoundCombatContext().clear_task_if(self)

        current_char = self.get_current_char(raise_exception=False)
        if current_char:
            self.get_current_char().on_combat_end(self.chars)

    def sleep_check(self):
        if self.skip_sleep_check:
            return

        if SoundCombatContext.should_interrupt_combat():
            self.log_info("Combat sleep interrupted by sound action")
            SoundCombatContext().execute_pending_action()
            SoundCombatContext.wait_for_resume()

        if self._in_combat:
            self.check_team_changed_during_combat()
            self.next_frame()
            if not self.in_combat():
                self.raise_not_in_combat("sleep check not in combat")

    def check_team_changed_during_combat(self, force=False):
        if (
            not self._in_combat
            or self.team_size <= 0
            or self._team_change_checking
            or self.in_sleep_check
        ):
            return False

        now = time.time()
        if not force and now - self._last_team_change_check < self.TEAM_CHANGE_CHECK_INTERVAL:
            return False
        self._last_team_change_check = now

        self._team_change_checking = True
        previous_skip_sleep_check = self.skip_sleep_check
        self.skip_sleep_check = True
        try:
            in_team, current_index, count = self.in_team()
        finally:
            self.skip_sleep_check = previous_skip_sleep_check
            self._team_change_checking = False

        snapshot = self._normalize_team_snapshot(
            in_team, current_index, count, source="team change check"
        )
        if snapshot is None:
            self._pending_team_change = None
            return False

        current_index, count = snapshot
        if count == self.team_size:
            self._pending_team_change = None
            return self.check_team_signature_changed_during_combat(now)

        previous = self._pending_team_change
        if previous is None or previous[0] != count:
            self._pending_team_change = (count, now)
            self.log_info(f"team size change candidate during action {self.team_size} -> {count}")
            return False

        if now - previous[1] < self.TEAM_CHANGE_CONFIRM_INTERVAL:
            return False

        if count > self.team_size and not self.is_reliable_team_expansion(count):
            self._pending_team_change = None
            self.log_info(
                f"team size expansion ignored because added slots are unknown "
                f"{self.team_size} -> {count}"
            )
            return False

        self._pending_team_change = None
        self.log_info(f"team size changed during action {self.team_size} -> {count}")
        raise TeamChangedException(f"team size changed {self.team_size} -> {count}")

    def check_team_signature_changed_during_combat(self, now=None):
        now = now or time.time()
        if now - self._last_team_signature_check < self.TEAM_SIGNATURE_CHECK_INTERVAL:
            return False
        self._last_team_signature_check = now

        manager = CustomCharManager()
        mismatches = []
        verified = 0
        frame = self.frame

        for char in self.chars:
            if char is None or not char.char_name or char.char_name == "unknown":
                continue

            char_info = manager.get_character_info(char.char_name) or {}
            if not char_info.get("feature_ids"):
                continue

            mat = self.get_char_box(char.index).scale(1.1, 1.1).crop_frame(frame)
            if mat is None or mat.size == 0:
                continue

            verified += 1
            is_match, match_name, confidence = manager.match_feature(
                self,
                mat,
                threshold=self.TEAM_SIGNATURE_MATCH_THRESHOLD,
                target_char=char.char_name,
            )
            if not is_match or match_name != char.char_name:
                mismatches.append((char.index, char.char_name, confidence))

        if not verified:
            self._pending_team_signature_change = None
            return False

        if not mismatches:
            self._pending_team_signature_change = None
            return False

        signature = tuple((index, name) for index, name, _ in mismatches)
        previous = self._pending_team_signature_change
        if previous is None or previous[0] != signature:
            self._pending_team_signature_change = (signature, now)
            mismatch_text = ", ".join(
                f"{index + 1}:{name}({confidence:.2f})"
                for index, name, confidence in mismatches
            )
            self.log_info(f"team signature change candidate during action {mismatch_text}")
            return False

        if now - previous[1] < self.TEAM_SIGNATURE_CONFIRM_INTERVAL:
            return False

        self._pending_team_signature_change = None
        self.log_info(f"team signature changed during action {signature}")
        raise TeamChangedException("team signature changed")

    def _apply_sound_config(self):
        if self.sound_config:
            enable = self.sound_config.get("Enable Sound Trigger", True)
            dodge_all_attacks = self.sound_config.get("Dodge All Attacks", True)
            dodge_thresh = self.sound_config.get("Dodge Threshold", 0.13)
            counter_thresh = self.sound_config.get("Counter Attack Threshold", 0.12)
            dodge_thresh = np.clip(dodge_thresh, 0.0, 1.0)
            counter_thresh = np.clip(counter_thresh, 0.0, 1.0)
            SoundCombatContext().update_config(
                enable, dodge_all_attacks, dodge_thresh, counter_thresh
            )
        SoundCombatContext().update_task(self)

    def check_combat(self):
        """检查当前是否处于战斗状态, 如果不是则抛出异常。"""
        self.check_team_changed_during_combat()
        if self._in_combat and not self.in_combat():
            # if self.debug:
            #     self.screenshot('not_in_combat_calling_check_combat')
            self.raise_not_in_combat("combat check not in combat")

    def set_key(self, key, box):
        best = self.find_best_match_in_box(box, ["t", "e", "r", "q"], threshold=0.7)
        logger.debug(f"set_key best match {key}: {best}")
        if best and best.name != self.key_config[key]:
            self.key_config[key] = best.name
            self.log_info(f"set_key {key} to {best.name}")

    def load_hotkey(self):
        """加载游戏内技能热键。"""
        for key, value in self.key_config.items():
            self.info_set(key, value)
        return self.key_config

    def has_char(self, char_cls):
        for char in self.chars:
            if isinstance(char, char_cls):
                return char

    def _do_load_char(self, index: int, fixed_slots) -> "BaseChar":
        fixed_slot = safe_get(fixed_slots, index)
        fixed_char_name = ""
        fixed_combo_ref = ""
        if isinstance(fixed_slot, dict):
            fixed_char_name = str(fixed_slot.get("char_name", "") or "").strip()
            fixed_combo_ref = str(fixed_slot.get("combo_ref", "") or "").strip()

        if fixed_char_name:
            self.log_debug(
                f"load_chars use fixed slot {index + 1}: {fixed_char_name} {fixed_combo_ref}"
            )
            return get_char_by_name(
                self, index, fixed_char_name, confidence=1, combo_ref=fixed_combo_ref
            )

        box_scaled = self.get_char_box(index).scale(1.1, 1.1)

        return get_char_by_pos(self, box_scaled, index, safe_get(self.chars, index))

    def _fixed_slot_has_char(self, fixed_slots, index: int) -> bool:
        fixed_slot = safe_get(fixed_slots, index)
        if not isinstance(fixed_slot, dict):
            return False
        return bool(str(fixed_slot.get("char_name", "") or "").strip())

    def _is_unknown_char(self, char: "BaseChar") -> bool:
        return type(char) is BaseChar and char.char_name == "unknown"

    def _get_fixed_slots(self):
        fixed_team = CustomCharManager().get_fixed_team()
        return fixed_team.get("slots", []) if fixed_team.get("enabled", False) else []

    def _is_weak_single_unknown_team(self, chars: list["BaseChar"], fixed_slots) -> bool:
        if len(chars) != 1 or self._fixed_slot_has_char(fixed_slots, 0):
            return False
        char = chars[0]
        return self._is_unknown_char(char)

    def _is_weak_unknown_expansion(
        self,
        chars: list["BaseChar"],
        fixed_slots,
        previous_count: int,
    ) -> bool:
        if previous_count <= 0 or len(chars) <= previous_count:
            return False
        for index in range(previous_count, len(chars)):
            if not self._fixed_slot_has_char(fixed_slots, index) and self._is_unknown_char(
                chars[index]
            ):
                return True
        return False

    def is_reliable_team_expansion(self, count: int) -> bool:
        fixed_slots = self._get_fixed_slots()
        for index in range(self.team_size, count):
            if self._fixed_slot_has_char(fixed_slots, index):
                continue
            char = self._do_load_char(index, fixed_slots)
            if self._is_unknown_char(char):
                return False
        return True

    def _commit_loaded_chars(self, chars: list["BaseChar"], current_index: int):
        self._pending_team_change = None
        self._pending_team_signature_change = None
        self._last_team_change_check = 0.0
        self._last_team_signature_check = 0.0
        self.clear_element_ring_reactions()
        elements = [char.element for char in chars]
        self.chars = chars
        self.info_set("char elements", elements)

        healer_count = 0
        self.info_set("chars", [])
        for char in self.chars:
            if char is not None:
                char.reset_state()
                if isinstance(char, Healer):
                    healer_count += 1
                char.is_current_char = char.index == current_index
                name = char.char_name
                conf = char.confidence
                elem = char.element
                self.log_info(f"load char success {char} {name} {conf:.2f} {elem}")
                self.info_add_to_list("chars", f"{char.char_name}: {char.combo_label}")

        if self.team_size > 0:
            self.combat_start = time.time()
            self._apply_sound_config()
            return True
        return False

    def load_chars(self, preserve_on_weak=True) -> bool:
        """加载队伍中的角色信息。"""
        ret = False
        now = time.perf_counter()
        self.load_hotkey()
        snapshot = self._get_valid_team_snapshot(source="load_chars", retry=True)
        if snapshot is None:
            return ret

        current_index, count = snapshot
        self.log_info(f"load_chars count {count} current_index {current_index}")

        fixed_slots = self._get_fixed_slots()
        resnap_weak_single_unknown = True
        while True:
            restart_with_new_snapshot = False
            for attempt in range(self.LOAD_CHARS_WEAK_RETRY + 1):
                new_chars = []
                indices_to_detect = []
                for i in range(count):
                    char = self._do_load_char(i, fixed_slots)
                    new_chars.append(char)
                    if char.element is Element.DEFAULT:
                        indices_to_detect.append(i)

                if indices_to_detect:
                    detected_elements = self.load_chars_element(indices_to_detect)
                    for i in indices_to_detect:
                        new_chars[i].element = detected_elements.get(i, Element.DEFAULT)

                weak_single_unknown = self._is_weak_single_unknown_team(new_chars, fixed_slots)
                if weak_single_unknown and resnap_weak_single_unknown:
                    resnap_weak_single_unknown = False
                    recovered_snapshot = self._get_valid_team_snapshot(
                        source="load_chars weak single unknown",
                        retry=True,
                        reject_snapshot=lambda team_snapshot: team_snapshot[1] == 1,
                    )
                    if recovered_snapshot is not None:
                        current_index, count = recovered_snapshot
                        self.log_info(
                            f"load_chars weak single unknown recovered team snapshot "
                            f"count {count} current_index {current_index}"
                        )
                        restart_with_new_snapshot = True
                        break

                weak_unknown_expansion = self._is_weak_unknown_expansion(
                    new_chars,
                    fixed_slots,
                    previous_count=self.team_size,
                )
                if (weak_single_unknown or weak_unknown_expansion) and attempt < self.LOAD_CHARS_WEAK_RETRY:
                    self.log_info(
                        f"load_chars weak unknown retry {attempt + 1}/{self.LOAD_CHARS_WEAK_RETRY}"
                    )
                    time.sleep(self.LOAD_CHARS_WEAK_RETRY_INTERVAL)
                    continue

                if weak_single_unknown and preserve_on_weak and self.chars:
                    self.log_info("load_chars weak single unknown ignored, keep previous team")
                    ret = False
                    break

                if weak_unknown_expansion and preserve_on_weak and self.chars:
                    self.log_info("load_chars weak unknown expansion ignored, keep previous team")
                    ret = False
                    break

                ret = self._commit_loaded_chars(new_chars, current_index)
                break

            if restart_with_new_snapshot:
                continue
            break

        logger.debug(f"load_chars cost {time.perf_counter() - now:.3f}s")
        return ret

    def load_chars_element(self, indices: List[int]) -> dict:
        def preprocess_image(image):
            return iu.binarize_bgr_by_adaptive_center(image)

        def process_transparency(img):
            """
            如果图片有透明通道，将其转为黑色背景
            """
            if img.shape[2] == 4:
                b, g, r, a = cv2.split(img)
                black_bg = np.zeros_like(img[:, :, :3])
                alpha_factor = a.astype(float) / 255.0
                alpha_factor = cv2.merge([alpha_factor, alpha_factor, alpha_factor])

                foreground = cv2.merge([b, g, r]).astype(float)
                background = black_bg.astype(float)

                final_img = cv2.add(
                    cv2.multiply(foreground, alpha_factor),
                    cv2.multiply(background, 1.0 - alpha_factor),
                )
                return final_img.astype(np.uint8)
            return img

        results = {}
        target_elements = [
            Element.BLUE,
            Element.GREEN,
            Element.RED,
            Element.PURPLE,
            Element.YELLOW,
            Element.WHITE,
        ]

        base_box = self.get_base_char_element_box()

        if not self._element_template_cache:
            element_scale = 0.5
            for element in target_elements:
                raw_template = cv2.imread(
                    f"assets/esper_icons/{element.value}.png", cv2.IMREAD_UNCHANGED
                )
                if raw_template is not None:
                    h, w = raw_template.shape[:2]
                    raw_template = process_transparency(raw_template)
                    raw_template = cv2.resize(
                        raw_template,
                        (int(w * element_scale), int(h * element_scale)),
                        interpolation=cv2.INTER_NEAREST,
                    )
                    template_bin = preprocess_image(raw_template)
                    _, mask = cv2.threshold(template_bin, 127, 255, cv2.THRESH_BINARY)
                    kernel = np.ones((30, 30), np.uint8)
                    mask = cv2.dilate(mask, kernel, iterations=1)
                    # iu.show_images([mask], [f"mask_{element}"])
                    self._element_template_cache[element] = (raw_template, mask)

        _frame = self.frame
        # self.screenshot("load_chars_element", _frame)

        for i in indices:
            base_scale = 8
            scale = base_scale * 1440 / self.height
            current_box = self.get_box_by_char_spacing(base_box, i)
            crop_img = current_box.crop_frame(_frame)
            crop_h, crop_w = crop_img.shape[:2]
            crop_resized = cv2.resize(
                crop_img,
                (int(crop_w * scale), int(crop_h * scale)),
                interpolation=cv2.INTER_NEAREST,
            )
            # iu.show_images([crop_resized, crop_img], [f"crop_resized_{i}", f"crop_img_{i}"])

            best_element = Element.DEFAULT
            max_score = -1.0

            for element in target_elements:
                template_data = self._element_template_cache.get(element)
                if template_data is None:
                    continue
                template_img, template_mask = template_data

                match_score = 0
                if crop_resized is not None and template_img is not None:
                    res = cv2.matchTemplate(
                        crop_resized, template_img, cv2.TM_CCOEFF_NORMED, mask=template_mask
                    )
                    res[np.isinf(res)] = 0
                    _, match_score, _, _ = cv2.minMaxLoc(res)

                if match_score > max_score:
                    max_score = match_score
                    best_element = element

            current_box.confidence = max_score
            current_box.name = best_element.name
            results[i] = best_element
            self.draw_boxes(boxes=current_box, color="red")
            self.log_debug(
                f"char_{i + 1} identified as {best_element.name} (score: {max_score:.4f})"
            )

        return results

    def is_cycle_full(self) -> bool:
        img = self.box_of_screen_scaled(
            2560, 1440, 944, 1316, width_original=66, height_original=66
        ).crop_frame(self.frame)
        h, w = img.shape[:2]
        side = h

        # 1. 预处理：灰度化 + 二值化
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

        # 2. 构造环形掩模 (Mask) —— 进一步排除干扰
        # 环厚度约 12%，我们可以只看这个半径范围内的像素
        mask = np.zeros((h, w), dtype=np.uint8)
        center = (w // 2, h // 2)
        outer_r = side // 2
        inner_r = int(outer_r * (1 - 0.15))  # 稍微多给一点余量，取15%
        cv2.circle(mask, center, outer_r, 255, -1)
        cv2.circle(mask, center, inner_r, 0, -1)

        # 应用掩模，只保留环形区域
        ring_only = cv2.bitwise_and(thresh, thresh, mask=mask)

        # 3. 取样区定义 (核心：对比顶部和底部)
        # 取顶部中心 10%x10% 的区域，以及底部中心同样的区域
        roi_size = int(side * 0.1)
        margin = int(side * 0.02)  # 避开最边缘可能存在的黑边

        # 顶部采样区 (12点钟方向)
        top_roi = ring_only[
            margin : margin + roi_size, (w // 2 - roi_size // 2) : (w // 2 + roi_size // 2)
        ]

        # 底部采样区 (6点钟方向)
        bottom_roi = ring_only[
            (h - margin - roi_size) : (h - margin),
            (w // 2 - roi_size // 2) : (w // 2 + roi_size // 2),
        ]

        # 4. 计算白色像素密度
        top_density = np.sum(top_roi == 255)
        bottom_density = np.sum(bottom_roi == 255)

        # 5. 精准判断逻辑
        # 如果满了，top_density 应该和 bottom_density 非常接近
        # 如果没满（有缺口），top_density 会显著低于 bottom_density
        if bottom_density == 0:
            return False  # 防止除以0

        ratio = top_density / bottom_density

        # 阈值建议：如果 ratio > 0.9，认为已经满了
        # “差一点点”的时候，由于缺口正好在顶部，这个 ratio 会瞬间降到 0.5 以下甚至更低
        is_full = ratio > 0.9

        return is_full

    def walk_until_combat(
        self, direction="w", time_out=10, run=False, delay=0, raise_if_not_found=False
    ):
        ret = False
        try:
            self.middle_click(after_sleep=0.2)
            self.send_key_down(direction)
            if run:
                self.sleep(0.1)
                self.send_key_down("lshift")
            ret = bool(
                self.wait_until(
                    self.in_combat,
                    time_out=time_out,
                    raise_if_not_found=raise_if_not_found,
                )
            )
            self.sleep(delay)
        finally:
            if run:
                self.send_key_up("lshift")
                self.sleep(0.1)
            self.send_key_up(direction)
        return ret


def convert_cd(text):
    """
    Strips a string to only keep the first part that matches the regex pattern.
    Args:
      text: The input string.
      pattern: The regex pattern to match.
    Returns:
      The first matching substring, or None if no match is found.
    """
    try:
        return float(text.name)
    except ValueError:
        match = re.search(cd_regex, text.name)
        if match:
            return float(match.group(0))
        else:
            return 1
