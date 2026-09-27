import unittest
from unittest import mock

import ok.core.events as core_events
from PySide6.QtWidgets import QApplication
from ok.ui.qt.events import install_qt_event_dispatcher

from src.events import communicate
from src.globals import Globals


class _ExitEvent:
    def bind_stop(self, _obj):
        pass


class GlobalsRuntimeStartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        previous = core_events._dispatcher
        self.addCleanup(core_events.set_event_dispatcher, previous)
        install_qt_event_dispatcher()

    def test_start_success_starts_runtime_services_through_qt_dispatcher(self):
        # ok-script 2 drops callbacks whose owner is an uninitialized QObject,
        # which previously left OpenVINO waiters blocked forever.
        globals_ = Globals(_ExitEvent())
        self.addCleanup(communicate.start_success.disconnect, globals_._start_runtime_services)

        with mock.patch.object(globals_._runtime_services, "start") as start:
            communicate.start_success.emit()

        start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
