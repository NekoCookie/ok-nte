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


if __name__ == "__main__":
    unittest.main()
