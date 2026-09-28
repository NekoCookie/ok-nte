"""[lw] 娜娜莉超级跳合并进角色自定义配置后的测试。"""

import json
import os
import tempfile
import unittest
from unittest import mock

from src.lw import nanally_super_jump as nanally
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask


class TestNanallySuperJump(unittest.TestCase):
    def make_task(self, **config):
        task = mock.MagicMock()
        task.config = {nanally.ENABLE: True, nanally.HOTKEY: "mouse4",
                       nanally.MODE_SWITCH_DELAY: 0, **config}
        task.is_foreground.return_value = True
        task._is_key_pressed.return_value = False
        return task

    def test_second_jump_disabled_by_zero_delay(self):
        steps = nanally.macro_steps({nanally.JUMP_DELAY: 0.3, nanally.SECOND_JUMP_DELAY: 0})

        self.assertEqual(steps[-2:], [("sleep", 0.3), ("key", "space", nanally.JUMP_KEY_DOWN_TIME)])
        self.assertEqual(sum(step[0] == "key" for step in steps), 1)

    def test_runs_once_per_press_while_focused(self):
        task = self.make_task()
        jump = nanally.NanallySuperJump(task)
        jump.run_macro = mock.MagicMock()

        task._is_key_pressed.return_value = True
        self.assertTrue(jump.poll())
        self.assertFalse(jump.poll())  # 按住不重复触发
        task._is_key_pressed.return_value = False
        self.assertFalse(jump.poll())
        task._is_key_pressed.return_value = True
        self.assertTrue(jump.poll())
        self.assertEqual(jump.run_macro.call_count, 2)

    def test_disabled_or_unfocused_never_runs(self):
        for config, focused in (({nanally.ENABLE: False}, True), ({}, False)):
            task = self.make_task(**config)
            task.is_foreground.return_value = focused
            task._is_key_pressed.return_value = True
            jump = nanally.NanallySuperJump(task)
            jump.run_macro = mock.MagicMock()

            self.assertFalse(jump.poll())
            jump.run_macro.assert_not_called()

    def test_legacy_values_map_old_task_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "NanallySuperJumpTask.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"_enabled": True, "触发按键": "mouse5", "起跳延迟(s)": 0.5}, f)

            self.assertEqual(
                nanally.legacy_values(path),
                {nanally.ENABLE: True, nanally.HOTKEY: "mouse5", nanally.JUMP_DELAY: 0.5},
            )
            self.assertEqual(nanally.legacy_values(os.path.join(folder, "missing.json")), {})


class TestNanallyConfigMigration(unittest.TestCase):
    def load(self, folder):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task.logger = mock.MagicMock()
        task.config = {}
        with (
            mock.patch("src.tasks.trigger.RequiemCombatConfigTask.Config.config_folder", folder),
            mock.patch(
                "src.tasks.trigger.RequiemCombatConfigTask.get_relative_path",
                side_effect=os.path.join,
            ),
            mock.patch.object(BaseNTETask, "load_config"),
        ):
            task.load_config()
        return task.config

    def write(self, folder, name, data):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_first_load_copies_old_super_jump_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            self.write(folder, "RequiemCombatConfigTask.json", {"触发按键": "mouse5"})
            self.write(folder, "NanallySuperJumpTask.json", {"_enabled": True, "触发按键": "x1"})

            config = self.load(folder)

        self.assertEqual(config, {nanally.ENABLE: True, nanally.HOTKEY: "x1"})

    def test_already_merged_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            self.write(folder, "RequiemCombatConfigTask.json", {nanally.ENABLE: False})
            self.write(folder, "NanallySuperJumpTask.json", {"_enabled": True})

            config = self.load(folder)

        self.assertEqual(config, {})


if __name__ == "__main__":
    unittest.main()
