"""[lw] Globals lifecycle extensions."""

from src.lw.task_info_layout import install_task_info_layout


class GlobalsExtMixin:
    """Install LW UI layout behavior after the framework creates its main window."""

    def on_show_main_window(self, main_window):
        install_task_info_layout(main_window)
