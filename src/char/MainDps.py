from src.char.BaseChar import BaseChar, Priority, Role


class MainDps(BaseChar):
    """Generic on-field damage dealer template."""

    IDLE_ATTACK_DURATION = 2.5
    IDLE_PRIORITY = 5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = Role.MAIN_DPS

    def _is_support(self, char):
        return char is not None and getattr(char, "role", Role.DEFAULT) != Role.MAIN_DPS

    def _has_resource(self, char):
        return char is not None and (char.skill_available() or char.ultimate_available())

    def support_has_resource(self):
        return any(
            self._is_support(char) and self._has_resource(char)
            for char in self.task.chars
            if char != self
        )

    def should_yield_to_support(self):
        return self.support_has_resource()

    def should_stay_on_field(self):
        return (
            self.is_current_char
            and not self.should_force_off_field()
            and not self.is_cycle_full()
            and not self.support_has_resource()
        )

    def should_force_off_field(self):
        return False

    def do_perform(self):
        self.wait_intro()
        if self.should_yield_to_support():
            self.logger.info("support resource ready, yielding main dps field time")
            self.continues_normal_attack(0.2)
            return

        used_ultimate = self.click_ultimate()
        used_skill = self.click_skill()[0]
        if not used_ultimate and not used_skill:
            self.continues_normal_attack(self.IDLE_ATTACK_DURATION)

    def count_base_priority(self):
        if not self.support_has_resource():
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = Role.SUB_DPS

    def has_resource(self):
        return self.skill_available() or self.ultimate_available()

    def do_perform(self):
        self.wait_intro()
        used_ultimate = self.click_ultimate()
        used_skill = self.click_skill()[0]
        if not used_ultimate and not used_skill:
            self.continues_normal_attack(0.2)

    def do_get_switch_priority(self, current_char, has_intro=False):
        if not self.has_resource():
            return Priority.BASE_MINUS_1
        return (
            super().do_get_switch_priority(current_char, has_intro)
            + self.RESOURCE_PRIORITY_BONUS
        )
