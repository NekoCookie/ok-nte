from types import SimpleNamespace
import unittest
from unittest import mock

from src.combat.BaseCombatTask import BaseCombatTask


class TestCombatExtensionHooks(unittest.TestCase):
    def test_dodge_status_row_is_inserted_immediately_after_log(self):
        task = object.__new__(BaseCombatTask)
        info_calls = mock.Mock()
        task.load_hotkey = mock.Mock()
        task._get_valid_team_snapshot = mock.Mock(return_value=(0, 0))
        task._get_fixed_slots = mock.Mock(return_value=[])
        task._expand_initial_snapshot_from_portraits = mock.Mock(return_value=0)
        task.log_info = info_calls.log_info
        task.info_set = info_calls.info_set
        task._lw_sound_dodge_status = "等待触发"
        task.chars = []
        task._is_weak_single_unknown_team = mock.Mock(return_value=False)
        task._is_weak_unknown_expansion = mock.Mock(return_value=False)
        task._commit_loaded_chars = mock.Mock(return_value=True)

        self.assertTrue(task.lw_load_chars())

        self.assertEqual(
            info_calls.mock_calls[:2],
            [
                mock.call.log_info("load_chars count 0 current_index 0"),
                mock.call.info_set("闪避情况", "等待触发"),
            ],
        )

    def test_current_ru_get_cd_delegates_the_snapshot_to_the_lw_policy(self):
        task = object.__new__(BaseCombatTask)
        task.refresh_cd = mock.Mock()
        task.get_current_char = mock.Mock(return_value=SimpleNamespace(index=1))
        task.cds = {1: {"time": 10.0, "skill": 4.0}}
        task.lw_get_cd = mock.Mock(return_value=3.5)

        self.assertEqual(BaseCombatTask.get_cd(task, "skill"), 3.5)

        task.lw_get_cd.assert_called_once_with("skill", 1, task.cds[1])

    def test_lw_preparation_clears_animation_before_resource_observation(self):
        task = object.__new__(BaseCombatTask)
        task.in_animation = True
        task.info_set = mock.Mock()
        task.lw_settle_combat_start_resources = mock.Mock()
        task._combat_session = SimpleNamespace(switch_enabled=False)

        self.assertFalse(task.lw_prepare_combat_start())

        self.assertFalse(task.in_animation)
        task.info_set.assert_called_once_with("闪避情况", "等待触发")
        task.lw_settle_combat_start_resources.assert_called_once_with()

    def test_loaded_character_info_uses_the_localized_template_name(self):
        task = object.__new__(BaseCombatTask)
        task._roster_monitor = mock.Mock(return_value=mock.Mock())
        task.clear_element_reactions = mock.Mock()
        task.combat_planner = mock.Mock()
        task.info_set = mock.Mock()
        task.info_add_to_list = mock.Mock()
        task.log_info = mock.Mock()
        task.lw_char_implementation_name = mock.Mock(return_value="安魂曲主C")
        task._apply_sound_config = mock.Mock()
        task._warm_up_background_mouse = mock.Mock()
        char = mock.Mock(
            index=0,
            char_name="安魂曲",
            impl_id="builtin:requiem",
            confidence=0.99,
            element="White",
        )

        self.assertTrue(task._commit_loaded_chars([char], current_index=0))

        task.lw_char_implementation_name.assert_called_once_with(char)
        task.info_add_to_list.assert_called_once_with("chars", "安魂曲: 安魂曲主C")

    def test_lw_template_name_uses_chinese_registry_metadata(self):
        task = object.__new__(BaseCombatTask)
        task.is_chinese = mock.Mock(return_value=True)
        char = mock.Mock(impl_id="builtin:requiem")

        self.assertEqual(task.lw_char_implementation_name(char), "安魂曲主C")

    def test_lw_template_name_keeps_custom_combo_names(self):
        task = object.__new__(BaseCombatTask)
        task.is_chinese = mock.Mock(return_value=True)
        char = mock.Mock(impl_id="combo_user_defined")

        with mock.patch("src.lw.combat_ext.CustomCharManager") as manager_class:
            manager_class.return_value.get_impl_name.return_value = "我的自定义模板"

            self.assertEqual(task.lw_char_implementation_name(char), "我的自定义模板")


if __name__ == "__main__":
    unittest.main()
