"""[lw] Retry controls for the daily-routine UI."""

from ok import og
from ok.gui.Communicate import communicate
from qfluentwidgets import FluentIcon, PushButton


class DailyRoutineTabExtMixin:
    """Attach the LW failed-item retry control without extending the RU tab behavior."""

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
