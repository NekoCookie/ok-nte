"""perform 分发回归测试: 用户角色的 do_perform 手感路径必须从主循环可达。

背景(48ab44a 修复的合并回归): 上游 planner 化后 BaseChar.perform 改走
combat_planner.perform_current_char, 不再调 do_perform——安魂曲免费技/闪避接combo/
站场combo/"禁用技能大招"开关全部被静默绕过, 且测试全绿(当时没有测试断言这条调用链)。
本文件锁住修复后的分发语义, 上游再动 perform 结构时这里会先红:
- 定义了 do_perform 的用户角色(Requiem/MainDps系) → 走 lw_perform → do_perform;
- 未定义 do_perform 的上游内置角色 → 走 planner(perform_current_char);
- LW_DO_PERFORM=False 对照开关 → 用户角色也回落 planner。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.char.BaseChar import BaseChar
from src.char.MainDps import MainDps
from src.char.Requiem import Requiem


def make_char(cls):
    c = cls.__new__(cls)
    c.index = 0
    c.has_intro = False
    c.is_current_char = True
    c.planner_handles_arc = False
    c.logger = mock.MagicMock()
    c.task = mock.MagicMock()
    # 两条路径的公共出口都在实例上 mock 掉, 只验证分发走向
    c.switch_next_char = mock.MagicMock()
    c.click_arc = mock.MagicMock()
    return c


class TestPerformDispatch(unittest.TestCase):
    def test_requiem_perform_reaches_do_perform(self):
        c = make_char(Requiem)
        c.do_perform = mock.MagicMock()
        c.perform()
        c.do_perform.assert_called_once()
        c.task.combat_planner.perform_current_char.assert_not_called()
        c.switch_next_char.assert_called_once()

    def test_main_dps_perform_reaches_do_perform(self):
        c = make_char(MainDps)
        c.do_perform = mock.MagicMock()
        c.perform()
        c.do_perform.assert_called_once()
        c.task.combat_planner.perform_current_char.assert_not_called()

    def test_builtin_char_without_do_perform_uses_planner(self):
        self.assertFalse(
            hasattr(BaseChar, "do_perform"),
            "上游 BaseChar 重新出现 do_perform 默认实现的话, hasattr 分发会把所有角色"
            "都拉进 lw_perform, 需要改用更精确的分发条件",
        )
        c = make_char(BaseChar)
        c.perform()
        c.task.combat_planner.perform_current_char.assert_called_once_with(c)
        c.switch_next_char.assert_called_once()

    def test_lw_do_perform_off_falls_back_to_planner(self):
        c = make_char(Requiem)
        c.do_perform = mock.MagicMock()
        with mock.patch.object(Requiem, "LW_DO_PERFORM", False):
            c.perform()
        c.do_perform.assert_not_called()
        c.task.combat_planner.perform_current_char.assert_called_once_with(c)


if __name__ == "__main__":
    unittest.main()
