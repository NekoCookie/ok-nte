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
from src.lw.skill_cast_settle import SkillCastSettleMixin


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


class ResourceSupport(SkillCastSettleMixin, BaseChar):
    """增益辅助与治疗共用的资源识别、进场动作和技能结算基础模板。"""

    RESOURCE_PROBE_INTERVAL = 30.0
    # 刚用过资源后的防抖间隔(秒): 仅防止"切出瞬间又被判有资源"的抖动。
    # 不再用大间隔掩盖 CD 推算误差 —— 大招就绪沿用 RU 后台模板、技能用可靠锚点推算。
    RESOURCE_RECHECK_AFTER_USE_INTERVAL = 4.0
    ULTIMATE_COMBAT_SETTLE_TIMEOUT = 0.8
    SKILL_DOWN_TIME = 0.01  # 技能按下时长; 子类(如早雾)改常量即可改长按
    SKILL_COOLDOWN = 20.0  # 技能CD(秒),放技能时当场锚定用;子类按角色改(早雾16)。默认20。
    SKILL_ABOUT_READY_WAIT = 1.0  # 切走前若技能CD<=此值,多等一下平A放了再走

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_resource_probe = 0.0
        self.last_resource_use = 0.0
        self.resource_cache_confirmed = False

    def team_has_main_dps(self):
        return any(
            char is not None
            and char is not self
            and char.describe_role().role == PlannerRole.MAIN_DPS
            for char in self.task.chars
        )

    def ultimate_ready_now(self):
        """统一使用 RU 的大招可用真值；其后台角色路径由 ult_ready 模板识别。"""

        return bool(self.ultimate_available())

    def has_resource(self):
        if not self.team_has_main_dps():
            return super().skill_available() or super().ultimate_available()
        return self.skill_available() or self.ultimate_ready_now()

    def has_cd_cache(self):
        return self.index in self.task.cds

    def has_confirmed_resource(self):
        if not self.team_has_main_dps():
            return False
        if self.recently_used_resource():
            return False
        if self.is_current_char:
            return self.has_resource()
        if self.ultimate_ready_now():
            return True
        # 技能下场读不到图标,仍靠在场时缓存的 CD 时间推算。
        return self.resource_cache_confirmed and self.has_cd_cache() and self.skill_available()

    def has_skill_resource(self):
        """仅"技能"可靠就绪(放招当场已锚CD、下场推算可信)。用于让就绪技能也被服务:
        优先级介于"大招就绪"(高, has_confirmed_resource)和"主C没资源平A"(低)之间。
        大招走 RU 真值、不掺进来;不要求 resource_cache_confirmed(那是旧的脆弱门槛)。"""
        if not self.team_has_main_dps():
            return False
        if self.recently_used_resource():
            return False
        if self.is_current_char:
            return self.skill_available()
        return self.has_cd_cache() and self.skill_available()

    def ultimate_buff_pending(self):
        """子类可覆写：是否存在需要优先铺设的大招增益。"""
        return False

    def recently_used_resource(self):
        return time.time() - self.last_resource_use < self.RESOURCE_RECHECK_AFTER_USE_INTERVAL

    def needs_resource_probe(self):
        if not self.team_has_main_dps():
            return False
        if self.is_current_char or self.has_confirmed_resource() or self.recently_used_resource():
            return False
        return time.time() - self.last_resource_probe >= self.RESOURCE_PROBE_INTERVAL

    def update_resource_after_perform(self, used_ultimate, used_skill):
        now = time.time()
        self.last_resource_probe = now

        if used_ultimate or not self.ultimate_available():
            if used_ultimate or used_skill:
                self.last_resource_use = now
            self.resource_cache_confirmed = False
            return

        if used_skill:
            self.logger.info("support skill used while ultimate remains available")
        self.resource_cache_confirmed = self.has_resource()

    def _cast_skill_if_about_ready(self):
        """切走前看一眼: 技能CD<=SKILL_ABOUT_READY_WAIT 就平A等到就绪、放了再走。
        不死等(上限 CD+0.4s); 等待期用平A不空耗。放成功返回 True。"""
        cd = self.task.get_cd("skill", self.index)
        if not (0 < cd <= self.SKILL_ABOUT_READY_WAIT):
            return False
        enter_at = time.time()
        self.task.diag_cast(self.index, enter_at, f"辅助技能差{cd:.1f}s就绪, 留场等待")
        deadline = enter_at + cd + 0.4
        while time.time() < deadline:
            if self.skill_available():
                if self.click_skill(down_time=self.SKILL_DOWN_TIME):  # 上游click_skill改返回bool
                    self.logger.info(
                        f"{type(self).__name__} 技能差{cd:.1f}s就绪, 等放完再走"
                    )
                    self.task.note_skill_on_cd(self.index, cd=self.SKILL_COOLDOWN)
                    self.task.diag_cast(self.index, enter_at, "辅助技能等待→放成功")
                    return True
                self.task.diag_cast(self.index, enter_at, "辅助技能等待→按键没发出, 放弃")
                return False
            self.normal_attack()
        self.task.diag_cast(self.index, enter_at, "辅助技能等待→超时仍没就绪, 放弃")
        return False

    def describe_role(self):
        raise NotImplementedError

    def skill_priority_ready(self):
        """技能是否可用于普通切人评分；下场不可见时允许按周期入场探测。"""
        return (
            self.has_skill_resource() or self.needs_resource_probe()
        ) and not self.recently_used_resource()

    def resource_field_claims(self, needs_probe):
        """子类按自身定位声明资源入场诉求。"""
        return []

    def combat_plan(self, context):
        """独立声明动作 + entry 编排:
        - 大招/技能各是一个独立 action(planner 能分别评分、被 route/reservation 精确匹配);
        - priority_ready 用辅助资源判定(大招看 RU ultimate_ready_now、技能看
          has_skill_resource；未知资源按探测周期获得一次有限入场机会);
        - entry generator 编排放大招→放技能→大招若刚就绪补一次，收尾更新资源缓存;
        - 技能的完整实现(放招+当场锚CD+闪避打断结算+差一点就绪留场等)封装在 skill 的 execute。
        大招、技能或资源探测待处理时都发 high claim，确保增益辅助先清完资源，
        再把输出窗口交给主 C。"""
        if not self.team_has_main_dps():
            return super().combat_plan(context)  # 无主C: BaseChar 默认(放大招放技能)

        needs_probe = self.needs_resource_probe()
        ultimate = self.planner_action(
            tags={ActionTag.SUPPORT, ActionTag.ULTIMATE_ACTION},
            slot=ActionSlot.ULTIMATE,
            execute=lambda _: self.click_ultimate(),
            name=f"{self}_ultimate",
            reason="support ultimate ready",
            can_execute=lambda _: self.ultimate_available(),
            priority_ready=lambda _: self.ultimate_ready_now() and not self.recently_used_resource(),
        )
        skill = self.planner_action(
            tags={ActionTag.SUPPORT, ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=self._execute_support_skill,
            name=f"{self}_skill",
            reason="support skill ready",
            # 下场时无法直接看技能图标；探测到期允许切入尝试，实际施放失败仍按失败结算。
            can_execute=lambda _: self.skill_available() or needs_probe,
            priority_ready=lambda _: self.skill_priority_ready(),
        )
        claims = self.resource_field_claims(needs_probe)

        def entry():
            used_ultimate = bool((yield ultimate))
            used_skill = bool((yield skill))
            # 放技能后大招常刚好充满，同一站场补放一次
            if not used_ultimate and self.ultimate_available():
                used_ultimate = bool((yield ultimate))
            self.update_resource_after_perform(used_ultimate, used_skill)

        return self.plan(ultimate, skill, claims=claims, entry=entry)

    def _execute_support_skill(self, context=None):
        """放招→当场锚 CD→闪避打断结算；没放成则看差一点就绪留场等。"""
        if self.click_skill(down_time=self.SKILL_DOWN_TIME):
            self.logger.info(f"{type(self).__name__} skill cast (anchor cd {self.SKILL_COOLDOWN}s)")
            self.task.note_skill_on_cd(self.index, cd=self.SKILL_COOLDOWN)
            cast_at = self.task.cds.get(self.index, {}).get("skill_cast_at", 0)
            self.settle_skill_after_cast(cast_at, self.SKILL_COOLDOWN)
            return True
        return self._cast_skill_if_about_ready()


class BuffSupport(ResourceSupport):
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
            return [FieldClaim.preemptive(source=self, reason="support ultimate buff pending")]
        if self.has_skill_resource():
            return [FieldClaim.preemptive(source=self, reason="support skill resource ready")]
        if needs_probe:
            return [FieldClaim.high(source=self, reason="support resource probe due")]
        return []


class HealSupport(ResourceSupport):
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
