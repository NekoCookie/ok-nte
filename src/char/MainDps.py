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

    def should_yield_to_support(self):
        return self.support_has_resource() or self.support_needs_probe()

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
    RESOURCE_PROBE_INTERVAL = 10.0
    RESOURCE_PROBE_PRIORITY = Priority.BASE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = Role.SUB_DPS
        self.last_resource_probe = 0.0
        self.resource_cache_confirmed = False

    def has_resource(self):
        return self.skill_available() or self.ultimate_available()

    def has_cd_cache(self):
        return self.index in self.task.cds

    def has_confirmed_resource(self):
        if self.is_current_char:
            return self.has_resource()
        return self.resource_cache_confirmed and self.has_cd_cache() and self.has_resource()

    def needs_resource_probe(self):
        if self.is_current_char or self.has_confirmed_resource():
            return False
        return time.time() - self.last_resource_probe >= self.RESOURCE_PROBE_INTERVAL

    def do_perform(self):
        self.wait_intro()
        self.last_resource_probe = time.time()
        used_ultimate = self.click_ultimate()
        used_skill = self.click_skill()[0]
        self.resource_cache_confirmed = used_ultimate or used_skill
        if not used_ultimate and not used_skill:
            self.continues_normal_attack(0.2)

    def do_get_switch_priority(self, current_char, has_intro=False):
        if self.has_confirmed_resource():
            return (
                super().do_get_switch_priority(current_char, has_intro)
                + self.RESOURCE_PRIORITY_BONUS
            )
        if self.needs_resource_probe():
            return self.RESOURCE_PROBE_PRIORITY
        return Priority.BASE_MINUS_1
