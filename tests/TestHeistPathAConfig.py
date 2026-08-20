"""Path 1 opening-movement configuration regression tests."""

import unittest
from unittest import mock

from src.heist_path.HeistPathA import HeistPathA
from src.lw.heist_ext import PATH1_INITIAL_D_DEFAULT, PATH1_INITIAL_W_DEFAULT
from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask


class _StopRoute(Exception):
    pass


class TestHeistPathAConfig(unittest.TestCase):
    def _path(self, config):
        task = mock.MagicMock()
        config_task = mock.MagicMock()
        config_task.config = config
        task.get_task_by_class.return_value = config_task
        task.wait_and_interact.side_effect = _StopRoute
        path = HeistPathA(task)
        path.sleep = mock.MagicMock()
        return path

    def test_opening_movement_uses_requiem_configuration(self):
        path = self._path(
            {
                RequiemCombatConfigTask.CONF_HEIST_PATH1_INITIAL_W: 3.1,
                RequiemCombatConfigTask.CONF_HEIST_PATH1_INITIAL_D: 2.2,
            }
        )

        with self.assertRaises(_StopRoute):
            path.goto_lg1()

        self.assertEqual(
            [call.args[0] for call in path.sleep.call_args_list[:6]],
            [0.81, 0.32, 0.16, 3.1, 2.2, 0.37],
        )

    def test_opening_movement_keeps_existing_timing_without_configuration(self):
        path = self._path({})

        with self.assertRaises(_StopRoute):
            path.goto_lg1()

        self.assertEqual(
            [call.args[0] for call in path.sleep.call_args_list[:6]],
            [0.81, 0.32, 0.16, PATH1_INITIAL_W_DEFAULT, PATH1_INITIAL_D_DEFAULT, 0.37],
        )
