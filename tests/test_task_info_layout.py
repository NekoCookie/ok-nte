import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy

from src.lw.task_info_layout import (
    calculate_task_info_table_height,
    install_task_info_layout,
)


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class _Timer:
    def __init__(self):
        self.timeout = _Signal()


class _Header:
    def __init__(self, height):
        self._height = height

    def height(self):
        return self._height


class _ScrollBar:
    def __init__(self, visible=False, height=0):
        self._visible = visible
        self._height = height

    def isVisible(self):
        return self._visible

    def height(self):
        return self._height


class _Table:
    def __init__(self, row_heights):
        self.row_heights = row_heights
        self.fixed_height = None
        self.geometry_updates = 0
        self.size_policy = None
        self.vertical_scroll_bar_policy = None

    def horizontalScrollBar(self):
        return _ScrollBar()

    def horizontalHeader(self):
        return _Header(30)

    def rowCount(self):
        return len(self.row_heights)

    def rowHeight(self, row):
        return self.row_heights[row]

    def frameWidth(self):
        return 1

    def setSizePolicy(self, horizontal, vertical):
        self.size_policy = (horizontal, vertical)

    def setVerticalScrollBarPolicy(self, policy):
        self.vertical_scroll_bar_policy = policy

    def setFixedHeight(self, height):
        self.fixed_height = height

    def updateGeometry(self):
        self.geometry_updates += 1


class _Container:
    def __init__(self):
        self.geometry_updates = 0
        self.size_policy = None

    def setSizePolicy(self, horizontal, vertical):
        self.size_policy = (horizontal, vertical)

    def updateGeometry(self):
        self.geometry_updates += 1


class _TaskTab:
    def __init__(self, row_heights):
        self.task_info_table = _Table(row_heights)
        self.task_info_container = _Container()
        self.timer = _Timer()


class _MainWindow:
    def __init__(self, task_tab):
        self.trigger_tab = None
        self.onetime_tab = task_tab
        self.grouped_task_tabs = []


class TestTaskInfoLayout(unittest.TestCase):
    def test_height_always_includes_every_row(self):
        self.assertEqual(92, calculate_task_info_table_height(30, [30, 30], frame_width=1))
        self.assertEqual(
            332,
            calculate_task_info_table_height(30, [100, 100, 100], frame_width=1),
        )

    def test_install_updates_height_after_framework_timer_refresh(self):
        task_tab = _TaskTab([30, 30])
        main_window = _MainWindow(task_tab)

        install_task_info_layout(main_window)

        self.assertEqual(92, task_tab.task_info_table.fixed_height)
        self.assertEqual(
            (QSizePolicy.Expanding, QSizePolicy.Fixed),
            task_tab.task_info_container.size_policy,
        )
        self.assertEqual(
            Qt.ScrollBarAlwaysOff,
            task_tab.task_info_table.vertical_scroll_bar_policy,
        )
        self.assertEqual(1, len(task_tab.timer.timeout.callbacks))

        task_tab.task_info_table.row_heights = [30]
        task_tab.timer.timeout.callbacks[0]()
        self.assertEqual(62, task_tab.task_info_table.fixed_height)

        install_task_info_layout(main_window)
        self.assertEqual(1, len(task_tab.timer.timeout.callbacks))


if __name__ == "__main__":
    unittest.main()
