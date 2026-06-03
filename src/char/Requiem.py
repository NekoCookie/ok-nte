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

    def should_force_off_field(self):
        return time.time() < self.skill_off_field_until

    def perform_free_skill_chain(self):
        self.logger.info("requiem free skill chain start")
        start = time.time()
        while time.time() - start < self.FREE_SKILL_WINDOW:
            if self.skill_available():
                if self.click_skill(time_out=1.0)[0]:
                    self.free_skill_pending = False
                    self.continues_normal_attack(0.3)
                    return

            self.normal_attack()
            self.sleep(self.FREE_SKILL_ATTACK_INTERVAL)

        self.logger.warning("requiem free skill window expired")
        self.free_skill_pending = False
        self.continues_normal_attack(0.3)

    def do_perform(self):
        self.wait_intro()
        if self.free_skill_pending:
            self.perform_free_skill_chain()
            return

        if self.should_yield_to_support():
            self.logger.info("support resource ready before requiem burst, yielding")
            self.continues_normal_attack(0.2)
            return

        used_ultimate = self.click_ultimate()
        used_skill = self.click_skill()[0]
        if used_skill:
            self.skill_off_field_until = time.time() + self.SKILL_OFF_FIELD_DURATION
            self.free_skill_pending = True
            self.logger.info("requiem skill cast, enabling off-field overlap switch")
            return

        if not used_ultimate:
            self.continues_normal_attack(self.IDLE_ATTACK_DURATION)

    def reset_state(self):
        super().reset_state()
        self.skill_off_field_until = 0.0
        self.free_skill_pending = False
