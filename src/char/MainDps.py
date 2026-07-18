import time

from src.char.BaseChar import BaseChar
from src.combat.planner import (
    ActionSlot,
    ActionTag,
    FieldClaim,
    FieldPreference,
    RoleProfile,
)
from src.combat.planner import Role as PlannerRole  # planner 定位, 与下面 legacy Role 区分
from src.lw.legacy_priority import Priority, Role  # 上游已从BaseChar移除, 迁移到src/lw/


class MainDps(BaseChar):
    """Generic on-field damage dealer template."""

    IDLE_ATTACK_DURATION = 2.5
    IDLE_PRIORITY = 5
    IDLE_ATTACK_INTERVAL = 0.1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = Role.MAIN_DPS

    def _is_support(self, char):
        return char is not None and getattr(char, "role", Role.DEFAULT) != Role.MAIN_DPS

    def team_has_support_template(self):
        """主C模板体系是否成立: 队里有辅助模板(BuffSupport系, 含治疗/早雾)。
        体系外(队友是娜娜莉等上游原生角色)时, 主C模板的让位/资源判定全部失去对象,
        planner 还会把本角色当 sub_dps 评分, 导致乒乓空切——此时应整体退回上游打法。"""
        return any(
            isinstance(char, BuffSupport)
            for char in self.task.chars
            if char is not None and char is not self
        )

    def lw_use_do_perform(self):
        # 体系外整体退回上游 planner(BaseChar.combat_plan 默认打法)
        return self.team_has_support_template()

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

    def _support_ultimate_ready(self, char):
        """辅助的"大招"是否就绪(不含技能): 在场看底部图标、下场看头像菱形; 刚用过不算。"""
        if char is None or char is self or not self._is_support(char):
            return False
        if getattr(char, "recently_used_resource", lambda: False)():
            return False
        ready = getattr(char, "ultimate_ready_now", None)
        if ready is not None:
            return ready()
        return char.ultimate_available()

    def support_has_ultimate(self):
        """是否有辅助的大招就绪。用于让位判定: 只有辅助大招就绪才压低主C优先级、先让辅助放大招;
        辅助仅技能就绪不让位(主C先放真技能, 放完 overlap 再切辅助放技能)。"""
        return any(self._support_ultimate_ready(char) for char in self.task.chars)

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

    def do_perform(self):
        self.wait_intro()
        if self.should_yield_to_support():
            self.logger.info("support resource ready, yielding main dps field time")
            self.continues_normal_attack(0.2)
            return

        used_ultimate = self.click_ultimate()
        used_skill = self.click_skill()  # 上游click_skill改返回bool(原三元组)
        if not used_ultimate and not used_skill:
            self.idle_normal_attack()

    def count_base_priority(self):
        # 只有辅助"大招"就绪才压低主C的idle分让位(→辅助大招 201 压过 Requiem技能 110)。
        # 辅助仅技能就绪时保持 idle 分: Requiem 技能就绪的 +100 加成使其 115 > 辅助技能 110,
        # 主C先放真技能、放完 overlap 再切辅助放技能; 主C没技能时(分5<110)自然让辅助技能上。
        if self.support_has_ultimate():
            return 0
        return self.IDLE_PRIORITY

    def switch_next_char(self, post_action=None, free_intro=False):
        if self.should_stay_on_field():
            self.logger.debug("main dps stays on field during team downtime")
            return
        super().switch_next_char(post_action=post_action, free_intro=free_intro)


