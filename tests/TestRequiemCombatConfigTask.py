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
        task.config = {}
        return task

    def test_load_config_copies_legacy_config_once(self):
        task = self.make_task()
        with (
            mock.patch.object(BaseNTETask, "load_config") as parent_load,
            mock.patch("src.lw.nanally_super_jump.legacy_values", return_value={}),
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
            mock.patch("src.lw.nanally_super_jump.legacy_values", return_value={}),
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

    def test_ordinary_dodge_waits_follow_zankou_perfect_recovery(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task.config_type = {}
        task.config_description = {}

        with mock.patch.object(BaseNTETask, "__init__", return_value=None):
            RequiemCombatConfigTask.__init__(task)

        self.assertEqual(task.default_config[task.CONF_ORDINARY_DODGE_WAIT], 0.5)
        self.assertEqual(task.default_config[task.CONF_REQUIEM_ORDINARY_DODGE_WAIT], 0.5)
        self.assertNotIn(
            task.CONF_ORDINARY_DODGE_WAIT,
            task.config_type[task.CONF_GROUP_DODGE]["sub_configs"][True],
        )
        self.assertNotIn(
            task.CONF_REQUIEM_ORDINARY_DODGE_WAIT,
            task.config_type[task.CONF_GROUP_DODGE]["sub_configs"][True],
        )
        self.assertIn(
            task.CONF_ORDINARY_DODGE_WAIT,
            task.config_type[task.CONF_SECTION_GENERAL]["sub_configs"][True],
        )
        self.assertIn(
            task.CONF_REQUIEM_ORDINARY_DODGE_WAIT,
            task.config_type[task.CONF_SECTION_REQUIEM]["sub_configs"][True],
        )
        self.assertIn(
            "首次按Shift",
            task.config_description[task.CONF_ORDINARY_DODGE_WAIT],
        )
        self.assertIn("除安魂曲主C外", task.config_description[task.CONF_ORDINARY_DODGE_WAIT])
        self.assertIn(
            "仅安魂曲主C使用",
            task.config_description[task.CONF_REQUIEM_ORDINARY_DODGE_WAIT],
        )
        self.assertIn(
            "仅残虹完美闪避使用",
            task.config_description[task.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION],
        )

    def test_coaxis_group_contains_requested_defaults(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task.config_type = {}
        task.config_description = {}

        with mock.patch.object(BaseNTETask, "__init__", return_value=None):
            RequiemCombatConfigTask.__init__(task)

        self.assertFalse(task.default_config[task.CONF_SECTION_ZANKOU])
        self.assertFalse(task.default_config[task.CONF_COAXIS_COMBAT_ENABLE])
        self.assertFalse(task.default_config[task.CONF_COAXIS_EARLY_ENTRY_ABILITY_INPUT])
        self.assertIn(
            "关=保持RU的切人和环合普攻逻辑",
            task.config_description[task.CONF_COAXIS_EARLY_ENTRY_ABILITY_INPUT],
        )
        self.assertIn(
            "不会把E后Q角色强制改成Q后E",
            task.config_description[task.CONF_COAXIS_EARLY_ENTRY_ABILITY_INPUT],
        )
        self.assertEqual(task.default_config[task.CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT], "关闭")
        self.assertEqual(
            task.config_type[task.CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT]["options"],
            ["关闭", "1", "2", "3", "4"],
        )
        self.assertFalse(task.default_config[task.CONF_DISABLE_SKILLS])
        self.assertIn("不放E/Q", task.config_description[task.CONF_DISABLE_SKILLS])
        self.assertIn("G和合轴不受影响", task.config_description[task.CONF_DISABLE_SKILLS])
        self.assertFalse(task.default_config[task.CONF_MANUAL_KEY_TRIGGERS])
        self.assertIn(
            task.CONF_MANUAL_KEY_TRIGGERS,
            task.config_type[task.CONF_SECTION_GENERAL]["sub_configs"][True],
        )
        self.assertEqual(task.default_config[task.CONF_COAXIS_TRIGGER_KEY], "8")
        self.assertEqual(task.default_config[task.CONF_COAXIS_REQUIEM_SWITCH_KEY], "1")
        self.assertEqual(task.default_config[task.CONF_COAXIS_ZANKOU_SWITCH_KEY], "2")
        self.assertEqual(task.default_config[task.CONF_COAXIS_REQUIEM_DURATION], 2.0)
        self.assertEqual(task.default_config[task.CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION], 2.0)
        self.assertEqual(task.default_config[task.CONF_COAXIS_ZANKOU_SWITCH_DELAY], 0.5)
        self.assertEqual(task.default_config[task.CONF_COAXIS_ZANKOU_INTRO_WAIT_DURATION], 1.5)
        self.assertFalse(task.default_config[task.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT])
        self.assertFalse(task.default_config[task.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL])
        self.assertTrue(task.default_config[task.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL_NON_BOSS])
        self.assertEqual(
            task.config_type[task.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL]["sub_configs"][True],
            [task.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL_NON_BOSS],
        )
        self.assertEqual(task.default_config[task.CONF_COAXIS_ZANKOU_HOLD_DURATION], 2.0)
        self.assertEqual(task.default_config[task.CONF_COAXIS_ZANKOU_NORMAL_DURATION], 2.0)
        self.assertEqual(task.default_config[task.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION], 0.5)
        self.assertEqual(task.default_config[task.CONF_ORDINARY_DODGE_WAIT], 0.5)
        self.assertEqual(task.default_config[task.CONF_REQUIEM_ORDINARY_DODGE_WAIT], 0.5)
        self.assertEqual(task.default_config[task.CONF_FREE_BREAK_TEST_KEY], "9")
        self.assertEqual(
            task.config_type[task.CONF_SECTION_ZANKOU]["sub_configs"][True],
            [
                task.CONF_COAXIS_COMBAT_ENABLE,
                task.CONF_GROUP_ZANKOU_ATTACK,
                task.CONF_GROUP_ZANKOU_GOLD_SKILL,
                task.CONF_GROUP_COAXIS_KEY_TEST,
            ],
        )
        self.assertEqual(
            task.config_type[task.CONF_GROUP_REQUIEM_COAXIS]["sub_configs"][True],
            [
                task.CONF_COAXIS_REQUIEM_DURATION,
                task.CONF_COAXIS_REQUIEM_FREE_SKILL_ATTACK_DURATION,
                task.CONF_COAXIS_REQUIEM_REAL_SKILL_SWITCH_SLOT,
            ],
        )
        self.assertEqual(
            task.config_type[task.CONF_GROUP_ZANKOU_ATTACK]["sub_configs"][True],
            [
                task.CONF_COAXIS_ZANKOU_INTRO_WAIT_DURATION,
                task.CONF_COAXIS_ZANKOU_HOLD_DURATION,
                task.CONF_COAXIS_ZANKOU_NORMAL_DURATION,
                task.CONF_COAXIS_ZANKOU_DODGE_NORMAL_DURATION,
            ],
        )
        self.assertEqual(
            task.config_type[task.CONF_GROUP_ZANKOU_GOLD_SKILL]["sub_configs"][True],
            [
                task.CONF_COAXIS_ZANKOU_GOLD_SKILL_INTERRUPT,
                task.CONF_COAXIS_OPENING_ZANKOU_GOLD_SKILL,
            ],
        )
        self.assertEqual(
            task.config_type[task.CONF_GROUP_COAXIS_KEY_TEST]["sub_configs"][True],
            [
                task.CONF_COAXIS_TRIGGER_KEY,
                task.CONF_COAXIS_REQUIEM_SWITCH_KEY,
                task.CONF_COAXIS_ZANKOU_SWITCH_KEY,
                task.CONF_COAXIS_ZANKOU_SWITCH_DELAY,
            ],
        )

    def test_activity_is_polled_before_manual_master_gate(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task._enabled = True
        task.config = {task.CONF_MANUAL_KEY_TRIGGERS: False}
        task._activity = mock.MagicMock()
        task._activity.poll.return_value = True
        task._poll_manual_key_triggers = mock.MagicMock()

        self.assertTrue(task._loop())
        task._activity.poll.assert_called_once_with()
        task._poll_manual_key_triggers.assert_not_called()

    def test_super_jump_is_polled_before_manual_master_gate(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task._enabled = True
        task.config = {task.CONF_MANUAL_KEY_TRIGGERS: False}
        task._activity = mock.MagicMock()
        task._activity.poll.return_value = False
        task._nanally = mock.MagicMock()
        task._nanally.poll.return_value = True
        task._poll_manual_key_triggers = mock.MagicMock()

        self.assertTrue(task._loop())
        task._nanally.poll.assert_called_once_with()
        task._poll_manual_key_triggers.assert_not_called()

    def test_active_activity_runs_on_executor_and_keeps_trigger_priority(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task._submitted = False
        task._activity = mock.MagicMock()
        task._activity.running = True
        task.submit_periodic_task = mock.MagicMock()
        self.assertTrue(task.run())
        self.assertTrue(task.run())
        self.assertEqual(task._activity.process.call_count, 2)
        task.submit_periodic_task.assert_called_once_with(task.CHECK_INTERVAL, task._loop)
        task._activity.running = False
        self.assertIsNone(task.run())

    def test_disabled_manual_key_switch_does_not_poll_any_manual_trigger(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task.config = {task.CONF_MANUAL_KEY_TRIGGERS: False}
        task._activity = mock.MagicMock()
        task._manual_key_triggers_armed = True
        task._poll_coaxis_trigger = mock.MagicMock()
        task._poll_dodge_test_trigger = mock.MagicMock()
        task._poll_free_skill_combo_test_trigger = mock.MagicMock()
        task._poll_macro_trigger = mock.MagicMock()

        self.assertFalse(task._poll_manual_key_triggers())

        for poller in (
            task._poll_coaxis_trigger,
            task._poll_dodge_test_trigger,
            task._poll_free_skill_combo_test_trigger,
            task._poll_macro_trigger,
        ):
            poller.assert_not_called()
        self.assertFalse(task._manual_key_triggers_armed)
        task._activity.stop.assert_not_called()
        task._activity.poll.assert_not_called()

    def test_enabled_manual_key_switch_polls_all_manual_trigger_handlers(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
        task.config = {task.CONF_MANUAL_KEY_TRIGGERS: True}
        task._activity = mock.MagicMock()
        task._activity.poll.return_value = False
        task._manual_key_triggers_armed = True
        task._poll_coaxis_trigger = mock.MagicMock(return_value=False)
        task._poll_dodge_test_trigger = mock.MagicMock(return_value=False)
        task._poll_free_skill_combo_test_trigger = mock.MagicMock(return_value=False)
        task._poll_macro_trigger = mock.MagicMock(return_value=False)

        self.assertFalse(task._poll_manual_key_triggers())

        for poller in (
            task._poll_coaxis_trigger,
            task._poll_dodge_test_trigger,
            task._poll_free_skill_combo_test_trigger,
            task._poll_macro_trigger,
        ):
            poller.assert_called_once_with()

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
            task.CONF_COAXIS_TRIGGER_KEY: "8",
            task.CONF_COAXIS_REQUIEM_SWITCH_KEY: "3",
            task.CONF_COAXIS_ZANKOU_SWITCH_KEY: "1",
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
        self.assertEqual(settings.requiem_attack_duration, 2.5)
        self.assertEqual(settings.zankou_switch_delay, 0.45)
        self.assertEqual(settings.zankou_hold_duration, 1.5)
        self.assertEqual(settings.zankou_normal_attack_duration, 0.35)
        self.assertFalse(task._macro_running)
        self.assertFalse(task._coaxis_running)

    def test_coaxis_switch_key_uses_framework_input(self):
        task = RequiemCombatConfigTask.__new__(RequiemCombatConfigTask)
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
            os.path.join("D:/workspace/data_export", "角色自定义配置.json"),
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
