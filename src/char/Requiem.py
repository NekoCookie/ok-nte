import time

import win32api

from src.char.BaseChar import BaseChar
from src.char.MainDps import MainDps


class Requiem(MainDps):
    """Main DPS template with off-field skill overlap after skill cast."""

    SKILL_OFF_FIELD_DURATION = 3.0
    FREE_SKILL_WINDOW = 12.0
    FREE_SKILL_ATTACK_INTERVAL = 0.18
    FREE_SKILL_FOLLOWUP_ATTACK_DURATION = 0.85

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
            if self.ultimate_available():
                if self.click_ultimate():
                    return

            if self.skill_available():
                if self.click_skill(time_out=1.0)[0]:
                    self.free_skill_pending = False
                    self.free_skill_expires_at = 0.0
                    self.free_skill_followup_attack()
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

    def free_skill_followup_attack(self):
        start = time.time()
        while time.time() - start < self.FREE_SKILL_FOLLOWUP_ATTACK_DURATION:
            if self.ultimate_available():
                if self.click_ultimate():
                    return
            if self.should_yield_to_support(include_probe=False):
                self.logger.info("support confirmed resource during requiem follow-up attack")
                return
            self.normal_attack()
            self.sleep(self.FREE_SKILL_ATTACK_INTERVAL)

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


class RequiemJumpAttackTest(BaseChar):
    """Press 6 to execute a single 4A + jump attack timing test."""

    HOTKEY = "6"
    END_RECOVERY = 0.15
    POLL_INTERVAL = 0.03
    # Recorded from the user's working mouse macro:
    # repeated left click down/up timings, then Space, then follow-up left clicks.
    RECORDED_MACRO = [
        ("click", 0.096),
        ("sleep", 0.087),
        ("click", 0.064),
        ("sleep", 0.095),
        ("click", 0.068),
        ("sleep", 0.099),
        ("click", 0.072),
        ("sleep", 0.092),
        ("click", 0.084),
        ("sleep", 0.077),
        ("click", 0.085),
        ("sleep", 0.074),
        ("click", 0.093),
        ("sleep", 0.082),
        ("click", 0.098),
        ("sleep", 0.077),
        ("click", 0.092),
        ("sleep", 0.326),
        ("key", "space", 0.100),
        ("sleep", 0.002),
        ("click", 0.074),
        ("sleep", 0.042),
        ("click", 0.082),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hotkey_was_down = False

    def perform(self):
        self.last_perform = time.time()
        if self.consume_test_hotkey():
            self.do_perform()
        else:
            self.sleep(self.POLL_INTERVAL)

    def consume_test_hotkey(self):
        vk_code = win32api.VkKeyScan(self.HOTKEY)
        if vk_code == -1:
            return False
        pressed = bool(win32api.GetAsyncKeyState(vk_code & 0xFF) & 0x8000)
        triggered = pressed and not self._hotkey_was_down
        self._hotkey_was_down = pressed
        return triggered

    def do_perform(self):
        self.logger.info("requiem jump attack recorded macro start")
        start = time.perf_counter()
        for step_index, step in enumerate(self.RECORDED_MACRO, start=1):
            action = step[0]
            if action == "click":
                down_time = step[1]
                self.logger.info(
                    f"requiem jump attack macro step={step_index} click "
                    f"at {time.perf_counter() - start:.3f}s down_time={down_time:.3f}s"
                )
                self.click(down_time=down_time)
            elif action == "key":
                key, down_time = step[1], step[2]
                self.logger.info(
                    f"requiem jump attack macro step={step_index} key={key} "
                    f"at {time.perf_counter() - start:.3f}s down_time={down_time:.3f}s"
                )
                self.send_key(key, down_time=down_time)
            else:
                time.sleep(step[1])

        time.sleep(self.END_RECOVERY)
        end_elapsed = time.perf_counter() - start
        self.logger.info(f"requiem jump attack recorded macro end elapsed={end_elapsed:.3f}s")
