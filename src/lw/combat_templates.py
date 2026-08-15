import time

from src.char.BaseChar import BaseChar
from src.combat.planner import (
    ActionSlot,
    ActionTag,
    FieldClaim,
    FieldPreference,
    RoleProfile,
)
from src.combat.planner import Role as PlannerRole
from src.lw.field_claim_ext import lw_preemptive_field_claim
from src.lw.resource_support import ResourceSupportMixin


class MainDps(BaseChar):
    """Generic on-field damage dealer template."""

    IDLE_ATTACK_DURATION = 2.5
    IDLE_ATTACK_INTERVAL = 0.1

    def _is_support(self, char):
        return char is not None and char.describe_role().role != PlannerRole.MAIN_DPS

    def describe_role(self):
        # planner 定位: 主C(靠 field_time 站场输出)。
        return RoleProfile(
            role=PlannerRole.MAIN_DPS,
            field_preference=FieldPreference.MAIN_DPS,
            max_field_time=self.IDLE_ATTACK_DURATION,
        )

    def combat_plan(self, context):
        """大招/技能独立 action，idle 平A 作为一个 LEGACY_COMBO 动作。

        entry 编排放大招→技能→没招则 idle。让位辅助由 planner 切人评分负责，
        idle 执行体内部也保留让位检查兜底。
        """
        ultimate = self.click_ultimate_action(reason="main dps ultimate ready")
        skill = self.click_skill_action(reason="main dps skill ready")
        idle = self.planner_action(
            tags={ActionTag.LEGACY_COMBO, ActionTag.DAMAGE, ActionTag.FIELD_TIME},
            slot=ActionSlot.LEGACY_COMBO,
            execute=lambda _: self.idle_normal_attack(),
            name=f"{self}_idle_combo",
            reason="main dps idle field time",
            priority_ready=lambda _: False,  # idle 不主动抢切人, 靠 describe_role 的 field_time 站场
        )

        def entry():
            used_ultimate = bool((yield ultimate))
            used_skill = bool((yield skill))
            if not used_ultimate and not used_skill:
                yield idle

        return self.plan(ultimate, skill, idle, entry=entry)

    def _has_resource(self, char):
        if char is None:
            return False
        if hasattr(char, "has_confirmed_resource"):
            if char.has_confirmed_resource():
                return True
            # 技能就绪(可靠锚点)也算"有资源",让主C让位、就绪技能被及时服务。
            if hasattr(char, "has_skill_resource") and char.has_skill_resource():
                return True
            return False
        return char.skill_available() or char.ultimate_available()

    def _needs_probe(self, char):
        return (
            char is not None
            and hasattr(char, "needs_resource_probe")
            and char.needs_resource_probe()
        )

    def support_has_resource(self):
        return any(
            self._is_support(char) and self._has_resource(char)
            for char in self.task.chars
            if char != self
        )

    def support_needs_probe(self):
        return any(
            self._is_support(char) and self._needs_probe(char)
            for char in self.task.chars
            if char != self
        )

    def should_yield_to_support(self, include_probe=True):
        return self.support_has_resource() or (include_probe and self.support_needs_probe())

    def should_stay_on_field(self):
        return (
            self.is_current_char
            and not self.should_force_off_field()
            and not self.is_cycle_full()
            and not self.should_yield_to_support()
        )

    def should_force_off_field(self):
        return False

    def idle_normal_attack(self, duration=None):
        start = time.time()
        duration = self.IDLE_ATTACK_DURATION if duration is None else duration
        while time.time() - start < duration:
            if self.should_yield_to_support():
                self.logger.info("support ready while main dps idle attacking")
                return
            self.normal_attack()
            self.sleep(self.IDLE_ATTACK_INTERVAL)

    def switch_next_char(self, post_action=None, free_intro=False):
        if self.should_stay_on_field():
            self.logger.debug("main dps stays on field during team downtime")
            return
        super().switch_next_char(post_action=post_action, free_intro=free_intro)