class BuffSupport(BaseChar):
    """Generic buff/support template that takes priority when resources are ready."""

    RESOURCE_PRIORITY_BONUS = Priority.SKILL_AVAILABLE
    RESOURCE_PROBE_INTERVAL = 30.0
    # 刚用过资源后的防抖间隔(秒): 仅防止"切出瞬间又被判有资源"的抖动。
    # 不再用大间隔掩盖 CD 推算误差 —— 大招就绪由头像菱形精确判定、技能由可靠锚点的 CD 推算判定。
    RESOURCE_RECHECK_AFTER_USE_INTERVAL = 4.0
    RESOURCE_PROBE_PRIORITY = Priority.BASE
    ULTIMATE_COMBAT_SETTLE_TIMEOUT = 0.8
    ULTIMATE_COMBAT_SETTLE_CLICK = True
    SKILL_DOWN_TIME = 0.01  # 技能按下时长;子类(如早雾)改这个常量即可改长按,无需重写 do_perform
    SKILL_COOLDOWN = 20.0  # 技能CD(秒),放技能时当场锚定用;子类按角色改(早雾16)。默认20。
    SKILL_ABOUT_READY_WAIT = 1.0  # 切走前若技能CD<=此值,多等一下平A放了再走

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = Role.SUB_DPS
        self.last_resource_probe = 0.0
        self.last_resource_use = 0.0
        self.resource_cache_confirmed = False

    def team_has_main_dps(self):
        return any(
            char is not None and char is not self and isinstance(char, MainDps)
            for char in self.task.chars
        )

    def ultimate_ready_now(self):
        """大招就绪判定:在场看底部大招图标;下场看头像元素菱形(视觉)。
        视觉不确定(None)时回退到 ultimate_available 的时间推算。"""
        if self.is_current_char:
            return self.ultimate_available()
        visual = self.task.off_field_ultimate_ready(self.index)
        if visual is None:
            return self.ultimate_available()
        return visual

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
        # 下场:大招直接看头像菱形(可靠,不受缓存门槛限制),只有视觉明确"有"才算确认。
        if self.task.off_field_ultimate_ready(self.index) is True:
            return True
        # 技能下场读不到图标,仍靠在场时缓存的 CD 时间推算。
        return self.resource_cache_confirmed and self.has_cd_cache() and self.skill_available()

    def has_skill_resource(self):
        """仅"技能"可靠就绪(放招当场已锚CD、下场推算可信)。用于让就绪技能也被服务:
        优先级介于"大招菱形就绪"(高, has_confirmed_resource)和"主C没资源平A"(低)之间。
        大招走菱形、不掺进来;不要求 resource_cache_confirmed(那是旧的脆弱门槛,现在锚点可靠)。"""
        if not self.team_has_main_dps():
            return False
        if self.recently_used_resource():
            return False
        if self.is_current_char:
            return self.skill_available()
        return self.has_cd_cache() and self.skill_available()

    def ultimate_buff_pending(self):
        """大招就绪、待上场铺 —— 用于让"先铺大招 buff"压过环合反应优先切人。
        只看大招(技能就绪不打断环合);在场看底部图标、下场看头像菱形;刚用过不算。"""
        if not self.team_has_main_dps():
            return False
        if self.recently_used_resource():
            return False
        if self.is_current_char:
            return self.ultimate_available()
        return self.task.off_field_ultimate_ready(self.index) is True

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

    def _cast_ult_and_skill(self, skill_down_time=0.01):
        """放大招 + 技能。放完技能后大招常刚好充满就绪,**同一次站场内补放一次大招**,
        避免"放完技能→大招才就绪→切走又立刻切回来开大招"的来回切。切走前的这次
        `ultimate_available` 检查很便宜(读一次图标),就绪就直接开、不就绪秒过。
        共享给 BuffSupport / 治疗 / 早雾,改一处全生效。"""
        used_ultimate = self.click_ultimate()
        used_skill = self.click_skill(down_time=skill_down_time)  # 上游click_skill改返回bool(原三元组)
        if used_skill:
            # 放技能即记日志(支援技能本来没日志) + 当场把技能CD锚上开始倒计时,
            # 不等后续OCR——否则放完即走、OCR没读到新CD时锚点会残留"就绪"撒谎。
            # 注意: 锚的是"点了技能"的标称CD; 真没放成功(闪避打断→短CD)由图标OCR识别纠正(见 refresh_cd)。
            self.logger.info(f"{type(self).__name__} skill cast (anchor cd {self.SKILL_COOLDOWN}s)")
            self.task.note_skill_on_cd(self.index, cd=self.SKILL_COOLDOWN)
            # 放招后紧接着闪避会打断释放(进3s短CD)或根本没按出去(还就绪)。切走前留场结算:
            # 进CD就读真实CD校准(否则下场误当20s冷却→空切)、还就绪就补放。放招后没闪避则秒返回。
            cast_at = self.task.cds.get(self.index, {}).get("skill_cast_at", 0)
            self.settle_skill_after_cast(cast_at, self.SKILL_COOLDOWN)
        if not used_ultimate and self.ultimate_available():
            used_ultimate = self.click_ultimate()
        # 技能差一点就绪(CD<=1s): 多等一下平A放了再走, 否则差0.5s被切走、这趟白跑。
        if not used_skill and self._cast_skill_if_about_ready():
            used_skill = True
        return used_ultimate, used_skill

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

    def lw_use_do_perform(self):
        # 无主C体系时整体退回上游 planner(旧版回退 super().do_perform() 已随 planner 化成
        # AttributeError)。另: 全面升级总开关 USE_PLANNER 开启后, 有主C也走 combat_plan。
        from src.lw.planner_migration import USE_PLANNER

        return self.team_has_main_dps() and not USE_PLANNER

    def describe_role(self):
        # planner 定位: 辅助。走 lw 切换决策(LW_SWITCH_NEXT)时不生效, 仅 planner 决策时用。
        return RoleProfile(
            role=PlannerRole.SUPPORT,
            field_preference=FieldPreference.SUPPORT,
            max_field_time=1.5,
        )

    def combat_plan(self, context):
        """按 ru 风格拆成独立声明动作 + entry 编排(对照 Nanally 的 planner 迁移):
        - 大招/技能各是一个独立 action(planner 能分别评分、被 route/reservation 精确匹配);
        - priority_ready 用辅助资源判定(大招看菱形 ultimate_ready_now、技能看 has_skill_resource,
          等价 legacy has_confirmed/skill_resource, 决定"下场时值不值得为它切上场");
        - entry generator 编排 do_perform 的顺序(放大招→放技能→大招若刚就绪补一次), 收尾更新资源缓存;
        - 技能的完整实现(放招+当场锚CD+闪避打断结算+差一点就绪留场等)封装在 skill 的 execute。
        大招 buff 待铺时发 high claim 压过环合反应(对应 lw 的 _any_support_ultimate_pending)。"""
        if not self.team_has_main_dps():
            return super().combat_plan(context)  # 无主C: BaseChar 默认(放大招放技能)

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
            can_execute=lambda _: self.skill_available(),
            priority_ready=lambda _: self.has_skill_resource() and not self.recently_used_resource(),
        )
        claims = []
        if self.ultimate_buff_pending():
            claims.append(FieldClaim.high(source=self, reason="support ultimate buff pending"))

        def entry():
            used_ultimate = bool((yield ultimate))
            used_skill = bool((yield skill))
            # 放技能后大招常刚好充满, 同一站场补放一次(对应 _cast_ult_and_skill 的补大招)
            if not used_ultimate and self.ultimate_available():
                used_ultimate = bool((yield ultimate))
            self.update_resource_after_perform(used_ultimate, used_skill)

        return self.plan(ultimate, skill, claims=claims, entry=entry)

    def _execute_support_skill(self, context=None):
        """技能动作的完整实现(从 _cast_ult_and_skill 的技能分支抽出, 手感不变):
        放招→当场锚 CD→闪避打断结算; 没放成则看差一点就绪留场等。"""
        if self.click_skill(down_time=self.SKILL_DOWN_TIME):
            self.logger.info(f"{type(self).__name__} skill cast (anchor cd {self.SKILL_COOLDOWN}s)")
            self.task.note_skill_on_cd(self.index, cd=self.SKILL_COOLDOWN)
            cast_at = self.task.cds.get(self.index, {}).get("skill_cast_at", 0)
            self.settle_skill_after_cast(cast_at, self.SKILL_COOLDOWN)
            return True
        return self._cast_skill_if_about_ready()

    def do_perform(self):
        if not self.team_has_main_dps():
            # 正常到不了这里(lw_use_do_perform=False 时 perform 直接走 planner);
            # 战斗中途队伍识别变化的极端时序兜底: 平A填场, 别调已被上游删除的 BaseChar.do_perform。
            self.continues_normal_attack(0.2)
            return

        self.wait_intro()
        used_ultimate, used_skill = self._cast_ult_and_skill(skill_down_time=self.SKILL_DOWN_TIME)
        self.update_resource_after_perform(used_ultimate, used_skill)
        if not used_ultimate and not used_skill:
            if not self.has_intro and not self.task.main_dps_overlapping():
                # 真空切(资源误判切早/探测落空)。排除两类非空切:环合反应切入(has_intro,
                # 为元素反应)、主C真技能 overlap 强制切人(来接平A,本身有输出)。
                self.logger.info(
                    f"support empty-switch 空切: {type(self).__name__} 切上场但啥都没放"
                )
            self.continues_normal_attack(0.2)

    def do_get_switch_priority(self, current_char, has_intro=False):
        if not self.team_has_main_dps():
            return super().do_get_switch_priority(current_char, has_intro)

        if self.has_confirmed_resource():
            return (
                super().do_get_switch_priority(current_char, has_intro)
                + self.RESOURCE_PRIORITY_BONUS
            )
        if self.has_skill_resource():
            # 技能就绪:中等优先级(不加 RESOURCE_PRIORITY_BONUS)→ 低于大招就绪、
            # 高于主C没资源平A的闲置分。让就绪技能被及时服务、不必死等大招。
            return super().do_get_switch_priority(current_char, has_intro)
        if self.needs_resource_probe():
            return self.RESOURCE_PROBE_PRIORITY
        return Priority.BASE_MINUS_1


