import time

from src.char.MainDps import MainDps


class Requiem(MainDps):
    """Main DPS template with off-field skill overlap after skill cast."""

    SKILL_OFF_FIELD_DURATION = 3.0
    FREE_SKILL_WINDOW = 12.0
    FREE_SKILL_ATTACK_INTERVAL = 0.18

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.skill_off_field_until = 0.0
        self.free_skill_pending = False
        self.free_skill_expires_at = 0.0

    def should_force_off_field(self):
        return time.time() < self.skill_off_field_until

    def perform_free_skill_chain(self):
        self.logger.info("requiem free skill chain start")
        while time.time() < self.free_skill_expires_at:
            if self.skill_available():
                if self.click_skill(time_out=1.0)[0]:
                    self.free_skill_pending = False
                    self.free_skill_expires_at = 0.0
                    self.continues_normal_attack(0.3)
                    return

            if self.should_yield_to_support(include_probe=False):
                self.logger.info("support confirmed resource during requiem free skill window")
                self.continues_normal_attack(0.1)
                return

            self.normal_attack()
            self.sleep(self.FREE_SKILL_ATTACK_INTERVAL)

        self.logger.warning("requiem free skill window expired")
        self.free_skill_pending = False
        self.free_skill_expires_at = 0.0
        self.continues_normal_attack(0.3)

    def do_perform(self):
        self.wait_intro()
        if self.free_skill_pending:
            self.perform_free_skill_chain()
            return

        used_ultimate = self.click_ultimate()
        used_skill = self.click_skill()[0]
        if used_skill:
            now = time.time()
            self.skill_off_field_until = now + self.SKILL_OFF_FIELD_DURATION
            self.free_skill_pending = True
            self.free_skill_expires_at = now + self.FREE_SKILL_WINDOW
            self.logger.info("requiem skill cast, enabling off-field overlap switch")
            return

        if used_ultimate:
            return

        if self.should_yield_to_support():
            self.logger.info("support resource ready after requiem action check, yielding")
            self.continues_normal_attack(0.2)
            return

        self.idle_normal_attack()

    def reset_state(self):
        super().reset_state()
        self.skill_off_field_until = 0.0
        self.free_skill_pending = False
        self.free_skill_expires_at = 0.0
