"""AutoCombatTask.run 必须在开战时读取"使用终结技"配置。

合并回归: 上游 planner 化后给 AutoCombatTask.run 开战分支新增
`self.use_ultimate = self.config.get(self.CONF_USE_ULT, True)`, 但 LW 主循环曾漏掉这行，
导致 self.use_ultimate 恒为 __init__ 默认 True, UI 里关掉
"使用终结技"对 lw 主循环无效(BaseChar 读 self.task.use_ultimate 决定放不放大招)。
本测试通过唯一公开入口锁住: 开战按配置设置 use_ultimate。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lw.team_roster import TeamReloadRequested, TeamRosterChange
from src.tasks.trigger.AutoCombatTask import AutoCombatTask


def make_run_task(use_ult_config):
    t = AutoCombatTask.__new__(AutoCombatTask)
    t.CONF_USE_ULT = "使用终结技"
    t.config = {"使用终结技": use_ult_config}
    t.use_ultimate = True  # __init__ 默认值
    t.scene = mock.MagicMock()
    t.scene.is_in_team.return_value = True
    t.is_in_team = mock.MagicMock()
    t.in_combat = mock.MagicMock(side_effect=[True, False])  # 跑一圈即退出
    t._last_team_recheck = 0.0
    t.switch_to_combat_start_char = mock.MagicMock()
    t._reload_if_team_size_changed = mock.MagicMock(return_value=True)
    t.get_current_char = mock.MagicMock(return_value=mock.MagicMock())
    t.combat_end = mock.MagicMock()
    return t


class TestUseUltimateConfig(unittest.TestCase):
    def test_use_ultimate_disabled_by_config(self):
        t = make_run_task(False)
        t.run()
        self.assertFalse(t.use_ultimate, "开战必须按配置关掉 use_ultimate, 否则 UI 开关无效")

    def test_use_ultimate_enabled_by_config(self):
        t = make_run_task(True)
        t.run()
        self.assertTrue(t.use_ultimate)

    def test_use_ultimate_defaults_true_when_missing(self):
        t = make_run_task(True)
        t.config = {}  # 配置缺失 → 默认 True
        t.use_ultimate = False  # 即便实例被别处置 False, 开战也应回到配置默认
        t.run()
        self.assertTrue(t.use_ultimate)

    def test_confirmed_team_change_reloads_instead_of_ending_combat(self):
        t = make_run_task(True)
        change = TeamRosterChange(kind="size", expected_count=4, observed_count=2)
        t._reload_if_team_size_changed.side_effect = TeamReloadRequested(change)
        t._reload_combat_team = mock.MagicMock(return_value=True)

        t.run()

        t._reload_combat_team.assert_called_once_with()
        t.combat_end.assert_called_once_with()

    def test_action_error_still_runs_combat_cleanup(self):
        t = make_run_task(True)
        current_char = mock.MagicMock()
        current_char.perform.side_effect = RuntimeError("action failed")
        t.get_current_char.return_value = current_char

        with self.assertRaisesRegex(RuntimeError, "action failed"):
            t.run()

        t.combat_end.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
