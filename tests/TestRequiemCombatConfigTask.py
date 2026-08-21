"""安魂曲战斗配置任务重命名兼容测试。"""

import os
import unittest
from unittest import mock

from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask


class TestRequiemCombatConfigTaskMigration(unittest.TestCase):
    def make_task(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task.logger = mock.MagicMock()
        return task

    def test_load_config_copies_legacy_config_once(self):
        task = self.make_task()
        with (
            mock.patch.object(BaseNTETask, "load_config") as parent_load,
            mock.patch("src.tasks.trigger.RequiemCombatConfigTask.os.path.exists", return_value=False),
            mock.patch("src.tasks.trigger.RequiemCombatConfigTask.os.path.isfile", return_value=True),
            mock.patch("src.tasks.trigger.RequiemCombatConfigTask.shutil.copyfile") as copyfile,
        ):
            task.load_config()

        legacy_file, current_file = copyfile.call_args.args
        self.assertEqual(os.path.basename(legacy_file), "RequiemJumpAttackTestTask.json")
        self.assertEqual(os.path.basename(current_file), "RequiemCombatConfigTask.json")
        parent_load.assert_called_once_with()

    def test_load_config_does_not_overwrite_current_config(self):
        task = self.make_task()
        with (
            mock.patch.object(BaseNTETask, "load_config") as parent_load,
            mock.patch("src.tasks.trigger.RequiemCombatConfigTask.os.path.exists", return_value=True),
            mock.patch("src.tasks.trigger.RequiemCombatConfigTask.shutil.copyfile") as copyfile,
        ):
            task.load_config()

        copyfile.assert_not_called()
        parent_load.assert_called_once_with()

    def test_support_preemption_group_defaults_to_enabled_q_and_e(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task.config_type = {}
        task.config_description = {}

        with mock.patch.object(BaseNTETask, "__init__", return_value=None):
            RequiemCombatConfigTask.__init__(task)

        self.assertFalse(task.default_config[task.CONF_GROUP_SUPPORT_PREEMPTION])
        self.assertTrue(task.default_config[task.CONF_SUPPORT_SKILL_SWITCH])
        self.assertTrue(task.default_config[task.CONF_SUPPORT_SKILL_PREEMPTION])
        self.assertTrue(task.default_config[task.CONF_SUPPORT_ULTIMATE_PREEMPTION])
        self.assertEqual(
            task.config_type[task.CONF_GROUP_SUPPORT_PREEMPTION]["sub_configs"][True],
            [
                task.CONF_SUPPORT_SKILL_SWITCH,
                task.CONF_SUPPORT_SKILL_PREEMPTION,
                task.CONF_SUPPORT_ULTIMATE_PREEMPTION,
            ],
        )

    def test_coaxis_group_contains_requested_defaults(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task.config_type = {}
        task.config_description = {}

        with mock.patch.object(BaseNTETask, "__init__", return_value=None):
            RequiemCombatConfigTask.__init__(task)

        self.assertFalse(task.default_config[task.CONF_GROUP_COAXIS])
        self.assertFalse(task.default_config[task.CONF_COAXIS_COMBAT_ENABLE])
        self.assertEqual(task.default_config[task.CONF_COAXIS_TRIGGER_KEY], "8")
        self.assertEqual(task.default_config[task.CONF_COAXIS_REQUIEM_SWITCH_KEY], "1")
        self.assertEqual(task.default_config[task.CONF_COAXIS_ZANKOU_SWITCH_KEY], "2")
        self.assertEqual(task.default_config[task.CONF_COAXIS_REQUIEM_INTERVAL], 0.2)
        self.assertEqual(task.default_config[task.CONF_COAXIS_REQUIEM_DURATION], 2.0)
        self.assertEqual(task.default_config[task.CONF_COAXIS_ZANKOU_SWITCH_DELAY], 0.5)
        self.assertEqual(task.default_config[task.CONF_COAXIS_ZANKOU_HOLD_DURATION], 2.0)
        self.assertEqual(task.default_config[task.CONF_COAXIS_ZANKOU_NORMAL_DURATION], 2.0)
        self.assertEqual(task.default_config[task.CONF_FREE_BREAK_TEST_KEY], "9")
        self.assertEqual(
            task.config_type[task.CONF_GROUP_COAXIS]["sub_configs"][True],
            [
                task.CONF_COAXIS_COMBAT_ENABLE,
                task.CONF_COAXIS_TRIGGER_KEY,
                task.CONF_COAXIS_REQUIEM_SWITCH_KEY,
                task.CONF_COAXIS_ZANKOU_SWITCH_KEY,
                task.CONF_COAXIS_REQUIEM_INTERVAL,
                task.CONF_COAXIS_REQUIEM_DURATION,
                task.CONF_COAXIS_ZANKOU_SWITCH_DELAY,
                task.CONF_COAXIS_ZANKOU_HOLD_DURATION,
                task.CONF_COAXIS_ZANKOU_NORMAL_DURATION,
            ],
        )

    def test_coaxis_trigger_starts_standalone_test_only_on_press_edge(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task.config = {task.CONF_COAXIS_TRIGGER_KEY: "8"}
        task._coaxis_key_was_down = False
        task._macro_running = False
        task._run_coaxis_test = mock.MagicMock(return_value=True)
        task._is_key_pressed = mock.MagicMock(side_effect=[True, True, False])

        self.assertTrue(task._poll_coaxis_trigger())
        task._run_coaxis_test.assert_called_once_with()
        self.assertFalse(task._poll_coaxis_trigger())
        self.assertFalse(task._poll_coaxis_trigger())
        task._run_coaxis_test.assert_called_once_with()

    def test_coaxis_test_builds_lw_tester_without_combat_state(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task.config = {
            task.CONF_INPUT_MODE: task.INPUT_BG,
            task.CONF_COAXIS_TRIGGER_KEY: "8",
            task.CONF_COAXIS_REQUIEM_SWITCH_KEY: "3",
            task.CONF_COAXIS_ZANKOU_SWITCH_KEY: "1",
            task.CONF_COAXIS_REQUIEM_INTERVAL: 0.25,
            task.CONF_COAXIS_REQUIEM_DURATION: 2.5,
            task.CONF_COAXIS_ZANKOU_SWITCH_DELAY: 0.45,
            task.CONF_COAXIS_ZANKOU_HOLD_DURATION: 1.5,
            task.CONF_COAXIS_ZANKOU_NORMAL_DURATION: 0.35,
        }
        task._macro_running = False
        task._coaxis_running = False
        task._prepare_input = mock.MagicMock()
        task._mouse_up = mock.MagicMock()
        task._is_key_pressed = mock.MagicMock(return_value=False)

        with mock.patch(
            "src.tasks.trigger.RequiemCombatConfigTask.RequiemZankouAxisTester"
        ) as tester_class:
            self.assertTrue(task._run_coaxis_test())

        tester_class.return_value.run.assert_called_once_with()
        task._prepare_input.assert_called_once_with()
        task._mouse_up.assert_called_once_with()
        settings = tester_class.call_args.args[1]
        self.assertEqual(settings.trigger_key, "8")
        self.assertEqual(settings.requiem_switch_key, "3")
        self.assertEqual(settings.zankou_switch_key, "1")
        self.assertEqual(settings.requiem_attack_interval, 0.25)
        self.assertEqual(settings.requiem_attack_duration, 2.5)
        self.assertEqual(settings.zankou_switch_delay, 0.45)
        self.assertEqual(settings.zankou_hold_duration, 1.5)
        self.assertEqual(settings.zankou_normal_attack_duration, 0.35)
        self.assertFalse(task._macro_running)
        self.assertFalse(task._coaxis_running)

    def test_coaxis_switch_key_uses_background_input_when_selected(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task._bg = True
        task._itx = mock.MagicMock()

        with mock.patch("src.tasks.trigger.RequiemCombatConfigTask.time.sleep") as sleep:
            self.assertTrue(task._coaxis_send_key("3"))

        task._itx.send_key_down.assert_called_once_with("3")
        sleep.assert_called_once_with(0.02)
        task._itx.send_key_up.assert_called_once_with("3")


class TestRequiemCombatConfigTaskExchangePaths(unittest.TestCase):
    def make_task(self):
        return RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)

    def test_exchange_directory_is_created_under_data_export(self):
        task = self.make_task()
        with (
            mock.patch(
                "src.tasks.trigger.RequiemCombatConfigTask.get_relative_path",
                return_value="D:/workspace/data_export",
            ) as get_relative_path,
            mock.patch("src.tasks.trigger.RequiemCombatConfigTask.os.makedirs") as makedirs,
        ):
            self.assertEqual(task._preset_exchange_directory(), "D:/workspace/data_export")

        get_relative_path.assert_called_once_with("data_export")
        makedirs.assert_called_once_with("D:/workspace/data_export", exist_ok=True)

    def test_export_dialog_defaults_to_data_export(self):
        task = self.make_task()
        task._preset_exchange_directory = mock.Mock(return_value="D:/workspace/data_export")

        with mock.patch(
            "PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=("", "")
        ) as get_save_file_name:
            task._preset_export()

        self.assertEqual(
            get_save_file_name.call_args.args[2],
            os.path.join("D:/workspace/data_export", "安魂曲配置.json"),
        )

    def test_import_dialog_defaults_to_data_export(self):
        task = self.make_task()
        task._preset_exchange_directory = mock.Mock(return_value="D:/workspace/data_export")

        with mock.patch(
            "PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=("", "")
        ) as get_open_file_name:
            task._preset_import()

        self.assertEqual(get_open_file_name.call_args.args[2], "D:/workspace/data_export")


if __name__ == "__main__":
    unittest.main()
