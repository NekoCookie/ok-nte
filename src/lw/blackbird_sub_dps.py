"""[lw] Blackbird sub-DPS template backed by the current RU implementation."""

from src.char.Blackbird import Blackbird
from src.combat.planner import ActionIntent, CombatContext, Planner
from src.lw.combat_test_policy import LWCombatTestPolicyMixin

CONF_ULT_FIELD_TIME_LIMIT = "黑羽大招站场上限(s)"
DEFAULT_ULT_FIELD_TIME_LIMIT = 4.0


class BlackbirdSubDps(LWCombatTestPolicyMixin, Blackbird):
    """Keep Blackbird's Witch window short so the main DPS gets the field time.

    RU gates the in-ultimate enhanced skill with the instant-cycle rule, so with a full
    cycle and a reaction teammate the enhanced skill never fires and Blackbird attacks
    for the whole Witch duration. The Witch timer pauses off field and the team ATK buff
    stays, so a sub DPS casts one enhanced skill (or hits the time limit) and hands off.
    """

    en_name = "Blackbird Sub DPS"
    cn_name = "黑羽副C"

    def perform_in_ult(self, context: CombatContext, skill: ActionIntent):
        enhanced_skill = self.click_skill_action(
            name=f"{self}_witch_skill",
            add_tags=Planner.ActionTag.HIGH_PRIORITY,
            reason="blackbird witch enhanced skill",
            can_execute=lambda _: not self.lw_skills_disabled_for_test(),
        )
        limit = self.ult_field_time_limit()
        self.logger.info(f"blackbird sub dps witch field start, limit {limit:.1f}s")
        start = self.now()
        while (elapsed := self.now() - start) < limit:
            if elapsed > 1 and not self.ultimate_available(False):
                break
            if context.is_action_allowed(self, enhanced_skill) and self.click_skill():
                break
            self.normal_attack()
            self.sleep(0.1)
        self.logger.info(f"blackbird sub dps witch field end {self.now() - start:.2f}s")

    def ult_field_time_limit(self) -> float:
        config = self._lw_config()
        value = config.get(CONF_ULT_FIELD_TIME_LIMIT) if config is not None else None
        try:
            limit = float(value)
        except (TypeError, ValueError):
            return DEFAULT_ULT_FIELD_TIME_LIMIT
        return min(max(limit, 0.0), self.ULT_DURATION)

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
