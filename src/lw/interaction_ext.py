# [lw] NTEInteraction 的用户扩展: 窗口前台状态稳定后再投递点击,
# 避免游戏窗口真实前台切换的瞬间吞掉后台投递的鼠标消息。

from src.lw.window_focus import WindowFocusStabilizer


class NTEInteractionExtMixin:
    LW_FOCUS_STABILIZE_RETRIES = 2

    def lw_init_focus_stabilizer(self):
        self._focus_stabilizer = WindowFocusStabilizer(
            lambda: self.hwnd_window.is_foreground()
        )

    def lw_observe_focus(self, visible):
        self._focus_stabilizer.observe(visible)

    def lw_stabilize_focus(self):
        """Return whether input may be posted after the foreground has settled."""
        return self._focus_stabilizer.stable()

    def lw_stabilize_click_focus(self):
        """Retry one activation while a foreground transition is still settling."""

        for attempt in range(self.LW_FOCUS_STABILIZE_RETRIES):
            if self.lw_stabilize_focus():
                return True
            if attempt + 1 < self.LW_FOCUS_STABILIZE_RETRIES:
                self.try_activate()
        return False
