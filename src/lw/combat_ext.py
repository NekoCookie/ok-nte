# [lw] BaseCombatTask 的用户扩展: 技能CD锚定/OCR就绪判定、角色不可用标记、
# 队伍变更检测、切换决策诊断、队伍快照/弱识别重试等。
# 接线: class BaseCombatTask(CombatExtMixin, CombatCheck)。
# 注: CharUnavailableException/TeamChangedException 因继承 NotInCombatException
# 仍定义在 BaseCombatTask.py(带 [lw] 标记), 本文件方法内用局部 import 引用。
import time
from typing import TYPE_CHECKING

import cv2
import numpy as np
from ok import Logger, safe_get

from src import text_white_color
from src.char.BaseChar import BaseChar, Element
from src.lw.legacy_priority import Priority  # [lw] 上游已移除, 迁移到 src/lw/
from src.char.custom.CustomCharManager import CustomCharManager
from src.char.Healer import Healer
from src.sound_trigger.SoundCombatContext import SoundCombatContext
from src.utils import game_filters as gf

if TYPE_CHECKING:
    from src.combat.BaseCombatTask import BaseCombatTask

    _TaskProxy = BaseCombatTask
else:

    class _TaskProxy:
        pass


logger = Logger.get_logger(__name__)


class CombatExtMixin(_TaskProxy):
    # 策略开关: True=走本文件的龙威实现, False=走上游原版(留在 BaseCombatTask.py 里, 仅排查对照用)。
    # 注意: settle 结算/主C资源判定依赖 lw 锚定写入的字段(skill_ocr_raw 等), 关掉后这些会退化,
    # 只应在"怀疑 lw 逻辑自身有问题、想和原版对照"时临时关闭。
    LW_CD_ANCHORING = True
    LW_LOAD_CHARS = True
    LW_SWITCH_DECIDE = True
    LW_COMBAT_RUN = True

    # 锚定技能/大招 CD 时, 若 OCR 读不到数字且图标不亮(无旧锚点)的保守占位:
    # 当成仍在冷却, 宁可多冷却也不误判可用(避免空切)。
    UNKNOWN_CD_SECONDS = 20.0
    SKILL_CAST_READY_GRACE = 2.0  # 放完技能后 N 秒内, "图标就绪"必为坏帧, 不许冲掉刚锚的CD(过渡态撑不到2s)
    # 技能"连续没数字才判就绪"的平时去抖窗。OCR 数字识别可靠: 在CD时几乎每帧都有数字, 只偶发漏帧;
    # 真就绪才会持续没数字。故没读到数字时, 连续没数字 < 此值当偶发坏帧(保留锚点倒数), >= 才判就绪。
    # 放招后那段(grace 内)数字滞后更久, 用 SKILL_CAST_READY_GRACE 这个更长的窗口顶, 防滞后被误判就绪→空切。
    READY_NO_NUMBER_DEBOUNCE = 0.5
    # 技能就绪模板匹配阈值: OCR 读不到数字时, 拿当前技能图标和该角色"就绪模板"带遮罩匹配,
    # 置信度 >= 此值判就绪(锚 0)。实测就绪 0.95~1.00 / CD 0.07~0.22, 0.7 两边大余量。
    SKILL_READY_TEMPLATE_THRESHOLD = 0.7
    # CD 诊断开关: 平时 False(不影响实战); 想观察"切早/切晚/空切"或采技能样本时翻成 True。
    # 开启后会打 cd-truth 切上场对照日志, 并把技能图标存到 logs/box_debug(含同步磁盘写)。
    SKILL_CD_DIAG = True

    LOAD_CHARS_WEAK_RETRY = 2
    LOAD_CHARS_WEAK_RETRY_INTERVAL = 0.25
    # 需覆盖开战入场动画(~1.5s), 期间队伍栏头像识别不全会得到无效快照
    LOAD_CHARS_SNAPSHOT_RETRY_WINDOW = 2.5
    LOAD_CHARS_SNAPSHOT_RETRY_INTERVAL = 0.08
    TEAM_CHANGE_CHECK_INTERVAL = 0.3
    TEAM_CHANGE_CONFIRM_INTERVAL = 0.8
    TEAM_SIGNATURE_CHECK_INTERVAL = 1.0
    TEAM_SIGNATURE_CONFIRM_INTERVAL = 0.5
    TEAM_SIGNATURE_MATCH_THRESHOLD = 0.6
    CHAR_UNAVAILABLE_BASE_COOLDOWN = 8.0
    CHAR_UNAVAILABLE_MAX_COOLDOWN = 30.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 用户字段集中在这里初始化(MRO 上游类的 super().__init__ 会路过本方法),
        # 上游 __init__ 里不留任何用户行。
        self._last_team_change_check = 0.0
        self._last_team_signature_check = 0.0
        self._pending_team_change = None
        self._pending_team_signature_change = None
        self._team_change_checking = False
        self.unavailable_char_until = {}
        self.unavailable_char_failures = {}
        self._last_team_recheck = 0.0  # AutoCombatTask 的队伍重载节流
        self._pending_team_shrink = None  # 主循环减员二次确认的候选(count, 首次检测时刻)

    # ---------- 角色不可用标记 ----------

    def reset_unavailable_chars(self):
        self.unavailable_char_until.clear()
        self.unavailable_char_failures.clear()

    def is_char_unavailable(self, char: "BaseChar | None") -> bool:
        if char is None:
            return False
        if getattr(char, "is_dead", False):  # 吸收上游fb360f3: 死亡角色也视为不可用
            return True
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

    # ---------- 闪避/放招诊断 ----------

    def last_dodge_time(self):
        """最近一次闪避(我方主动触发)的时刻; 没有则 0。供战斗循环判断"刚是否闪避了"。"""
        return SoundCombatContext().last_dodge_time()

    def diag_cast(self, char_index, cast_at, tag):
        """放招诊断(临时, 验证完删): 专门盯三条未实战验证的路径——真技能被闪避打断→重试、
        放招后留场读CD、辅助技能差就绪等待。打印: 角色、走了哪条分支(tag)、当前技能图标
        CD读数、最近闪避相对本次放招(cast_at)的时刻(标出是否邻近)。前缀 [放招诊断] 便于 grep。"""
        dodge_at = self.last_dodge_time()
        rel = dodge_at - cast_at if cast_at else None
        if rel is not None and -0.5 <= rel < 2.5:
            near = f"闪避@放招后{rel:+.2f}s"
        else:
            near = "无邻近闪避"
        cd = self.get_cd("skill", char_index)
        self.log_info(f"[放招诊断] char{char_index + 1} {tag} | 图标CD={cd:.1f}s | {near}")

    def flush_pending_dodge(self):
        """把声音线程已触发、但还排在队列里没执行的闪避立即落地, 使 last_dodge_time 更新。
        供 settle 在判"放招后是否闪避"前调用: 否则"放招→闪避(还pending)→切人"贴太紧时,
        闪避执行被排在判定之后, last_dodge_time 尚未更新 → settle 漏看这次闪避(哈尼娅实测)。
        若 pending 是反击(counter)而非闪避, 执行后 last_dodge_time 不更新, settle 仍不介入。"""
        if SoundCombatContext.should_interrupt_combat():
            SoundCombatContext().execute_pending_action()

    def after_dodge_executed(self):
        """闪避在主线程执行完(键已按下)后的钩子: 当前在场角色若定义了 on_dodge_counter
        (目前仅安魂曲)就调用它强制平A打出闪避反击; 其它角色无此方法则不做。
        由 DodgeCounterTrigger.execute_dodge 在闪避键按下后同步调用(主线程内)。"""
        char = self.get_current_char(raise_exception=False)
        hook = getattr(char, "on_dodge_counter", None)
        if hook is not None:
            try:
                hook()
            except Exception as e:
                self.log_error(f"on_dodge_counter failed: {e}")

    # ---------- 技能CD锚定 / OCR就绪判定 ----------

    def lw_refresh_cd(self):
        """refresh_cd 的龙威实现(BaseCombatTask.refresh_cd 按 LW_CD_ANCHORING 分发到这里):
        OCR 读数为主判据 + 图标/模板兜底 + 去抖/grace, 每 box 独立锚点时间。"""
        from src.combat.BaseCombatTask import cd_regex, convert_cd

        if self.scene.cd_refreshed:
            return
        # 上游get_current_char默认语义反转(旧: 默认raise; 新: 默认返回None), 显式raise保持旧行为,
        # 否则识别丢当前角色的瞬间这里会变成未捕获的NoneType.index而非可被战斗循环接住的NotInCombat
        index = self.get_current_char(raise_exception=True).index
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
            # 只截技能图标做诊断;大招走头像菱形稳定判定、不靠这套, 截了纯属浪费。
            if self.SKILL_CD_DIAG and box == "skill":
                self._dump_box_debug(box, ocr_cd)
            # 记下这一帧 OCR 的原始读数(None=没读到数字), 供 settle / 真技能判定不受 note 标称CD 污染地判进CD/就绪。
            cds[box + "_ocr_raw"] = ocr_cd
            if ocr_cd is not None:
                # 读到数字 = 在CD, 数字即剩余CD(OCR 数字识别可靠, 作主判据)。
                # 闪避打断检测: 放招刚锚了标称大CD, 但图标紧接着读到明显更短的CD = 技能被打断、
                # 没真放(进短CD ~3s)。闪避是我方主动触发(记了时刻), 所以用"放招后是否真闪避了"
                # 确定性确认, 图标短CD作实证, 不靠动画/猜测。
                noted = cds.get(box)
                cast_at = cds.get("skill_cast_at", 0)
                if (
                    box == "skill"
                    and 0 < now - cast_at < 2.5
                    and isinstance(noted, (int, float))
                    and ocr_cd < noted - 5
                ):
                    dodge_at = SoundCombatContext().last_dodge_time()
                    dodged = cast_at < dodge_at <= now
                    extra = f"(闪避@放招后{dodge_at - cast_at:.2f}s)" if dodged else ""
                    self.log_info(
                        f"技能被打断: char{index + 1} 放招锚{noted:.0f}s 图标实读{ocr_cd:.1f}s "
                        f"(没真放, 约{ocr_cd:.0f}s后可重放) | 闪避确认={dodged}{extra}"
                    )
                cds[box] = ocr_cd
                cds[box + "_time"] = now
                cds.pop(box + "_no_number_since", None)  # 读到数字 → 清空"连续没数字"计时
            elif box == "skill":
                # 技能没读到数字: 不再靠每角色就绪模板/图标高亮(高亮按"有白色像素"判, 会被CD白字骗→
                # 安魂曲进CD也误判就绪)。改成"连续没数字够久才算就绪": 数字识别可靠→在CD几乎每帧有数字、
                # 只偶发漏帧, 真就绪才持续没数字。去抖窗放招后(grace内)取更长的 grace(挡放招后数字滞后,
                # 别把刚放出的技能误判就绪→空切), 平时取短的 READY_NO_NUMBER_DEBOUNCE。
                since = cds.get("skill_no_number_since")
                if since is None:
                    since = now
                    cds["skill_no_number_since"] = now
                if "skill" not in cds:
                    # 首次见该角色且没数字: 没历史可做"连续没数字"去抖, 用图标兜一帧定调
                    # (就绪→锚0; 否则占位冷却, 下一帧读到数字再校准)。仅这一帧用图标, 之后走去抖。
                    cds["skill"] = 0 if self._box_ready_no_number("skill") else self.UNKNOWN_CD_SECONDS
                    cds["skill_time"] = now
                else:
                    in_post_cast = 0 < now - cds.get("skill_cast_at", 0) < self.SKILL_CAST_READY_GRACE
                    debounce = self.SKILL_CAST_READY_GRACE if in_post_cast else self.READY_NO_NUMBER_DEBOUNCE
                    if now - since >= debounce:
                        cds["skill"] = 0
                        cds["skill_time"] = now
                    # else: 没数字但没到去抖窗 → 保留上次锚点继续倒数(偶发坏帧, 不动)
            elif self._box_ready_no_number(box):
                # 大招(ultimate): 维持原"图标就绪→锚0"判定(大招走头像菱形那条线, 不改)。
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

    def note_skill_on_cd(self, char_index, cd=None):
        """角色主动放出技能后, 当场把技能锚点设成"在冷却"并开始倒计时(保守占位 UNKNOWN_CD_SECONDS,
        或传入已知CD)。修复"放完技能不算CD、等后续OCR才倒计时"的不合理:放完即走、OCR没读到
        新CD时, 锚点不再残留"就绪"撒谎。下次该角色在场时 OCR 会读到真实CD重锚、修正这个占位。"""
        cds = self.cds.get(char_index)
        if cds is None:
            cds = {}
            self.cds[char_index] = cds
        cds["skill"] = cd if cd is not None else self.UNKNOWN_CD_SECONDS
        cds["skill_time"] = time.time()
        cds["skill_cast_at"] = cds["skill_time"]  # grace 标记: 刚放完, refresh 不许把它冲成就绪
        # 重置"连续没数字"去抖计时: 放招前技能就绪时 since 已累计了几秒且只在读到数字时才清,
        # 若不清, 放招后第一帧没数字(OCR约1s滞后)就会 now-since>>grace 立刻触发 → 把刚锚的CD
        # 冲回就绪(0) → 下场推算恒可用 → 空切。清掉后去抖从放招后重新起算, grace 才真正生效。
        cds.pop("skill_no_number_since", None)

    def note_skill_ready(self, char_index):
        """把技能锚点设成"就绪/可用"(CD=0)。用于放招后被闪避打断、补放仍没放出去时——
        别留标称CD(20s)撒谎, 锚成就绪让下场判它可用、下次再上来放。清掉 skill_cast_at,
        否则 grace 会把这个本就该就绪的锚点又保护成"刚放完不许就绪"。"""
        cds = self.cds.get(char_index)
        if cds is None:
            cds = {}
            self.cds[char_index] = cds
        cds["skill"] = 0
        cds["skill_time"] = time.time()
        cds.pop("skill_cast_at", None)

    def skill_ocr_raw(self, char_index=None):
        """当前帧 OCR 对技能格读到的原始 CD 数字(None=没读到数字=就绪/坏帧)。
        不经锚点推算、不受 note_skill_on_cd 刚锚的标称CD 污染——专供 settle / 真技能判定
        确定"这一下到底进没进CD": 读到有意义数字才是真进了CD, 没数字就是没放成/还就绪。"""
        self.refresh_cd()
        if char_index is None:
            char_index = self.get_current_char(raise_exception=True).index  # 同lw_refresh_cd: 保持旧版raise语义
        return self.cds.get(char_index, {}).get("skill_ocr_raw")

    # ---------- CD 诊断(SKILL_CD_DIAG) ----------

    def _capture_switch_in_estimate(self, index, cds):
        """临时诊断:切上场瞬间,用覆盖前的下场锚点算出"下场最后推算 CD",挂起待对照。验证完即删。"""
        try:
            est = {}
            for box in ("skill", "ultimate"):
                if box in cds and (box + "_time") in cds:
                    elapsed = self.time_elapsed_accounting_for_freeze(cds[box + "_time"])
                    est[box] = cds[box] - elapsed
            self._switch_in_pending = {"index": index, "est": est, "at": time.time()} if est else None
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
                    # 切入后该角色自己把技能放出去了(skill_cast_at 晚于切入时刻)→ 推算"可用"其实是对的,
                    # "在场真实"读到的是它自己放招后的CD, 不是切入前就存在的CD → 不是空切(诊断读基线读晚了)。
                    cast_at = cds.get(box + "_cast_at", 0)
                    cast_after_switch_in = box == "skill" and cast_at >= pending.get("at", 0)
                    # 主C overlap 强制切人拉上来的(非因资源)→ 不算CD误报, 单独标注。
                    if box == "skill" and self.main_dps_overlapping():
                        flag = "overlap切人(主C真技能强制切, 非CD误)"
                    elif cast_after_switch_in:
                        flag = "准(切入即放招: 推算可用且已放出, 非空切)"
                    else:
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

            n = getattr(self, "_box_dbg_n", 0)
            if n >= 300:
                return
            cur = self.get_current_char()
            idx = cur.index
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
            # 时间戳(对得上日志的 cd-truth/freeze 记录) + 切上场前的缓存锚CD(一眼看 OCR vs 锚点)。
            ts = time.strftime("%H-%M-%S", time.localtime(now)) + f"-{int((now % 1) * 1000):03d}"
            prev = self.cds.get(idx, {}).get(box)
            anchor_tag = f"a{prev:.1f}" if isinstance(prev, (int, float)) else "aNA"
            d = os.path.join("logs", "box_debug")
            os.makedirs(d, exist_ok=True)
            # 去掉角色中文名(cv2 写非ASCII路径会乱码), 角色用 charN 标识即可。
            path = os.path.join(
                d,
                f"{self._box_dbg_n:04d}_{ts}_char{idx + 1}_{box}_{ocr_tag}_{anchor_tag}_w{pct:.3f}.png",
            )
            ok, buf = cv2.imencode(".png", crop)
            if ok:
                buf.tofile(path)
        except Exception as e:
            self.log_debug(f"box debug dump failed: {e}")

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
            for item in self.freeze_durations:
                fs, dur, ft = item[0], item[1], item[2]
                cause = item[3] if len(item) > 3 else ""
                if anchor < fs:
                    if ft == -100:
                        parts.append(f"入场/环合@{now - fs:.1f}s前(dur{dur:.2f},跳过不扣)[{cause}]")
                        continue
                    deduct = dur - ft
                    to_minus += deduct
                    parts.append(f"@{now - fs:.1f}s前 dur{dur:.2f} 扣{deduct:.2f}[{cause}]")
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

    # ---------- 切换决策辅助 ----------

    def lw_decide_switch_to(self, current_char: "BaseChar", free_intro=False, require_intro=False):
        """_decide_switch_to 的龙威实现(按 LW_SWITCH_DECIDE 分发到这里):
        跳过不可用角色 + 切换决策诊断 + 辅助大招待铺时压过环合反应。"""
        has_intro = free_intro or current_char.is_cycle_full()
        switch_to = current_char

        if require_intro and not has_intro:
            return switch_to, has_intro

        max_priority = Priority.MIN

        # 只在主决策打(retry_intro 那个 0.12s 重决策不打, 免刷屏)
        diag = [] if (self.SKILL_CD_DIAG and not require_intro) else None
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

            if diag is not None:
                diag.append(self._switch_diag_str(char, priority))

            if priority > max_priority or (
                priority == max_priority and char.last_perform < switch_to.last_perform
            ):
                if priority == max_priority:
                    logger.debug("switch priority equal, determine by last perform")
                max_priority = priority
                switch_to = char

        if diag is not None:
            self.log_info(
                f"switch决策(has_intro={has_intro}): {' | '.join(diag)} "
                f"=> 选 {self._get_char_log_name(switch_to)}"
            )

        if has_intro and max_priority < Priority.FAST_SWITCH:
            # 辅助大招就绪待铺时,先上场铺大招 buff,不被环合反应覆盖
            # (按优先级切到该辅助开大);没有大招待铺时环合照常走。
            if not self._any_support_ultimate_pending(current_char):
                reaction_target = self.find_element_reaction_target(current_char)  # 上游改名(原find_element_ring_reaction_target)
                if reaction_target and not self.is_char_unavailable(reaction_target):
                    return reaction_target, has_intro

        return switch_to, has_intro

    def _switch_diag_str(self, char, priority):
        """诊断(SKILL_CD_DIAG):某角色本次切人决策拿到的优先级 + (支援)资源判定明细,
        用来定位"技能/大招就绪却没被选中=晚切"的原因(是确认不到资源、还是优先级被压)。"""
        s = f"{self._get_char_log_name(char)}={int(priority)}"
        try:
            from src.char.MainDps import BuffSupport

            if isinstance(char, BuffSupport) and not char.is_current_char:
                conf = char.has_confirmed_resource()
                sk = char.skill_available()
                dia = self.off_field_ultimate_ready(char.index)
                probe = char.needs_resource_probe()
                rcc = getattr(char, "resource_cache_confirmed", None)
                recent = char.recently_used_resource()
                s += (
                    f"[确认{conf} 技能{sk} 菱形{dia} 探测{probe} "
                    f"缓存确认{rcc} 刚用过{recent}]"
                )
        except Exception:
            pass
        return s

    def _any_support_ultimate_pending(self, current_char):
        """是否有(非当前场上的)辅助大招就绪待铺,用于让"先铺大招 buff"压过环合反应。"""
        from src.char.MainDps import BuffSupport

        for char in self.chars:
            if char is None or char is current_char:
                continue
            if isinstance(char, BuffSupport) and char.ultimate_buff_pending():
                return True
        return False

    def main_dps_overlapping(self):
        """是否有主C正处于"真技能 off-field overlap"强制下场窗口(刚放完真技能、被强制让场)。
        这期间主C必须切给别人, 切上来的支援是来接 overlap 平A的(平A本身有输出), 不该被算成
        "空切/切早"。用于诊断排除这种误报。"""
        from src.char.MainDps import MainDps

        for char in self.chars:
            if isinstance(char, MainDps) and char.should_force_off_field():
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

    # ---------- 队伍快照 / 队伍变更检测 ----------

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
            self.click(action_name="load_chars_fill_attack", interval=0.2)
            time.sleep(self.LOAD_CHARS_SNAPSHOT_RETRY_INTERVAL)

    def check_team_changed_during_combat(self, force=False):
        from src.combat.BaseCombatTask import TeamChangedException

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
        try:
            # 上游72ab817把skip_sleep_check布尔重构为SleepCheckSkip+contextmanager, 等价改写
            with self.skip_sleep_checks() as skip:
                skip.all = True
                in_team, current_index, count = self.in_team()
        finally:
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
        from src.combat.BaseCombatTask import TeamChangedException

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

            # 上游schema v5删除了按名查询get_character_info, 用 按名找id+按id查 组合等价
            char_id = manager._find_character_id_by_name(char.char_name)
            char_info = (manager.get_character_info_by_id(char_id) if char_id else None) or {}
            if not char_info.get("feature_ids"):
                continue

            mat = self.get_char_box(char.index).scale(1.1, 1.1).crop_frame(frame)
            if mat is None or mat.size == 0:
                continue

            verified += 1
            # 上游schema v5后match_feature的target_char/返回值均为char_id(原为char_name);
            # 传名字会过滤掉全部候选→置信度恒0.00→误判队伍变更(实测每秒误报清combo状态)
            is_match, match_id, confidence = manager.match_feature(
                self,
                mat,
                threshold=self.TEAM_SIGNATURE_MATCH_THRESHOLD,
                target_char=char_id,
            )
            if not is_match or match_id != char_id:
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

    # ---------- trigger 战斗循环的队伍重载(AutoCombatTask.run 使用) ----------

    TEAM_RECHECK_INTERVAL = 1.0
    TEAM_RELOAD_WAIT_INTERVAL = 0.2

    def lw_combat_run(self):
        """AutoCombatTask.run 的龙威实现(按 LW_COMBAT_RUN 分发到这里):
        增加队伍变化重载、当前角色丢失重载、角色不可用/队伍变更两类异常的恢复分支。"""
        from src.combat.BaseCombatTask import (
            CharDeadException,
            CharUnavailableException,
            NotInCombatException,
            TeamChangedException,
        )

        ret = False
        if not self.scene.is_in_team(self.is_in_team):
            return

        self._last_team_recheck = 0.0
        self.reset_unavailable_chars()
        combat_start = time.time()
        while self.in_combat():
            try:
                if not ret:
                    ret = True
                    # [lw] 吸收上游 run 新增: 开战读"使用终结技"开关。lw 主循环原先漏了这行,
                    # self.use_ultimate 恒为 __init__ 默认 True → UI 关掉"使用终结技"对 lw 无效。
                    self.use_ultimate = self.config.get(self.CONF_USE_ULT, True)
                    self.switch_to_combat_start_char()
                if not self._reload_if_team_size_changed():
                    time.sleep(self.TEAM_RELOAD_WAIT_INTERVAL)
                    continue
                current_char = self.get_current_char()
                if current_char is None:
                    self.log_info("current char missing during combat, reload chars")
                    if not self._reload_combat_team():
                        time.sleep(self.TEAM_RELOAD_WAIT_INTERVAL)
                    continue
                current_char.perform()
            except CharDeadException:
                self.log_error("Characters dead", notify=True)
                break
            except CharUnavailableException as e:
                logger.info(
                    f"auto_combat_task_char_unavailable "
                    f"{int(time.time() - combat_start)} {e}"
                )
                continue
            except TeamChangedException as e:
                logger.info(f"auto_combat_task_team_changed {int(time.time() - combat_start)} {e}")
                if not self._reload_combat_team():
                    time.sleep(self.TEAM_RELOAD_WAIT_INTERVAL)
                continue
            except NotInCombatException as e:
                logger.info(f"auto_combat_task_out_of_combat {int(time.time() - combat_start)} {e}")
                break
        if ret:
            self.combat_end()

    def _reload_combat_team(self) -> bool:
        from src.combat.BaseCombatTask import CharUnavailableException

        if self.load_chars():
            self.reset_unavailable_chars()
            self._in_combat = True
            try:
                self.switch_to_combat_start_char()
            except CharUnavailableException as e:
                logger.info(f"combat start char unavailable after team reload {e}")
            return True

        if self.chars and self.get_current_char() is not None:
            self.log_info("team reload failed, keep previous valid team")
            return True

        self.log_info("team reload pending, skip combat action this tick")
        return False

    def _reload_if_team_size_changed(self) -> bool:
        now = time.time()
        if now - self._last_team_recheck < self.TEAM_RECHECK_INTERVAL:
            return True
        self._last_team_recheck = now

        in_team, current_index, count = self.in_team()
        snapshot = self._normalize_team_snapshot(
            in_team, current_index, count, source="team size check"
        )
        if snapshot is None:
            return True
        current_index, count = snapshot
        if self.team_size == 0 or count == self.team_size:
            self._pending_team_shrink = None  # 人数恢复, 清减员候选(抖动被吸收)
            return True
        if count > self.team_size and not self.is_reliable_team_expansion(count):
            self._pending_team_shrink = None
            self.log_info(
                f"team size expansion ignored during combat {self.team_size} -> {count}"
            )
            return True

        # [lw] 减员二次确认: 某帧头像瞬时识别不到(大招演出/切人过渡/遮挡)会误判减员,
        # 直接 reload 会打断战斗并触发连锁问题。要求同一 count 持续 TEAM_CHANGE_CONFIRM_INTERVAL
        # 才真 reload; 抖动下一轮 count 恢复→上面 count==team_size 分支清候选, 不 reload。
        # (对齐战斗动作中的 check_team_changed_during_combat, 补齐主循环这条历史遗漏的路径)
        if count < self.team_size:
            previous = self._pending_team_shrink
            if previous is None or previous[0] != count:
                self._pending_team_shrink = (count, now)
                # 首次检测到该减员即 dump 各槽匹配分: 擦边(0.6x)=抖动误判, 归零(<0.3)=真减员
                try:
                    scores = self.lw_dump_char_slot_scores()
                    fmt = ", ".join(f"槽{i + 1}={s:.2f}" for i, s in enumerate(scores))
                    self.log_info(
                        f"team shrink candidate {self.team_size} -> {count} @current{current_index}, "
                        f"各槽头像匹配分[{fmt}] (>=0.70命中算有人; 0.00=低于0.30)"
                    )
                except Exception as e:
                    self.log_info(f"team shrink diag failed: {e}")
                return True  # 本轮不 reload, 继续用旧队伍
            if now - previous[1] < self.TEAM_CHANGE_CONFIRM_INTERVAL:
                return True  # 候选未满确认窗口, 继续等
            self._pending_team_shrink = None  # 减员持续确认, 落地 reload

        self.log_info(f"team size changed during combat {self.team_size} -> {count}, reload chars")
        return self._reload_combat_team()

    # ---------- 队伍加载(弱识别防抖) ----------

    def _fixed_slot_has_char(self, fixed_slots, index: int) -> bool:
        fixed_slot = safe_get(fixed_slots, index)
        if not isinstance(fixed_slot, dict):
            return False
        # 上游schema v5后固定槽字段为char_id(原char_name), 读旧键恒False→固定槽被当未知槽
        return bool(str(fixed_slot.get("char_id", "") or "").strip())

    def _is_unknown_char(self, char: "BaseChar") -> bool:
        return type(char) is BaseChar and char.char_name == "unknown"

    def _warm_up_background_mouse(self):
        """开战(换队加载成功)时预热后台鼠标状态。LauncherTask 每次"Switching capture to game
        window"都会重建 interaction, bg_mouse_pos 归零成 (0,0)/目标 hwnd 丢失——重建后的第一场
        战斗里 combo 的 PostMessage 左键会打到窗口左上角, 游戏不响应(实测: 程序启动/暂停重启后
        第一把双4a只出闪避那一下)。此刻 load_chars 刚截图成功, width/height 必然有效, 用画面
        中心坐标把 bg_mouse_pos/_dynamic_target_hwnd/激活状态热身一次。"""
        try:
            itx = self.executor.interaction
            itx.update_mouse_pos(round(self.width * 0.5), round(self.height * 0.5))
        except Exception as e:
            self.log_debug(f"warm_up_background_mouse failed: {e}")

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

    def lw_load_chars(self, preserve_on_weak=True) -> bool:
        """load_chars 的龙威实现(BaseCombatTask.load_chars 按 LW_LOAD_CHARS 分发到这里):
        快照带重试(覆盖开战入场动画)+ 弱识别(unknown)防抖重试/保留旧队伍。"""
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

    def _commit_loaded_chars(self, chars: list["BaseChar"], current_index: int):
        self._pending_team_change = None
        self._pending_team_signature_change = None
        self._pending_team_shrink = None
        self._last_team_change_check = 0.0
        self._last_team_signature_check = 0.0
        self.clear_element_reactions()  # 上游改名(原clear_element_ring_reactions)
        elements = [char.element for char in chars]
        self.chars = chars
        self.combat_planner.reset(self.chars)  # 上游planner架构要求换队后重置(record_switch等仍走planner)
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
                self.info_add_to_list("chars", f"{char.char_name}: {char.combo_name}")  # 上游改名(原combo_label)

        if self.team_size > 0:
            self.combat_start = time.time()
            self._apply_sound_config()
            self._warm_up_background_mouse()
            return True
        return False
