# [lw] BaseChar 的用户扩展: 空闲平A填充、输入模式重试和大招演出保护等。
# 接线: class BaseChar(CharExtMixin), self 即角色实例。
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
    # 大招演出结束(已回到队伍画面)后,等"时停解除/CD 开始走"的精确确认超时。
    # 正常 1~2s 内 condition 就满足;深渊换层等场景下大招图标区识别会失效,会一直空等到
    # 超时,导致角色卡住十几秒不切人。这第二段只用来算 freeze 时长,缩短它纯止血、不影响放招。
    ULTIMATE_UNFREEZE_TIMEOUT = 4

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
