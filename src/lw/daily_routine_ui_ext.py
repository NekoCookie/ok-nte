"""[lw] Daily-routine UI extensions."""

from ok import og
from ok.gui.Communicate import communicate
from ok.gui.tasks.TaskCard import TaskCard
from qfluentwidgets import FluentIcon, PushButton

from src.tasks.SwitchAccountTask import SwitchAccountTask


class DailyRoutineTabExtMixin:
    """Attach LW controls to the RU daily-routine tab through explicit hooks."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lw_switch_account_card = None

    def lw_install_switch_account_card(self):
        if self._lw_switch_account_card is not None:
            return

        switch_account_task = self.get_task(SwitchAccountTask)
        if switch_account_task is None:
            return

        card = TaskCard(switch_account_task, True)
        card.setParent(self.routine_settings_view)
        self.routine_settings_layout.addWidget(card)
        card.show()
        self._lw_switch_account_card = card

    def lw_install_retry_button(self, action_layout):
        self.retry_button = PushButton(FluentIcon.SYNC, self.tr("重试失败项"), self.action_bar)
        self.retry_button.setEnabled(False)
        action_layout.addWidget(self.retry_button)
        self.retry_button.clicked.connect(self.lw_retry_failed_items)
        communicate.task.connect(self.lw_sync_retry_button)

    def lw_retry_button_enabled(self, routine_task=None):
        routine_task = routine_task or self._routine_task()
        return bool(
            routine_task
            and not routine_task.enabled
            and routine_task.lw_can_retry_failed_items()
        )

    def lw_retry_failed_items(self):
        routine_task = self._routine_task()
        if routine_task is None:
            return
        if routine_task.lw_start_retry_failed_items(self.lw_retry_start_controller()):
            self.retry_button.setEnabled(False)

    def lw_retry_start_controller(self):
        return og.app.start_controller

    def lw_sync_retry_button(self, task=None):
        if task is None or task is self._routine_task():
            self.retry_button.setEnabled(self.lw_retry_button_enabled())
