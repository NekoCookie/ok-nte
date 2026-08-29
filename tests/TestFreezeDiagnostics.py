from collections import deque
import unittest
from unittest import mock

from src.combat.BaseCombatTask import BaseCombatTask


class TestFreezeDiagnostics(unittest.TestCase):
    def _task(self):
        task = object.__new__(BaseCombatTask)
        task.freeze_durations = deque()
        task.FREEZE_DURATION_RETENTION_SECONDS = 1200
        task.SKILL_CD_DIAG = True
        task.log_info = mock.Mock()
        task.log_debug_gated = mock.Mock()
        return task

    def test_lw_diagnostic_cause_does_not_change_ru_freeze_tuple_shape(self):
        task = self._task()

        with mock.patch("src.lw.combat_ext.time.time", return_value=100.0):
            task.lw_add_freeze_duration(100.0, duration=1.5, cause="ultimate")

        self.assertEqual(list(task.freeze_durations), [(100.0, 1.5, 0.1)])
        self.assertEqual(task._lw_freeze_causes, {100.0: "ultimate"})
        task.log_info.assert_called_once()

    def test_cast_diagnostic_is_inert_by_default(self):
        task = self._task()
        task.SKILL_CD_DIAG = False
        task.get_cd = mock.Mock()

        task.diag_cast(0, 100.0, "diagnostic")

        task.get_cd.assert_not_called()
        task.log_info.assert_not_called()


if __name__ == "__main__":
    unittest.main()
