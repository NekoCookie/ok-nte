# [lw] BaseChar 的用户扩展: 技能打断恢复、空闲平A填充、输入模式重试和大招演出保护等。
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
    IDLE_FILL_ATTACK_INTERVAL = 0.1
    SKILL_INPUT_MODE_RETRY_DELAY = 0.12
    SKILL_SETTLE_MAX_DURATION = 0.5
    SKILL_SETTLE_INTERVAL = 0.1
    SKILL_SETTLE_MIN_ON_CD = 1.0
    # 大招演出结束(已回到队伍画面)后,等"时停解除/CD 开始走"的精确确认超时。
    # 正常 1~2s 内 condition 就满足;深渊换层等场景下大招图标区识别会失效,会一直空等到
    # 超时,导致角色卡住十几秒不切人。这第二段只用来算 freeze 时长,缩短它纯止血、不影响放招。
    ULTIMATE_UNFREEZE_TIMEOUT = 4

    def lw_skill_cooldown_hint(self):
        """返回技能结算使用的标称 CD；未知角色交给 CombatExt 的保守占位。"""

        return getattr(self, "SKILL_COOLDOWN", None)

    def lw_click_skill_with_settlement(self, cooldown=None, max_duration=None, **kwargs):
        """Run the current RU skill action with an LW-only settlement override."""

        sentinel = object()
        previous = getattr(self, "_lw_skill_settle_options", sentinel)
        self._lw_skill_settle_options = (cooldown, max_duration)
        try:
            return self.click_skill(**kwargs)
        finally:
            if previous is sentinel:
                del self._lw_skill_settle_options
            else:
                self._lw_skill_settle_options = previous

    def lw_after_skill_action(self, result, clicked, animated, down_time):
        """Apply LW dodge-settlement only after a non-animated successful skill."""

        if not clicked or animated:
            return
        cooldown, max_duration = getattr(
            self,
            "_lw_skill_settle_options",
            (self.lw_skill_cooldown_hint(), None),
        )
        self.settle_skill_after_cast(
            result["action_time"],
            cooldown,
            max_duration=max_duration,
            down_time=down_time,
        )

    def lw_after_action_poll(self, has_animation):
        """Advance the frame after an action without misclassifying a valid animation."""

        self.task.next_frame()
        if not has_animation:
            self.check_combat()

    def settle_skill_after_cast(
        self,
        cast_at,
        cooldown=None,
        max_duration=None,
        down_time=None,
    ):
        """技能发键后发生闪避时，确认是否进 CD；未放出则在短窗口内补发。

        这是所有角色都会遇到的输入恢复问题，由 BaseChar.click_skill 统一触发。
        ResourceSupportMixin 的资源缓存和 Requiem 的长短 CD/下场判断仍留在各自业务层。
        """
        if not self.is_current_char:
            return False

        # 放招瞬间触发的闪避可能还在队列中，先落地再判断，避免紧接切人时漏检。
        self.task.flush_pending_dodge()
        if not (cast_at > 0 and self.task.last_dodge_time() >= cast_at):
            return False

        down_time = 0.01 if down_time is None else down_time
        duration = self.SKILL_SETTLE_MAX_DURATION if max_duration is None else max_duration
        self.logger.info("放招后触发闪避, 留场结算技能(校准/补放)")
        deadline = time.time() + duration
        while time.time() < deadline:
            self.task.next_frame()
            # 只认本帧 OCR 原始 CD；推算 CD 会被刚写入的标称值污染。
            raw = self.task.skill_ocr_raw(self.index)
            if raw is not None and raw >= self.SKILL_SETTLE_MIN_ON_CD:
                self.logger.info(f"放招后结算: 技能已进CD, 校准为真实CD={raw:.1f}s")
                return True

            self.send_skill_key(down_time=down_time)
            self.task.note_skill_on_cd(self.index, cd=cooldown)
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
        self.click(action_name=f"{self.name}_idle_fill_attack", interval=interval)
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

    def lw_skill_send_action(self, down_time, has_animation=False):
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
