# [lw] NTEInteraction 的用户扩展: 窗口前台状态稳定后再投递点击,
# 避免游戏窗口真实前台切换的瞬间吞掉后台投递的鼠标消息。

from src.lw.window_focus import WindowFocusStabilizer


class NTEInteractionExtMixin:
    def lw_init_focus_stabilizer(self):
        self._focus_stabilizer = WindowFocusStabilizer(
            lambda: self.hwnd_window.is_foreground()
        )

    def lw_observe_focus(self, visible):
        self._focus_stabilizer.observe(visible)

    def lw_stabilize_focus(self):
        self._focus_stabilizer.stable()
