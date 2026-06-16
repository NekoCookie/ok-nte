import time

from src.char.BaseChar import BaseChar, Priority, Role


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

    def _has_resource(self, char):
        if char is None:
            return False
        if hasattr(char, "has_confirmed_resource"):
            return char.has_confirmed_resource()
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

    def do_perform(self):
        self.wait_intro()
        if self.should_yield_to_support():
            self.logger.info("support resource ready, yielding main dps field time")
            self.continues_normal_attack(0.2)
            return

        used_ultimate = self.click_ultimate()
        used_skill = self.click_skill()[0]
        if not used_ultimate and not used_skill:
            self.idle_normal_attack()

    def count_base_priority(self):
        if not self.should_yield_to_support():
            return self.IDLE_PRIORITY
        return 0

    def switch_next_char(self, post_action=None, free_intro=False):
        if self.should_stay_on_field():
            self.logger.debug("main dps stays on field during team downtime")
            return
        super().switch_next_char(post_action=post_action, free_intro=free_intro)


class BuffSupport(BaseChar):
    """Generic buff/support template that takes priority when resources are ready."""

    RESOURCE_PRIORITY_BONUS = Priority.SKILL_AVAILABLE
    RESOURCE_PROBE_INTERVAL = 20.0
    RESOURCE_RECHECK_AFTER_USE_INTERVAL = 18.0
    RESOURCE_PROBE_PRIORITY = Priority.BASE
    ULTIMATE_COMBAT_SETTLE_TIMEOUT = 0.8
    ULTIMATE_COMBAT_SETTLE_CLICK = True

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

    def do_perform(self):
        if not self.team_has_main_dps():
            super().do_perform()
            return

        self.wait_intro()
        used_ultimate = self.click_ultimate()
        used_skill = self.click_skill()[0]
        self.update_resource_after_perform(used_ultimate, used_skill)
        if not used_ultimate and not used_skill:
            self.continues_normal_attack(0.2)

    def do_get_switch_priority(self, current_char, has_intro=False):
        if not self.team_has_main_dps():
            return super().do_get_switch_priority(current_char, has_intro)

        if self.has_confirmed_resource():
            return (
                super().do_get_switch_priority(current_char, has_intro)
                + self.RESOURCE_PRIORITY_BONUS
            )
        if self.needs_resource_probe():
            return self.RESOURCE_PROBE_PRIORITY
        return Priority.BASE_MINUS_1


class SakiriBuffSupport(BuffSupport):
    """Buff support variant for Sakiri that holds skill."""

    SKILL_DOWN_TIME = 0.25

    def do_perform(self):
        self.wait_intro()
        used_ultimate = self.click_ultimate()
        used_skill = self.click_skill(down_time=self.SKILL_DOWN_TIME)[0]
        if not self.team_has_main_dps():
            if not used_ultimate and not used_skill:
                self.continues_normal_attack(0.2)
            return

        self.update_resource_after_perform(used_ultimate, used_skill)
        if not used_ultimate and not used_skill:
            self.continues_normal_attack(0.2)
