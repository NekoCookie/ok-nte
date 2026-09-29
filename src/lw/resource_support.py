"""[lw] 增益辅助与治疗共享的资源识别和 planner 执行能力。"""

import time

from src.combat.planner import ActionSlot, ActionTag
from src.combat.planner import Role as PlannerRole


class ResourceSupportMixin:
    """资源型角色能力，不代表角色定位；由 BuffSupport 与 HealSupport 共同组合。"""

    RESOURCE_PROBE_INTERVAL = 30.0
    # 刚用过资源后的防抖间隔，仅防止切出瞬间又被判有资源。
    RESOURCE_RECHECK_AFTER_USE_INTERVAL = 4.0
    ULTIMATE_COMBAT_SETTLE_TIMEOUT = 0.8
    SKILL_DOWN_TIME = 0.01
    SKILL_COOLDOWN = 20.0
    SKILL_ABOUT_READY_WAIT = 1.0

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
        """统一使用 RU 的大招可用真值；后台角色路径由 ult_ready 模板识别。"""

        return not self.lw_skills_disabled_for_test() and bool(self.ultimate_available())

    def has_resource(self):
        if self.lw_skills_disabled_for_test():
            return False
        if not self.team_has_main_dps():
            return super().skill_available() or super().ultimate_available()
        return self.skill_available() or self.ultimate_ready_now()

    def has_cd_cache(self):
        return self.index in self.task.cds

    def has_confirmed_resource(self):
        if self.lw_skills_disabled_for_test():
            return False
        if not self.team_has_main_dps() or self.recently_used_resource():
            return False
        if self.is_current_char:
            return self.has_resource()
        if self.ultimate_ready_now():
            return True
        return self.resource_cache_confirmed and self.has_cd_cache() and self.skill_available()

    def has_skill_resource(self):
        """技能是否有可靠的就绪锚点；大招继续使用 RU 真值。"""

        if self.lw_skills_disabled_for_test():
            return False
        if not self.team_has_main_dps() or self.recently_used_resource():
            return False
        if self.is_current_char:
            return self.skill_available()
        return self.has_cd_cache() and self.skill_available()

    def ultimate_buff_pending(self):
        """角色模板可覆写：是否存在需要优先铺设的大招增益。"""

        return False

    def recently_used_resource(self):
        return time.time() - self.last_resource_use < self.RESOURCE_RECHECK_AFTER_USE_INTERVAL

    def needs_resource_probe(self):
        if self.lw_skills_disabled_for_test():
            return False
        if not self.team_has_main_dps():
            return False
        if self.is_current_char or self.has_confirmed_resource() or self.recently_used_resource():
            return False
        if self.has_cd_cache():
            # 本场已有技能 CD 记录: 交给下场推算, 就绪时走"技能就绪"诉求, 不再周期盲探。
            return False
        # 本场还没见过该技能(开局无记录): 上场看一眼, 就绪当场放, 否则锚定真实 CD。
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

    RESOURCE_DIAG_INTERVAL = 2.0

    def _log_resource_decision_diag(self, needs_probe, claims):
        """CD 对照诊断: 下场且推算技能已就绪/将就绪时, 记下 planner 评估这一刻的判断依据。

        用来定位"推算已就绪却没发技能就绪诉求"。每个角色节流, 只在
        SKILL_CD_TRUTH_DIAG 打开时运行。
        """

        task = getattr(self, "task", None)
        if getattr(task, "SKILL_CD_TRUTH_DIAG", False) is not True:
            return
        if getattr(self, "is_current_char", False) or not self.has_cd_cache():
            return
        skill_cd = task.get_cd("skill", self.index)
        if skill_cd > self.SKILL_ABOUT_READY_WAIT:
            return
        now = time.time()
        if now - getattr(self, "_lw_resource_diag_at", 0.0) < self.RESOURCE_DIAG_INTERVAL:
            return
        self._lw_resource_diag_at = now
        claim = claims[0].reason if claims else "none"
        self.logger.info(
            f"support-diag {self}: skill_est={skill_cd:.1f} "
            f"skill_resource={self.has_skill_resource()} "
            f"switch_cfg={self.should_switch_for_ready_skill()} "
            f"recent_use={self.recently_used_resource()} "
            f"ult_ready={self.ultimate_ready_now()} probe={needs_probe} claim={claim}"
        )

    def skill_about_ready_on_field(self):
        """在场且技能差不到 SKILL_ABOUT_READY_WAIT 就绪: 值得执行技能动作留场等放。"""

        get_cd = getattr(self.task, "get_cd", None)
        if not getattr(self, "is_current_char", False) or not callable(get_cd):
            return False
        return 0 < get_cd("skill", self.index) <= self.SKILL_ABOUT_READY_WAIT

    def _cast_skill_if_about_ready(self):
        """技能即将就绪时短暂留场平A，放出后再离场。"""

        cd = self.task.get_cd("skill", self.index)
        if not (0 < cd <= self.SKILL_ABOUT_READY_WAIT):
            return False
        enter_at = time.time()
        self.task.diag_cast(self.index, enter_at, f"辅助技能差{cd:.1f}s就绪, 留场等待")
        deadline = enter_at + cd + 0.4
        while time.time() < deadline:
            if self.skill_available():
                if self.click_skill(down_time=self.SKILL_DOWN_TIME):
                    self.logger.info(f"{type(self).__name__} 技能差{cd:.1f}s就绪, 等放完再走")
                    self.task.note_skill_on_cd(self.index, cd=self.SKILL_COOLDOWN)
                    self.task.diag_cast(self.index, enter_at, "辅助技能等待→放成功")
                    return True
                self.task.diag_cast(self.index, enter_at, "辅助技能等待→按键没发出, 放弃")
                return False
            self.normal_attack()
        self.task.diag_cast(self.index, enter_at, "辅助技能等待→超时仍没就绪, 放弃")
        return False

    def skill_priority_ready(self):
        """技能是否可用于普通切人评分；下场不可见时允许按周期入场探测。"""

        return (
            (self.should_switch_for_ready_skill() and self.has_skill_resource())
            or self.needs_resource_probe()
        ) and not self.recently_used_resource()

    def should_switch_for_ready_skill(self):
        """技能确认就绪时是否允许主动切入; 资源模板默认保持原行为。"""

        return True

    def resource_field_claims(self, needs_probe):
        """角色模板按自身定位声明资源入场诉求。"""

        return []

    def resource_charge_action(self):
        """角色模板可覆写: 没放出大招时留场攒能量的动作, 没有返回 None。"""

        return None

    def combat_plan(self, context):
        """资源型角色共用的大招→技能→资源缓存更新执行骨架。"""

        if self.lw_skills_disabled_for_test():
            return self.plan()
        if not self.team_has_main_dps():
            return super().combat_plan(context)

        needs_probe = self.needs_resource_probe()
        ultimate = self.planner_action(
            tags={ActionTag.SUPPORT, ActionTag.ULTIMATE_ACTION},
            slot=ActionSlot.ULTIMATE,
            execute=lambda _: self.click_ultimate(),
            name=f"{self}_ultimate",
            reason="support ultimate ready",
            can_execute=lambda _: self.ultimate_available(),
            priority_ready=lambda _: self.ultimate_ready_now()
            and not self.recently_used_resource(),
        )
        skill = self.planner_action(
            tags={ActionTag.SUPPORT, ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=self._execute_support_skill,
            name=f"{self}_skill",
            reason="support skill ready",
            # 差一点就绪也执行: _execute_support_skill 会留场平A等到放出(否则等待分支永远走不到)。
            can_execute=lambda _: (
                self.skill_available() or needs_probe or self.skill_about_ready_on_field()
            ),
            priority_ready=lambda _: self.skill_priority_ready(),
        )
        charge = self.resource_charge_action()
        claims = self.resource_field_claims(needs_probe)
        self._log_resource_decision_diag(needs_probe, claims)

        def entry():
            used_ultimate = bool((yield ultimate))
            used_skill = bool((yield skill))
            if not used_ultimate and self.ultimate_available():
                used_ultimate = bool((yield ultimate))
            if not used_ultimate and charge is not None:
                yield charge
            self.update_resource_after_perform(used_ultimate, used_skill)

        return self.plan(ultimate, skill, claims=claims, entry=entry)

    def _execute_support_skill(self, context=None):
        """放招后锚定资源 CD；通用闪避打断恢复由 BaseChar.click_skill 处理。"""

        if self.click_skill(down_time=self.SKILL_DOWN_TIME):
            self.logger.info(
                f"{type(self).__name__} skill cast (anchor cd {self.SKILL_COOLDOWN}s)"
            )
            self.task.note_skill_on_cd(self.index, cd=self.SKILL_COOLDOWN)
            return True
        return self._cast_skill_if_about_ready()
