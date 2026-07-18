"""perform 分发回归测试: 用户角色的 do_perform 手感路径必须从主循环可达。

背景(48ab44a 修复的合并回归): 上游 planner 化后 BaseChar.perform 改走
combat_planner.perform_current_char, 不再调 do_perform——安魂曲免费技/闪避接combo/
站场combo/"禁用技能大招"开关全部被静默绕过, 且测试全绿(当时没有测试断言这条调用链)。
本文件锁住修复后的分发语义, 上游再动 perform 结构时这里会先红:
- 模板体系成立(主C模板+辅助模板同队)时, 用户角色 → 走 lw_perform → do_perform;
- 模板体系不成立(主C没辅助配合/辅助没主C)时 → 整体退回上游 planner:
  安魂曲主C用 RU 安魂曲(Lacrimosa)的角色画像与出招计划, 早雾辅助用 RU 早雾(Sakiri);
  (旧回退 super().do_perform()/Sakiri.do_perform 已随上游 planner 化删除, 是 AttributeError)
- 未定义 do_perform 的上游内置角色 → 走 planner(perform_current_char);
- LW_DO_PERFORM=False 对照开关 → 用户角色也回落 planner。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.char.BaseChar import BaseChar
from src.char.Lacrimosa import Lacrimosa
from src.char.MainDps import BuffSupport, MainDps, SakiriBuffSupport
from src.char.Requiem import Requiem
from src.char.Sakiri import Sakiri
from src.combat.planner import Role


def make_char(cls, teammates=()):
    c = cls.__new__(cls)
    c.index = 0
    c.has_intro = False
    c.is_current_char = True
    c.planner_handles_arc = False
    c.logger = mock.MagicMock()
    c.task = mock.MagicMock()
    c.task.chars = [c, *teammates]
    # 两条路径的公共出口都在实例上 mock 掉, 只验证分发走向
    c.switch_next_char = mock.MagicMock()
    c.click_arc = mock.MagicMock()
    return c


def support_template():
    return BuffSupport.__new__(BuffSupport)


def main_dps_template():
    return MainDps.__new__(MainDps)


class TestPerformDispatch(unittest.TestCase):
    def test_requiem_in_system_perform_reaches_do_perform(self):
        c = make_char(Requiem, teammates=[support_template()])
        c.do_perform = mock.MagicMock()
        c.perform()
        c.do_perform.assert_called_once()
        c.task.combat_planner.perform_current_char.assert_not_called()
        c.switch_next_char.assert_called_once()

    def test_requiem_without_support_template_falls_back_to_planner(self):
        # 体系外(如安魂曲+娜娜莉): 走上游 planner, 不进 do_perform
        c = make_char(Requiem)
        c.do_perform = mock.MagicMock()
        c.perform()
        c.do_perform.assert_not_called()
        c.task.combat_planner.perform_current_char.assert_called_once_with(c)

    def test_main_dps_in_system_perform_reaches_do_perform(self):
        c = make_char(MainDps, teammates=[support_template()])
        c.do_perform = mock.MagicMock()
        c.perform()
        c.do_perform.assert_called_once()
        c.task.combat_planner.perform_current_char.assert_not_called()

    def test_support_with_main_dps_perform_reaches_do_perform(self):
        c = make_char(BuffSupport, teammates=[main_dps_template()])
        c.do_perform = mock.MagicMock()
        c.perform()
        c.do_perform.assert_called_once()
        c.task.combat_planner.perform_current_char.assert_not_called()

    def test_support_without_main_dps_falls_back_to_planner(self):
        # 旧回退 super().do_perform() 已断(BaseChar.do_perform 被上游删除),
        # 新机制在 perform 分发层就退回 planner, 不再经过 do_perform。
        c = make_char(BuffSupport)
        self.assertFalse(c.lw_use_do_perform())
        c.perform()
        c.task.combat_planner.perform_current_char.assert_called_once_with(c)

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
        c = make_char(Requiem, teammates=[support_template()])
        c.do_perform = mock.MagicMock()
        with mock.patch.object(Requiem, "LW_DO_PERFORM", False):
            c.perform()
        c.do_perform.assert_not_called()
        c.task.combat_planner.perform_current_char.assert_called_once_with(c)


class TestTemplateSystemFallback(unittest.TestCase):
    """体系外委托 RU 模板的具体走向。"""

    def test_requiem_out_of_system_role_is_main_dps(self):
        c = make_char(Requiem)
        self.assertEqual(c.describe_role().role, Role.MAIN_DPS)

    def test_requiem_in_system_role_is_main_dps_via_super(self):
        # 有辅助体系: describe_role 走 super()=MainDps → MAIN_DPS(安魂曲是主C, MainDps 迁移后)
        c = make_char(Requiem, teammates=[support_template()])
        self.assertEqual(c.describe_role().role, Role.MAIN_DPS)

    def test_requiem_out_of_system_plan_delegates_to_lacrimosa(self):
        c = make_char(Requiem)
        with mock.patch.object(Lacrimosa, "combat_plan", return_value="ru-plan") as m:
            self.assertEqual(c.combat_plan("ctx"), "ru-plan")
        m.assert_called_once_with(c, "ctx")

    def test_requiem_in_system_plan_uses_main_dps_super(self):
        # 有辅助体系: combat_plan 走 super()=MainDps(不调 RU Lacrimosa)。
        # 注: task#4 会让 Requiem override combat_plan 成双4a, 届时更新此断言。
        c = make_char(Requiem, teammates=[support_template()])
        with mock.patch.object(Lacrimosa, "combat_plan") as ru, mock.patch.object(
            MainDps, "combat_plan", return_value="maindps-plan"
        ):
            self.assertEqual(c.combat_plan("ctx"), "maindps-plan")
        ru.assert_not_called()

    def test_sakiri_support_without_main_dps_delegates_to_ru_sakiri(self):
        c = make_char(SakiriBuffSupport)
        with mock.patch.object(Sakiri, "combat_plan", return_value="ru-sakiri") as m:
            self.assertEqual(c.combat_plan("ctx"), "ru-sakiri")
        m.assert_called_once_with(c, "ctx")

    def test_sakiri_support_with_main_dps_delegates_to_buff_support(self):
        # 有主C体系: SakiriBuffSupport.combat_plan 走 super()=BuffSupport(planner出招),
        # 不再是 BaseChar 默认(BuffSupport 迁移后), 且不调 RU Sakiri。
        c = make_char(SakiriBuffSupport, teammates=[main_dps_template()])
        with mock.patch.object(Sakiri, "combat_plan") as ru, mock.patch.object(
            BuffSupport, "combat_plan", return_value="buff-plan"
        ):
            self.assertEqual(c.combat_plan("ctx"), "buff-plan")
        ru.assert_not_called()


if __name__ == "__main__":
    unittest.main()
