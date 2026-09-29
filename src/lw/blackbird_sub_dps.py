"""[lw] Blackbird sub-DPS template backed by the current RU implementation.

Rotation: Q1 (team ATK buff) -> Q2 right away -> E (full cycle) -> the reaction swap to the
dark-attribute teammate triggers Dark Star. Blackbird's passive records the damage taken
during each Dark Star and applies a second one afterwards, so the main DPS keeps the field
for both windows.

Dark Star pays 20% of the damage recorded in the window, so Blackbird's E follows the main
DPS ultimates instead of its own cooldown: Blackbird comes back once E is ready and a main
DPS ultimate is ready, and the main DPS keep their burst until Dark Star has been triggered.
Both waits are capped so neither side stalls when the other never becomes ready.
"""

import time

from src.char.Blackbird import Blackbird
from src.combat.planner import FieldClaim, Planner
from src.Labels import Labels
from src.lw.combat_test_policy import LWCombatTestPolicyMixin

DARK_STAR_HOLD = "黯星期间不回黑羽(s)"
SKILL_WAIT = "黑羽E等主C大招最长(s)"
BURST_HOLD = "主C大招等黑羽黯星最长(s)"
KEYS = [DARK_STAR_HOLD, SKILL_WAIT, BURST_HOLD]
# 黑羽副C配置的唯一默认值来源: 界面默认值和读不到配置时的兜底都读这里。
DEFAULTS = {DARK_STAR_HOLD: 10.0, SKILL_WAIT: 8.0, BURST_HOLD: 5.0}


def configure_blackbird_sub_dps(task):
    task.default_config.update(DEFAULTS)
    task.config_description.update({
        DARK_STAR_HOLD: (
            "黑羽下场后至少这么久不再切回(扣除大招动画时间), 让主C打满两段黯星; "
            "此后还要等黑羽E就绪才会切回; 0=只等E就绪"
        ),
        SKILL_WAIT: (
            "黑羽E就绪后要等安魂曲/残虹任一大招就绪才切回触发黯星; "
            "等超过这么久(扣除大招动画时间)就不等大招直接切回放E"
        ),
        BURST_HOLD: (
            "黑羽即将切回触发黯星时, 安魂曲/残虹先不放大招和安魂曲真技能, 留到黯星里; "
            "最多憋这么久(扣除大招动画时间), 超时照常放"
        ),
    })


def config_seconds(config, key) -> float:
    value = config.get(key) if config is not None else None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return DEFAULTS[key]


def dark_star_setup_pending(char) -> bool:
    """Whether ``char`` should keep its burst because Blackbird is about to trigger Dark Star."""

    for mate in getattr(getattr(char, "task", None), "chars", None) or ():
        if mate is not char and isinstance(mate, BlackbirdSubDps):
            return mate.holds_team_burst()
    return False


class BlackbirdSubDps(LWCombatTestPolicyMixin, Blackbird):
    """Short Blackbird turns that line Dark Star up with the main DPS ultimates."""

    en_name = "Blackbird Sub DPS"
    cn_name = "黑羽副C"
    SECOND_ULTIMATE_WAIT = 1.5
    SECOND_ULTIMATE_POLL_INTERVAL = 0.1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.left_field_time = -1.0
        self.skill_ready_since = -1.0
        self.burst_hold_since = -1.0

    def combat_plan(self, context):
        ultimate = self.click_ultimate_action(
            can_execute=lambda _: not self.lw_skills_disabled_for_test(),
        )
        # Unlike RU, a full cycle does not hold E back: E also marks the target, and the
        # full cycle swaps to the reaction teammate either way.
        skill = self.click_skill_action(
            add_tags=Planner.ActionTag.HIGH_PRIORITY,
            can_execute=lambda _: not self.lw_skills_disabled_for_test(),
        )
        claims = []
        if self.skill_available() and not self.lw_skills_disabled_for_test():
            claims.append(FieldClaim.normal(reason="sub dps dark star cycle"))

        def entry():
            if self.in_ult is None:
                self.in_ult = bool(
                    self.task.wait_until(
                        lambda: self.task.find_one(Labels.blackbird_ult_2),
                        post_action=self.click_with_interval,
                        time_out=0.5,
                    )
                )
            if not self.in_ult and (yield ultimate):
                self.in_ult = True
                self._wait_for_second_ultimate()
            if self.in_ult and (yield ultimate.repeat_for_entry()):
                self.in_ult = False
            yield skill

        return self.plan(skill, ultimate, claims=claims, entry=entry)

    def _wait_for_second_ultimate(self) -> bool:
        deadline = self.now() + self.SECOND_ULTIMATE_WAIT
        while not self.ultimate_available():
            if self.now() >= deadline:
                self.logger.info("blackbird second ultimate unavailable; continuing with skill")
                return False
            self.normal_attack()
            self.sleep(self.SECOND_ULTIMATE_POLL_INTERVAL)
        return True

    def lw_can_switch_in(self):
        """Come back for E only after Dark Star, with a main DPS ultimate ready."""

        if self.is_current_char:
            return True
        config = self._lw_config()
        if self._elapsed(self.left_field_time) < config_seconds(config, DARK_STAR_HOLD):
            return False
        if not self.skill_available():
            self.skill_ready_since = -1.0
            return False
        if self.skill_ready_since < 0:
            self.skill_ready_since = self._stamp()
        if self._main_dps_ultimate_ready():
            return True
        return self._elapsed(self.skill_ready_since) >= config_seconds(config, SKILL_WAIT)

    def holds_team_burst(self) -> bool:
        """Ask the main DPS to keep their burst while this turn is about to start."""

        if (
            self.is_current_char
            or getattr(self, "is_dead", False)
            or self.lw_skills_disabled_for_test()
            or not self.lw_can_switch_in()
        ):
            self.burst_hold_since = -1.0
            return False
        if self.burst_hold_since < 0:
            self.burst_hold_since = self._stamp()
            self.logger.info("main dps burst held for blackbird dark star")
        return self._elapsed(self.burst_hold_since) < config_seconds(
            self._lw_config(), BURST_HOLD
        )

    def _main_dps_ultimate_ready(self) -> bool:
        return any(
            not getattr(char, "is_dead", False) and char.ultimate_available()
            for char in self.get_teammates_by_role(Planner.Role.MAIN_DPS)
        )

    @staticmethod
    def _stamp() -> float:
        # Same clock as the freeze records behind time_elapsed_accounting_for_freeze.
        return time.time()

    def _elapsed(self, since: float) -> float:
        return self.time_elapsed_accounting_for_freeze(since)

    def switch_out(self):
        super().switch_out()
        self.left_field_time = self._stamp()
        self.skill_ready_since = -1.0
        self.burst_hold_since = -1.0

    def reset_state(self):
        super().reset_state()
        self._reset_dark_star_state()

    def on_combat_end(self, chars):
        super().on_combat_end(chars)
        self._reset_dark_star_state()

    def _reset_dark_star_state(self):
        self.left_field_time = -1.0
        self.skill_ready_since = -1.0
        self.burst_hold_since = -1.0

    def _lw_config(self):
        get_task_by_class = getattr(getattr(self, "task", None), "get_task_by_class", None)
        if not callable(get_task_by_class):
            return None

        from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask

        try:
            config_task = get_task_by_class(RequiemCombatConfigTask)
        except (LookupError, RuntimeError, TypeError):
            return None
        config = getattr(config_task, "config", None)
        return config if hasattr(config, "get") else None
