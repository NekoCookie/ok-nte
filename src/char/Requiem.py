import time

from src.char.MainDps import MainDps


class Requiem(MainDps):
    """Main DPS template with off-field skill overlap after skill cast."""

    SKILL_OFF_FIELD_DURATION = 3.0
    PRE_SKILL_ULTIMATE_WAIT = 0.3
    # 真技能放出"之前"先平A出手进入交战。开战瞬间安魂曲还没真正攻击,
    # 直接放技能会打空(技能消失);先平A一下交战,技能才稳。与切人时机无关。
    # 只在"真技能"分支生效;免费技能是中途放的(已交战),不需要。可被配置覆盖。
    SKILL_ENGAGE_ATTACK = 0.1
    CONF_ENGAGE_ATTACK = "安魂曲技能前平A(s)"
    # 真技能 CD 固定 16s,从真技能释放那刻起算;免费技能不影响 CD。
    # 用"距上次真技能是否 >= SKILL_CD"来区分真技能 / 免费技能,而不是猜窗口。
    SKILL_CD = 16.0
    FREE_SKILL_ATTACK_INTERVAL = 0.1
    FREE_SKILL_FOLLOWUP_ATTACK_DURATION = 0.85

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.skill_off_field_until = 0.0
        self.last_real_skill_time = 0.0

    def should_force_off_field(self):
        return time.time() < self.skill_off_field_until

    def real_skill_ready(self):
        """真技能 CD 是否走完(走完 → 下一发是真技能,否则是免费技能)。"""
        return time.time() - self.last_real_skill_time >= self.SKILL_CD

    def engage_attack_duration(self):
        """真技能前的起手平A时长,优先读自动战斗任务的配置,便于实时调。"""
        try:
            return max(0.0, float(self.task.config.get(self.CONF_ENGAGE_ATTACK, self.SKILL_ENGAGE_ATTACK)))
        except (AttributeError, TypeError, ValueError):
            return self.SKILL_ENGAGE_ATTACK

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

        used_ultimate = self.click_ultimate(wait_if_cd_ready=self.PRE_SKILL_ULTIMATE_WAIT)

        if self.skill_available():
            if self.real_skill_ready():
                # 先平A出手进入交战,再放真技能,否则开战瞬间直接放会打空。
                engage = self.engage_attack_duration()
                if engage > 0:
                    self.continues_normal_attack(engage)
                # 锚点取按键时刻(起手平A之后),避免 click_skill 耗时拉偏 CD 计时。
                cast_at = time.time()
                if self.click_skill()[0]:
                    self.last_real_skill_time = cast_at
                    self.skill_off_field_until = time.time() + self.SKILL_OFF_FIELD_DURATION
                    self.logger.info(
                        f"requiem real skill cast (engage {engage:.2f}s), off-field overlap switch"
                    )
                    return
            else:
                if self.click_skill(time_out=1.0)[0]:
                    # 免费技能:留场接平A,绝不推进 last_real_skill_time,也不触发下场。
                    self.logger.info("requiem free skill cast, staying on field")
                    self.free_skill_followup_attack()
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
        self.last_real_skill_time = 0.0
