"""[lw] Blackbird sub-DPS template backed by the current RU implementation.

Rotation: Q1 (team ATK buff) -> Q2 right away -> E (full cycle) -> the reaction swap to the
dark-attribute teammate triggers Dark Star. Blackbird's passive records the damage taken
during each Dark Star and applies a second one afterwards, so the main DPS keeps the field
for both windows. Blackbird only comes back when E is ready again, because E is the only
reason to return.
"""

import time

from src.char.Blackbird import Blackbird
from src.combat.planner import FieldClaim, Planner
from src.Labels import Labels
from src.lw.combat_test_policy import LWCombatTestPolicyMixin

DARK_STAR_HOLD = "黯星期间不回黑羽(s)"
KEYS = [DARK_STAR_HOLD]
# 黑羽副C配置的唯一默认值来源: 界面默认值和读不到配置时的兜底都读这里。
DEFAULTS = {DARK_STAR_HOLD: 10.0}


def configure_blackbird_sub_dps(task):
    task.default_config.update(DEFAULTS)
    task.config_description.update({
        DARK_STAR_HOLD: (
            "黑羽下场后至少这么久不再切回(扣除大招动画时间), 让主C打满两段黯星; "
            "此后还要等黑羽E就绪才会切回; 0=只等E就绪"
        ),
    })


def dark_star_hold_seconds(config) -> float:
    value = config.get(DARK_STAR_HOLD) if config is not None else None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return DEFAULTS[DARK_STAR_HOLD]


class BlackbirdSubDps(LWCombatTestPolicyMixin, Blackbird):
    """Short Blackbird turns that hand the Dark Star windows to the main DPS."""

    en_name = "Blackbird Sub DPS"
    cn_name = "黑羽副C"
    SECOND_ULTIMATE_WAIT = 1.5
    SECOND_ULTIMATE_POLL_INTERVAL = 0.1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.left_field_time = -1.0

    def combat_plan(self, context):
        ultimate = self.click_ultimate_action(
            can_execute=lambda _: not self.lw_skills_disabled_for_test(),
        )
        # Unlike RU, a full cycle does not hold E back: E also marks the target and keeps
        # the 16s rhythm, and the full cycle swaps to the reaction teammate either way.
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
        """Stay off field through the Dark Star windows and until E is ready again."""

        if self.is_current_char:
            return True
        hold = dark_star_hold_seconds(self._lw_config())
        if self.time_elapsed_accounting_for_freeze(self.left_field_time) < hold:
            return False
        return bool(self.skill_available())

    def switch_out(self):
        super().switch_out()
        self.left_field_time = time.time()

    def reset_state(self):
        super().reset_state()
        self.left_field_time = -1.0

    def on_combat_end(self, chars):
        super().on_combat_end(chars)
        self.left_field_time = -1.0

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