class HealSupport(BuffSupport):
    """治疗模板:机制与辅助(`BuffSupport`)完全一样——探测间隔 + CD/大招就绪都看,
    上场放治疗技能/大招后即下场。**唯一区别是优先级最低**:只有当主C没爆发(技能/大招
    都没就绪)、且别的辅助也没资源(含待探测)时,才轮到治疗被切上来。

    实现:在辅助原有"有没有资源"判定外再加一道闸 `_higher_priority_busy()`——只要主C或
    别的辅助还有事干,治疗一律视为没资源(优先级压到 BASE_MINUS_1),自然让位;两者都空了
    才放行。无需改 MainDps/BaseCombatTask:治疗 role=HEALER 也算"辅助",会被 MainDps
    的 should_yield_to_support 纳入,但因为这道闸,主C只会在自己空闲时才给治疗让场。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = Role.HEALER

    def describe_role(self):
        # planner 无 HEALER 定位, 用 SUPPORT + SETUP_ONLY 站场偏好: 治疗不主动站场(无请求时不
        # 抢 field_time), 只在 priority_ready(资源就绪且 _higher_priority_busy 放行)时被切上。
        # 治疗"最低优先级"在 planner 下靠 has_confirmed_resource/has_skill_resource 的门控实现。
        return RoleProfile(
            role=PlannerRole.SUPPORT,
            field_preference=FieldPreference.SETUP_ONLY,
            max_field_time=1.5,
        )

    def _higher_priority_busy(self):
        """主C有爆发(技能/大招就绪),或别的非治疗辅助有资源/待探测 = 有更高优先级要上,治疗让位。"""
        for char in self.task.chars:
            if char is None or char is self:
                continue
            if isinstance(char, MainDps):
                if char.skill_available() or char.ultimate_available():
                    return True
            elif isinstance(char, BuffSupport) and not isinstance(char, HealSupport):
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

    def ultimate_buff_pending(self):
        # 治疗不参与"先铺大招 buff 压过环合"那条抢线(那是辅助专属);治疗优先级最低。
        return False

    def do_get_switch_priority(self, current_char, has_intro=False):
        p = super().do_get_switch_priority(current_char, has_intro)
        # 没资源时(落到 BASE_MINUS_1)再降一档: overlap填场/平局时, 宁可选别的辅助,
        # 也别按"最久没动"把治疗顶上来空放(治疗应是最后兜底)。
        if p == Priority.BASE_MINUS_1:
            return Priority.BASE_MINUS_1 - 1
        return p


class SakiriBuffSupport(BuffSupport):
    """早雾辅助:**有主C时**与辅助模板完全一致,仅技能改为长按(SKILL_DOWN_TIME);
    **无主C时**回退到 RU 的早雾(`Sakiri`)逻辑,而不是辅助那套资源/补大招。"""

    SKILL_DOWN_TIME = 0.25
    SKILL_COOLDOWN = 16.0  # 早雾技能CD 16s

    def combat_plan(self, context):
        if not self.team_has_main_dps():
            # 无主C体系(经 lw_use_do_perform 退回 planner)时: 用 RU 早雾(Sakiri)的
            # 出招计划, 而不是 BaseChar 通用版。旧版是 Sakiri.do_perform(self),
            # 该方法已随上游 planner 化删除, 对应物即 combat_plan。
            from src.char.Sakiri import Sakiri

            return Sakiri.combat_plan(self, context)
        # 有主C体系: 走 super()=BuffSupport 的 ru 风格 combat_plan(大招/技能独立动作+entry编排)。
        # 长按由 SKILL_DOWN_TIME=0.25 在 skill 的 execute(_execute_support_skill)自动生效, 无需重写。
        return super().combat_plan(context)

    def do_perform(self):
        # 有主C体系:走辅助模板逻辑;长按由 SKILL_DOWN_TIME=0.25 自动生效,无需重写出招。
        # (无主C体系由 lw_use_do_perform=False 退回 planner, 不经过这里, 见 BuffSupport)
        super().do_perform()
