"""check_team_changed_during_combat 回归测试: 不得再引用上游已删的旧 sleep-check 属性。

背景: 上游 72ab817 把 skip_sleep_check 布尔重构为 SleepCheckSkip + skip_sleep_checks()
上下文管理器, lw 的队伍变更检测仍写旧属性 → 进战斗第一次检测即
AttributeError('skip_sleep_check')(实机弹红色通知、自动战斗挂掉), 且 _team_change_checking
在 try 块外置 True 未复位, 之后检测被永久静默短路。本测试构造 _in_combat=True 的最小实例,
锁住: 检测正常走完不抛 AttributeError, 且 _team_change_checking 用后复位。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.combat.BaseCombatTask import BaseCombatTask, SleepCheckSkip


def make_task():
    t = BaseCombatTask.__new__(BaseCombatTask)
    t._in_combat = True
    t.chars = [mock.MagicMock(), mock.MagicMock()]
    t._team_change_checking = False
    t.in_sleep_check = False  # 实机由 ok-script 运行时维护
    t._last_team_change_check = 0.0
    t.sleep_check_skip = SleepCheckSkip()
    t.in_team = mock.MagicMock(return_value=(True, 0, 2))
    # 快照归一返回 None → 走"无效快照"早退分支, 不再依赖后续签名比对的更多状态
    t._normalize_team_snapshot = mock.MagicMock(return_value=None)
    t._pending_team_change = None
    return t


class TestTeamChangeCheck(unittest.TestCase):
    def test_no_attribute_error_and_flag_reset(self):
        t = make_task()
        result = t.check_team_changed_during_combat(force=True)
        self.assertFalse(result)
        t.in_team.assert_called_once()
        self.assertFalse(t._team_change_checking, "检测后必须复位, 否则之后恒短路")

    def test_flag_reset_even_if_in_team_raises(self):
        t = make_task()
        t.in_team = mock.MagicMock(side_effect=RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            t.check_team_changed_during_combat(force=True)
        self.assertFalse(t._team_change_checking, "异常路径也必须复位(旧代码卡True→静默失效)")

    def test_sleep_check_skip_restored(self):
        t = make_task()
        t.check_team_changed_during_combat(force=True)
        self.assertFalse(t.sleep_check_skip.all, "skip 状态必须随上下文管理器退出还原")


if __name__ == "__main__":
    unittest.main()
