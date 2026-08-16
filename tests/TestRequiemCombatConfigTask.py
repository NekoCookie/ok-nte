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
