"""switch_next_char 分发回归: 主切人决策必须走 lw_decide_switch_to, 不被 planner 旁路。

背景(合并回归): 上游 planner 化删除 _find_switch_target, 把主切换方法 switch_next_char
改成直连 combat_planner.decide_switch。用户的 lw_decide_switch_to(legacy Priority 选人/
跳过不可用角色/辅助大招压环合/诊断日志)因此只在 _switch_to_char 的 retry_intro 重规划
(0.12s 窗口)生效, 主决策被 planner 接管——与 perform 被绕过同源的架构断裂。
本文件锁住修复: LW_SWITCH_NEXT 分发让主切换走 lw_switch_next_char → lw_decide_switch_to。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.combat.BaseCombatTask import BaseCombatTask


class TestSwitchNextDispatch(unittest.TestCase):
    def test_dispatch_to_lw_when_enabled(self):
        # LW_SWITCH_NEXT=True(默认): switch_next_char 走 lw 版, 不碰 planner.decide_switch
        t = BaseCombatTask.__new__(BaseCombatTask)
        t.combat_planner = mock.MagicMock()
        t.lw_switch_next_char = mock.MagicMock()
        t.switch_next_char(mock.MagicMock())
        t.lw_switch_next_char.assert_called_once()
        t.combat_planner.decide_switch.assert_not_called()

    def test_dispatch_to_planner_when_disabled(self):
        # 对照开关关闭 → 回落上游 planner 原版
        t = BaseCombatTask.__new__(BaseCombatTask)
        t.chars = [mock.MagicMock(), mock.MagicMock()]  # team_size=2
        t.lw_switch_next_char = mock.MagicMock()
        decision = mock.MagicMock()
        decision.target = None  # 保持当前角色, 早退
        t.combat_planner = mock.MagicMock()
        t.combat_planner.decide_switch.return_value = decision
        t.run_with_interval = mock.MagicMock()
        current = mock.MagicMock()
        with mock.patch.object(BaseCombatTask, "LW_SWITCH_NEXT", False):
            t.switch_next_char(current)
        t.lw_switch_next_char.assert_not_called()
        t.combat_planner.decide_switch.assert_called_once()

    def test_lw_switch_uses_lw_decide_and_switch_to_char(self):
        # lw 版内部: 走 lw_decide_switch_to 选目标 + _switch_to_char 执行, 不碰 planner.decide_switch
        t = BaseCombatTask.__new__(BaseCombatTask)
        t.chars = [mock.MagicMock(), mock.MagicMock()]
        t.combat_planner = mock.MagicMock()
        t.combat_planner.has_strict_route.return_value = False
        target = mock.MagicMock()
        t.lw_decide_switch_to = mock.MagicMock(return_value=(target, True))
        t._wait_switch_in_guard = mock.MagicMock()
        t._switch_to_char = mock.MagicMock()
        current = mock.MagicMock()
        t.lw_switch_next_char(current)
        t.lw_decide_switch_to.assert_called_once()
        t.combat_planner.decide_switch.assert_not_called()
        # 切换守卫 + 切换CD(非 strict route)
        t._wait_switch_in_guard.assert_called_once()
        current.wait_switch_cd.assert_called_once()
        # _switch_to_char 收到 lw 选的目标
        t._switch_to_char.assert_called_once()
        self.assertIs(t._switch_to_char.call_args.args[0], target)

    def test_lw_switch_keeps_current_when_no_better_target(self):
        # lw 决策选回当前角色 → 不切, 平A保持
        t = BaseCombatTask.__new__(BaseCombatTask)
        t.chars = [mock.MagicMock(), mock.MagicMock()]
        t.combat_planner = mock.MagicMock()
        t._switch_to_char = mock.MagicMock()
        t.run_with_interval = mock.MagicMock()
        current = mock.MagicMock()
        t.lw_decide_switch_to = mock.MagicMock(return_value=(current, False))
        t.lw_switch_next_char(current)
        t._switch_to_char.assert_not_called()
        current.click_with_interval.assert_called_once()

    def test_lw_switch_single_char_team_just_clicks(self):
        # 单人队 → 只点一下(与上游一致)
        t = BaseCombatTask.__new__(BaseCombatTask)
        t.chars = [mock.MagicMock()]  # team_size=1
        t.click = mock.MagicMock()
        t.lw_decide_switch_to = mock.MagicMock()
        t.lw_switch_next_char(mock.MagicMock())
        t.click.assert_called_once()
        t.lw_decide_switch_to.assert_not_called()


if __name__ == "__main__":
    unittest.main()