class BuffSupport(ResourceSupportMixin, BaseChar):
    """增益辅助模板：确认有资源时先入场铺 buff，再把输出窗口交给主 C。"""

    def describe_role(self):
        return RoleProfile(
            role=PlannerRole.SUPPORT,
            field_preference=FieldPreference.SUPPORT,
            max_field_time=1.5,
        )

    def ultimate_buff_pending(self):
        """大招就绪、待上场铺，用于发布环合前的 preemptive FieldClaim。"""
        if not self.team_has_main_dps() or self.recently_used_resource():
            return False
        return self.ultimate_ready_now()

    def combat_start_resource_observation(self):
        """仅用于开场稳定门控：技能/RU 真值优先，LW 几何识别保留三态 UI 观察。"""

        if self.recently_used_resource():
            return False
        if self.has_skill_resource() or self.ultimate_ready_now():
            return True
        if self.is_current_char:
            return False
        return self.task.off_field_ultimate_ready(self.index)

    def resource_field_claims(self, needs_probe):
        if self.ultimate_buff_pending():
            return [lw_preemptive_field_claim(source=self, reason="support ultimate buff pending")]
        if self.has_skill_resource():
            return [lw_preemptive_field_claim(source=self, reason="support skill resource ready")]
        if needs_probe:
            return [FieldClaim.high(source=self, reason="support resource probe due")]
        return []


class HealSupport(ResourceSupportMixin, BaseChar):
    """治疗模板与增益辅助平级，共用资源检测和执行骨架，但保持最低切人优先级。

    只有当主C没爆发、且增益辅助也没资源时，治疗资源才参与 planner 评分。

    `_higher_priority_busy()` 是治疗自己的门控，不影响增益辅助的 claim 策略。
    """

    def describe_role(self):
        # planner 无 HEALER 定位。max_field_time=0 让治疗无资源时完全不参与普通驻场；
        # 有资源时靠低 claim 入场，SUPPORT 权重使其刚好压过主C空闲驻场、仍低于真实终结技。
        return RoleProfile(
            role=PlannerRole.SUPPORT,
            field_preference=FieldPreference.SUPPORT,
            max_field_time=0,
        )

    def _higher_priority_busy(self):
        """主C有爆发(技能/大招就绪),或别的非治疗辅助有资源/待探测 = 有更高优先级要上,治疗让位。"""
        for char in self.task.chars:
            if char is None or char is self:
                continue
            if char.describe_role().role == PlannerRole.MAIN_DPS:
                if char.skill_available() or char.ultimate_available():
                    return True
            elif isinstance(char, BuffSupport):
                if (
                    char.has_confirmed_resource()
                    or char.has_skill_resource()
                    or char.needs_resource_probe()
                ):
                    return True
        return False

    def has_confirmed_resource(self):
        if self._higher_priority_busy():
            return False
        return super().has_confirmed_resource()

    def has_skill_resource(self):
        if self._higher_priority_busy():
            return False
        return super().has_skill_resource()

    def needs_resource_probe(self):
        if self._higher_priority_busy():
            return False
        return super().needs_resource_probe()

    def resource_field_claims(self, needs_probe):
        if self.has_skill_resource():
            return [FieldClaim.low(source=self, reason="heal skill resource ready")]
        if needs_probe:
            return [FieldClaim.low(source=self, reason="heal resource probe due")]
        return []


class SakiriBuffSupport(BuffSupport):
    """早雾辅助:**有主C时**与辅助模板完全一致,仅技能改为长按(SKILL_DOWN_TIME);
    **无主C时**回退到 RU 的早雾(`Sakiri`)逻辑,而不是辅助那套资源/补大招。"""

    SKILL_DOWN_TIME = 0.25
    SKILL_COOLDOWN = 16.0  # 早雾技能CD 16s

    def combat_plan(self, context):
        if not self.team_has_main_dps():
            # 无主C体系时使用 RU 早雾(Sakiri)的出招计划，而不是 BaseChar 通用版。
            from src.char.Sakiri import Sakiri

            return Sakiri.combat_plan(self, context)
        # 有主C体系: 走 super()=BuffSupport 的 combat_plan(大招/技能独立动作+entry编排)。
        # 长按由 SKILL_DOWN_TIME=0.25 在 skill 的 execute(_execute_support_skill)自动生效, 无需重写。
        return super().combat_plan(context)
