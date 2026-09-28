"""[lw] 折叠分组声明与角色自定义配置分区的测试。"""

import unittest
from unittest import mock

from src.lw import nanally_super_jump as nanally
from src.lw.activity import GROUP as ACTIVITY_GROUP
from src.lw.config_group import (
    config_group,
    config_group_depth,
    config_group_keys,
    is_config_group,
)
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

    def test_depth_counts_nested_groups_only(self):
        config_type = {
            "section": config_group(["inner", "flat"]),
            "inner": config_group(["leaf", "switch"]),
            "switch": {"sub_configs": {True: ["child"]}},
            "plain": {"sub_configs": {True: ["plain_child"]}},
        }

        self.assertEqual(config_group_depth(config_type, "section"), 0)
        self.assertEqual(config_group_depth(config_type, "flat"), 1)
        self.assertEqual(config_group_depth(config_type, "leaf"), 2)
        self.assertEqual(config_group_depth(config_type, "child"), 3)
        # 框架原生的开关子项不在折叠分组里, 保持框架默认缩进
        self.assertEqual(config_group_depth(config_type, "plain_child"), 0)


class TestCharacterConfigSections(unittest.TestCase):
    def make_task(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task.config_type = {}
        task.config_description = {}
        with mock.patch.object(BaseNTETask, "__init__", return_value=None):
            RequiemCombatConfigTask.__init__(task)
        return task

    def test_top_level_is_character_sections_then_activity_and_presets(self):
        task = self.make_task()
        sub_keys = {
            child
            for the_type in task.config_type.values()
            if isinstance(the_type, dict) and isinstance(the_type.get("sub_configs"), dict)
            for children in the_type["sub_configs"].values()
            for child in children
        }
        top_level = [k for k in task.default_config if not k.startswith("_") and k not in sub_keys]

        self.assertEqual(task.name, "角色自定义配置")
        self.assertEqual(
            top_level,
            [
                task.CONF_SECTION_GENERAL, task.CONF_SECTION_REQUIEM,
                task.CONF_SECTION_ZANKOU, task.CONF_SECTION_NANALLY,
                ACTIVITY_GROUP, task.CONF_GROUP_PRESET,
            ],
        )
        self.assertTrue(all(is_config_group(task.config_type[k]) for k in top_level))

    def test_sections_hold_their_characters_settings(self):
        task = self.make_task()

        def children(key):
            return task.config_type[key]["sub_configs"][True]

        self.assertEqual(
            children(task.CONF_SECTION_GENERAL),
            [
                task.CONF_GROUP_SUPPORT_PREEMPTION, task.CONF_COAXIS_EARLY_ENTRY_ABILITY_INPUT,
                task.CONF_ORDINARY_DODGE_WAIT, task.CONF_MANUAL_KEY_TRIGGERS,
                task.CONF_DISABLE_SKILLS,
            ],
        )
        self.assertEqual(
            children(task.CONF_SECTION_REQUIEM),
            [
                task.CONF_GROUP_REQUIEM_COAXIS,
                task.CONF_GROUP_TRIGGER, task.CONF_REQUIEM_ORDINARY_DODGE_WAIT,
                task.CONF_GROUP_DODGE, task.CONF_LS_EXPAND, task.CONF_FREE_BREAK_EXPAND,
                task.CONF_GROUP_TUNING, task.CONF_GROUP_DODGE_TEST,
            ],
        )
        self.assertEqual(children(task.CONF_SECTION_ZANKOU)[0], task.CONF_COAXIS_COMBAT_ENABLE)
        self.assertEqual(children(task.CONF_SECTION_NANALLY), nanally.KEYS)
        self.assertEqual(
            children(task.CONF_GROUP_DODGE_TEST), [task.CONF_DODGE_TEST, task.CONF_DODGE_TEST_KEY]
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
        self.assertIn(nanally.HOTKEY, preset_keys)
        self.assertIn(task.CONF_COAXIS_ZANKOU_HOLD_DURATION, preset_keys)

    def test_presets_cover_every_setting_automatically(self):
        task = self.make_task()
        task.default_config["以后新增的配置"] = 1  # 新增配置不需要登记到档位清单

        excluded = config_group_keys(task.config_type) | {task.CONF_PRESET_SLOT}
        self.assertEqual(
            task._preset_keys(),
            [k for k in task.default_config if not k.startswith("_") and k not in excluded],
        )
        self.assertIn("以后新增的配置", task._preset_keys())


if __name__ == "__main__":
    unittest.main()
