# [lw] BaseChar 的用户扩展: 技能收尾结算、大招 settle 等待/强制、空闲平A填充、
# 输入模式重试等。
# 接线: class BaseChar(CharExtMixin), self 即角色实例。
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.char.BaseChar import BaseChar

    _CharProxy = BaseChar
else:

    class _CharProxy:
        pass


class CharExtMixin(_CharProxy):
    ULTIMATE_COMBAT_SETTLE_TIMEOUT = 2.5
    ULTIMATE_COMBAT_SETTLE_CLICK = True
    ULTIMATE_COMBAT_SETTLE_FORCE_ON_TIMEOUT = True
    ULTIMATE_COMBAT_SETTLE_FORCE_RETARGET = True
    IDLE_FILL_ATTACK_INTERVAL = 0.1
    SKILL_INPUT_MODE_RETRY_DELAY = 0.12
    # 放长CD技能后若"放招之后触发了闪避"(可能打断释放), 留场结算的最长时间/间隔:
    # 期间看技能图标——进CD就读真实CD校准锚点, 还就绪就补发技能, 直到定下来或超时。
    SKILL_SETTLE_MAX_DURATION = 0.5
    SKILL_SETTLE_INTERVAL = 0.1
    # settle 判"已进CD"的最小有效CD。图标抖动成"非就绪"但 OCR 读到 -0.2/0 这种(就绪/读数
    # 未稳的噪声)不算真进CD, 否则会把"还没放成"误当进CD退出、不再补放。读到 <此值就继续补放。
    SKILL_SETTLE_MIN_ON_CD = 1.0
    # 大招演出结束(已回到队伍画面)后,等"时停解除/CD 开始走"的精确确认超时。
    # 正常 1~2s 内 condition 就满足;深渊换层等场景下大招图标区识别会失效,会一直空等到
    # 超时,导致角色卡住十几秒不切人。这第二段只用来算 freeze 时长,缩短它纯止血、不影响放招。
    ULTIMATE_UNFREEZE_TIMEOUT = 4

    def settle_skill_after_cast(self, cast_at, cooldown, max_duration=None):
        """放长CD技能后的收尾结算 —— 校准CD / 补放。放技能那一下若**紧接着触发了闪避**,
        释放可能被打断: 要么按出去了但没生效、进了个 ~3s 短CD(以为是20s长CD就糟了), 要么
        和闪避隔太近、键根本没按出去、技能还就绪。这里在切人前把它弄清楚。

        仅当"放招(cast_at)之后发生过闪避"才介入; 否则技能正常放出, 直接返回(不影响平常)。
        介入后留场平A最多 SKILL_SETTLE_MAX_DURATION, 每 SKILL_SETTLE_INTERVAL 看技能图标:
          A. OCR读到有意义CD数字 → 按出去了(放成功长CD / 被打断短CD): 锚点已被OCR校准, 结束;
          B. 没读到数字 = 还就绪/没按出去: 底层补发技能(用 send_skill_key 绕过被刚锚CD挡住的
             available), 放出去后下一圈转 A;
          超时仍没数字 → 锚成就绪(别留标称CD撒谎, 下次再上来放)。

        进CD与否只认 skill_ocr_raw(这帧OCR真读到的原始数字), 不读 skill_available/get_cd
        ——后者会被刚 note 的标称CD + grace 污染。返回 True=确认进了CD(已校准); False=没介入/超时。"""
        if not self.is_current_char:
            return False
        # 放招瞬间触发的闪避此刻可能还排在队列里没执行, last_dodge_time 尚未更新。先把它落地再判,
        # 否则"放招→闪避(pending)→切人"贴太紧时会漏检(辅助没有起手平A 去顺手落地闪避)。
        self.task.flush_pending_dodge()
        if not (cast_at > 0 and self.task.last_dodge_time() >= cast_at):
            return False  # 放招后没闪避 → 不介入
        down_time = getattr(self, "SKILL_DOWN_TIME", 0.01)
        self.logger.info("放招后触发闪避, 留场结算技能(校准/补放)")
        deadline = time.time() + (max_duration or self.SKILL_SETTLE_MAX_DURATION)
        while time.time() < deadline:
            self.task.next_frame()
            # A: 这帧OCR真读到了够大的CD数字 → 已进CD(放成功长CD / 被打断短CD), 锚点已校准。
            # 用 skill_ocr_raw 而非 get_cd: 后者没数字时会按刚 note 的标称CD 倒数、谎报进CD。
            raw = self.task.skill_ocr_raw(self.index)
            if raw is not None and raw >= self.SKILL_SETTLE_MIN_ON_CD:
                self.logger.info(f"放招后结算: 技能已进CD, 校准为真实CD={raw:.1f}s")
                return True
            # B: 没读到数字 = 还就绪/没按出去 → 底层补发(绕过被note挡住的available检查)
            self.send_skill_key(down_time=down_time)
            self.task.note_skill_on_cd(self.index, cd=cooldown)  # 暂锚标称, 真值下圈A校准
            self.normal_attack()
            self.sleep(self.SKILL_SETTLE_INTERVAL)
        self.task.note_skill_ready(self.index)
        self.logger.info("放招后结算: 超时仍就绪(没放出), 锚为就绪等下次")
        return False

    def fill_idle_attack(self, interval=None):
        current_char = self.task.get_current_char(raise_exception=False)
        if current_char is not self:
            return False
        if self.task.in_animation or not self.task.is_in_team():
            return False
        interval = self.IDLE_FILL_ATTACK_INTERVAL if interval is None else interval
        return self.click(action_name=f"{self.name}_idle_fill_attack", interval=interval)

    def _force_ultimate_after_combat_settle_timeout(self):
        if not self.ULTIMATE_COMBAT_SETTLE_FORCE_ON_TIMEOUT:
            self.logger.info(
                f"click_ultimate skipped by combat_detect_settle timeout "
                f"{self.ULTIMATE_COMBAT_SETTLE_TIMEOUT}s"
            )
            return False

        current_char = self.task.get_current_char(raise_exception=False)
        if current_char is not self:
            self.logger.info("click_ultimate skipped because current char changed during settle")
            return False
        if not self.task.is_in_team():
            return self.task.in_animation
        if not self.ultimate_available():
            self.logger.info("click_ultimate skipped because ultimate is no longer available")
            return False

        if self.ULTIMATE_COMBAT_SETTLE_FORCE_RETARGET:
            has_target = self.task.combat_detect()
            if not has_target and self.click(
                key="middle", action_name="ultimate_settle_retarget", interval=0.35
            ):
                self.task.openvino_clear_cache()
            self.task.next_frame()

        if not self.ultimate_available():
            self.logger.info("click_ultimate skipped after retarget because ultimate is no longer available")
            return False

        self.logger.info(
            f"click_ultimate forced after combat_detect_settle timeout "
            f"{self.ULTIMATE_COMBAT_SETTLE_TIMEOUT}s"
        )
        return True

    def wait_ultimate_combat_settle(self):
        # 上游状态机重构(f245cbd)后 _combat_settle 已移除, 改读 combat_detect_uncertain
        if not self.task.combat_detect_uncertain:
            return True

        self.logger.info("click_ultimate blocked by combat_detect_uncertain")
        start = time.time()
        while self.task.combat_detect_uncertain:
            if time.time() - start >= self.ULTIMATE_COMBAT_SETTLE_TIMEOUT:
                return self._force_ultimate_after_combat_settle_timeout()
            self.task.next_frame()
            self.check_combat()
            if self.ULTIMATE_COMBAT_SETTLE_CLICK:
                self.fill_idle_attack()
            self.sleep(0.1)
        return True

    def _click_during_ultimate_unfreeze(self):
        # 大招演出/时停解除前，队伍与目标 UI 会短暂消失。这里处在 skip_sleep_checks
        # 保护区内，只做填充点击；完整战斗检测交给大招动作返回后的外层战斗循环。
        self.click_with_interval()

    def _current_char_still_self(self):
        return self.task.get_current_char(raise_exception=False) is self

    def _skill_still_available_after_input_mode_delay(self, has_animation=False):
        self.sleep(self.SKILL_INPUT_MODE_RETRY_DELAY, sleep_check=False)
        self.task.next_frame()
        # 带动画技能按键后可能先隐藏目标/UI，再由外层动作循环确认 animation。
        # 此处若做完整战斗检查，会与大招起手一样把正常演出误判为脱战。
        if not has_animation:
            self.check_combat()
        return (
            self._current_char_still_self()
            and not self.task.in_animation
            and self.task.is_in_team()
            and self.skill_available()
        )

    def lw_send_skill_action_factory(self, down_time, has_animation=False):
        """click_skill 的发键动作: 首次按键后若技能仍就绪(输入模式没吃到键), 重试一次。"""
        state = {"retry_used": False}

        def send_skill_action():
            sent = self.send_skill_key(
                down_time=down_time, action_name="skill_send", interval=0.25
            )
            if sent is False or state["retry_used"]:
                return sent
            if not self._skill_still_available_after_input_mode_delay(
                has_animation=has_animation
            ):
                return sent

            state["retry_used"] = True
            self.logger.info("skill still available after first key press, retry input mode once")
            self._skill_available = False
            return self.send_skill_key(down_time=down_time)

        return send_skill_action
