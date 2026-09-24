"""[lw] Globals lifecycle extensions."""

from src.lw.task_info_layout import install_task_info_layout
from src.ui.foundation.dialogs import install_confirmation_handler
from src.ui.foundation.overlay import install_overlay_window


class GlobalsExtMixin:
    """Install LW UI layout behavior after the framework creates its main window."""

    def on_show_main_window(self, main_window):
        install_task_info_layout(main_window)
        main_window.setMinimumSize(1200, 800)
        main_window._confirmation_handler = install_confirmation_handler(main_window)
        install_overlay_window(main_window)
