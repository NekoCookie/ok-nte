"""Path 1 opening-movement configuration regression tests."""

import unittest
from unittest import mock

from src.combat.BaseCombatTask import BaseCombatTask
from src.heist_path.HeistPathA import HeistPathA
from src.lw.heist_ext import (
    CONF_PATH1_INITIAL_D,
    CONF_PATH1_INITIAL_W,
    PATH1_INITIAL_D_DEFAULT,
    PATH1_INITIAL_W_DEFAULT,
)
from src.tasks.AutoHeistTask import AutoHeistTask
from src.tasks.BaseNTETask import BaseNTETask


class _StopRoute(Exception):
    pass


class TestHeistPathAConfig(unittest.TestCase):
    def _path(self, config):
        task = mock.MagicMock()
        task.config = config
        task.wait_and_interact.side_effect = _StopRoute
        path = HeistPathA(task)
        path.sleep = mock.MagicMock()
        return path

    def test_opening_movement_uses_heist_configuration(self):
        path = self._path(
            {
                CONF_PATH1_INITIAL_W: 3.1,
                CONF_PATH1_INITIAL_D: 2.2,
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

    def test_heist_task_exposes_opening_timing_configuration(self):
        task = AutoHeistTask.__new__(AutoHeistTask)
        task.default_config = {}
        task.config_type = {}
        task.config_description = {}
        task.get_app_locale = mock.Mock(return_value="zh_CN")

        with mock.patch.object(BaseCombatTask, "__init__", return_value=None):
            AutoHeistTask.__init__(task)

        self.assertEqual(task.default_config[task.CONF_PATH1_INITIAL_W], PATH1_INITIAL_W_DEFAULT)
        self.assertEqual(task.default_config[task.CONF_PATH1_INITIAL_D], PATH1_INITIAL_D_DEFAULT)
        self.assertIn(task.CONF_PATH1_INITIAL_W, task.config_description)
        self.assertIn(task.CONF_PATH1_INITIAL_D, task.config_description)

    def test_load_config_migrates_existing_requiem_timing_once(self):
        task = AutoHeistTask.__new__(AutoHeistTask)
        task.config = {}
        task.logger = mock.MagicMock()
        legacy_config = {CONF_PATH1_INITIAL_W: 3.1, CONF_PATH1_INITIAL_D: 2.2}

        with (
            mock.patch.object(BaseNTETask, "load_config"),
            mock.patch(
                "src.tasks.AutoHeistTask.read_json_file",
                side_effect=[None, legacy_config],
            ),
        ):
            task.load_config()

        self.assertEqual(task.config[task.CONF_PATH1_INITIAL_W], 3.1)
        self.assertEqual(task.config[task.CONF_PATH1_INITIAL_D], 2.2)
        task.logger.info.assert_called_once_with("migrated Path 1 opening timings from Requiem config")
