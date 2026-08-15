"""LW-only daily task policy extensions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from src.tasks.DailyTask import DailyTask

    _DailyTaskProxy = DailyTask
else:

    class _DailyTaskProxy:
        pass


class DailyTaskExtMixin(_DailyTaskProxy):
    """Keep LW ordering and stamina-target policy outside the RU task flow."""

    def lw_daily_task_entries(self) -> list[tuple[str, bool, Callable]]:
        coffee_modes = [self.COFFEE_MODE_CLAIM_AND_RESTOCK, self.COFFEE_MODE_AUTO]
        return [
            (self.CONF_CLAIM_MAIL, self._task_enabled(self.CONF_CLAIM_MAIL, True), self.claim_mail),
            (
                self.CONF_COMPLETE_DAILY,
                self._task_enabled(self.CONF_COMPLETE_DAILY, True),
                self.complete_daily_activities,
            ),
            (
                self.CONF_CINEMA_DATE,
                self._task_enabled(self.CONF_CINEMA_DATE, False),
                self.run_cinema_task,
            ),
            (
                self.CONF_FOUNTAIN_SIGN,
                self._task_enabled(self.CONF_FOUNTAIN_SIGN, self.TASK_NONE, self.TASK_NONE),
                self.run_fountain_sign_task,
            ),
            (self.CONF_FURNITURE, self._task_enabled(self.CONF_FURNITURE, False), self.run_furniture_task),
            (self.CONF_GIFT, self._task_enabled(self.CONF_GIFT, False), self.run_gift_task),
            (
                self.CONF_CLAIM_ACTIVITY,
                self._task_enabled(self.CONF_CLAIM_ACTIVITY, True),
                self.claim_activity_rewards,
            ),
            (
                self.CONF_COFFEE_TASK,
                self.config.get(self.CONF_COFFEE_TASK) in coffee_modes,
                self.run_coffee_task,
            ),
            (
                self.CONF_CLAIM_BP,
                self._task_enabled(self.CONF_CLAIM_BP, True),
                self.claim_battle_pass_rewards,
            ),
        ]

    def lw_daily_activity_target_reached(self, used_stamina: int) -> bool:
        target_stamina = self.config.get(self.DAILY_STAMINA_TARGET, 180)
        return used_stamina >= target_stamina

    @staticmethod
    def lw_daily_activity_target_message() -> str:
        return "当前体力消耗已达目标，跳过每日活跃度任务"
