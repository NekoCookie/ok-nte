"""[lw] 折叠分组声明与安魂曲配置档位的测试。"""

import unittest
from unittest import mock

from src.lw.activity import GROUP as ACTIVITY_GROUP
from src.lw.config_group import config_group, config_group_keys, is_config_group
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.trigger.RequiemCombatConfigTask import RequiemCombatConfigTask


class TestConfigGroup(unittest.TestCase):
    def test_group_shows_children_only_when_expanded(self):
        the_type = config_group(["a", "b"])

        self.assertTrue(is_config_group(the_type))
        self.assertEqual(the_type["sub_configs"], {True: ["a", "b"]})
        self.assertNotIn("type", the_type)  # 非 Qt 界面回退成框架的布尔开关

    def test_only_marked_entries_are_groups(self):
        config_type = {
            "group": config_group(["a"]),
            "switch": {"sub_configs": {True: ["b"]}},
            "drop": {"type": "drop_down", "options": ["x"]},
        }

        self.assertEqual(config_group_keys(config_type), {"group"})
        self.assertEqual(config_group_keys(None), set())


class TestRequiemConfigGroups(unittest.TestCase):
    def make_task(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task.config_type = {}
        task.config_description = {}
        with mock.patch.object(BaseNTETask, "__init__", return_value=None):
            RequiemCombatConfigTask.__init__(task)
        return task

    def test_requiem_groups_use_folded_header(self):
        task = self.make_task()

        self.assertEqual(
            config_group_keys(task.config_type),
            {
                task.CONF_LS_EXPAND, task.CONF_FREE_BREAK_EXPAND, task.CONF_GROUP_TRIGGER,
                task.CONF_GROUP_SUPPORT_PREEMPTION, task.CONF_GROUP_COAXIS,
                task.CONF_GROUP_DODGE, task.CONF_GROUP_TUNING, task.CONF_GROUP_TEST,
                task.CONF_GROUP_PRESET, ACTIVITY_GROUP,
            },
        )
        # 功能开关带子项时仍是普通开关, 不能被当成折叠分组
        self.assertFalse(is_config_group(task.config_type[task.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL]))

    def test_preset_controls_share_one_group(self):
        task = self.make_task()

        self.assertEqual(
            task.config_type[task.CONF_GROUP_PRESET]["sub_configs"][True],
            [task.CONF_PRESET_SLOT, task.CONF_PRESET_OPS, task.CONF_PRESET_FILE],
        )

    def test_presets_skip_group_expand_state(self):
        task = self.make_task()
        preset_keys = task._preset_keys()

        self.assertTrue(config_group_keys(task.config_type).isdisjoint(preset_keys))
        self.assertIn(task.CONF_TRIGGER_KEY, preset_keys)


if __name__ == "__main__":
    unittest.main()
