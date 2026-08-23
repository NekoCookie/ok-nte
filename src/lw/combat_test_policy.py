"""[lw] Shared test-mode policy for user-owned combat templates."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask


class LWCombatTestPolicyMixin:
    """Read the test-only E/Q disable switch for LW templates."""

    def lw_skills_disabled_for_test(
        self,
        config_task: "RequiemCombatConfigTask | None" = None,
    ) -> bool:
        if config_task is None:
            task = getattr(self, "task", None)
            get_task_by_class = getattr(task, "get_task_by_class", None)
            if not callable(get_task_by_class):
                return False

            from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask

            try:
                config_task = get_task_by_class(RequiemCombatConfigTask)
            except (LookupError, RuntimeError, TypeError):
                return False

        config = getattr(config_task, "config", None)
        if not hasattr(config, "get"):
            return False

        from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask

        return config.get(RequiemCombatConfigTask.CONF_DISABLE_SKILLS, False) is True
