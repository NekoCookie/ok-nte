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
from src.combat.planner import ActionSlot, ActionTag, Role


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

    def test_requiem_out_of_system_uses_own_double_4a(self):
        # 安魂曲停止降级 RU: 无辅助体系(如单人)也走自己的双4a(_lw_combat_plan), 不调 Lacrimosa
        c = make_char(Requiem)
        c._pending_double_4a = None
        with mock.patch.object(Lacrimosa, "combat_plan") as m:
            plan = c.combat_plan(None)
        m.assert_not_called()
        self.assertTrue(any(a.slot == ActionSlot.LEGACY_COMBO for a in plan.actions))

    def test_requiem_in_system_uses_own_double_4a(self):
        # 有辅助体系: combat_plan 走 Requiem 自己的双4a(_lw_combat_plan), 不调 RU Lacrimosa
        # 也不走 MainDps super(task#4 后)。
        c = make_char(Requiem, teammates=[support_template()])
        c._pending_double_4a = None
        with mock.patch.object(Lacrimosa, "combat_plan") as ru, mock.patch.object(
            MainDps, "combat_plan"
        ) as maindps:
            plan = c.combat_plan("ctx")
        ru.assert_not_called()
        maindps.assert_not_called()
        self.assertTrue(any(a.slot == ActionSlot.LEGACY_COMBO for a in plan.actions))

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


class TestRequiemDouble4aPlan(unittest.TestCase):
    """安魂曲双4a 迁 planner: 大招/真技能/免费技/双4a combo/续打 各独立动作, combo 整段包进
    LEGACY_COMBO 槽不拆内部时序。有辅助体系走此计划, 无辅助走 RU Lacrimosa。"""

    def _requiem(self, pending=None, real=True, skill_ready=True, ult_ready=True):
        c = make_char(Requiem, teammates=[support_template()])
        c._pending_double_4a = pending
        c.skill_available = lambda: skill_ready
        c.is_real_skill_now = lambda: real
        c.ultimate_available = lambda: ult_ready
        c.PRE_SKILL_ULTIMATE_WAIT = 0.3
        return c

    def _named(self, plan, suffix):
        return next(a for a in plan.actions if a.name.endswith(suffix))

    def test_in_system_splits_all_actions(self):
        plan = self._requiem().combat_plan(None)
        slots = {}
        for a in plan.actions:
            slots.setdefault(a.slot, 0)
            slots[a.slot] += 1
        self.assertEqual(slots[ActionSlot.ULTIMATE], 1)
        self.assertEqual(slots[ActionSlot.SKILL], 2)  # 真技能 + 免费技
        self.assertEqual(slots[ActionSlot.LEGACY_COMBO], 2)  # combo + 续打
        combo = self._named(plan, "_double_4a")
        self.assertIn(ActionTag.LEGACY_COMBO, combo.tags)

    def test_combo_continue_gated_on_pending(self):
        cont = self._named(self._requiem(pending=None).combat_plan(None), "_double_4a_continue")
        self.assertFalse(cont.can_execute(None), "无 _pending 不能续打")
        cont2 = self._named(self._requiem(pending="x").combat_plan(None), "_double_4a_continue")
        self.assertTrue(cont2.can_execute(None), "有 _pending 可续打")

    def test_real_skill_gated_on_is_real(self):
        real = self._named(self._requiem(real=True).combat_plan(None), "_real_skill")
        self.assertTrue(real.can_execute(None))
        real2 = self._named(self._requiem(real=False).combat_plan(None), "_real_skill")
        self.assertFalse(real2.can_execute(None), "免费技时真技能不可执行")

    def test_free_skill_gated_on_not_real(self):
        free = self._named(self._requiem(real=False).combat_plan(None), "_free_skill")
        self.assertTrue(free.can_execute(None))
        free2 = self._named(self._requiem(real=True).combat_plan(None), "_free_skill")
        self.assertFalse(free2.can_execute(None), "真技能时免费技不可执行")

    def test_out_of_system_uses_own_double_4a(self):
        # 安魂曲停止降级 RU: 无辅助体系也走自己的双4a, 不调 Lacrimosa
        c = make_char(Requiem)  # 无 teammates
        c._pending_double_4a = None
        with mock.patch.object(Lacrimosa, "combat_plan") as m:
            plan = c.combat_plan(None)
        m.assert_not_called()
        self.assertTrue(any(a.slot == ActionSlot.LEGACY_COMBO for a in plan.actions))

    def test_free_skill_execute_breaks_a5_and_followups(self):
        c = self._requiem(real=False)
        c.click_skill = mock.MagicMock(return_value=True)
        c._free_skill_break_a5 = mock.MagicMock()
        c.free_skill_followup_attack = mock.MagicMock()
        self.assertTrue(c._execute_free_skill(None))
        c._free_skill_break_a5.assert_called_once()
        c.free_skill_followup_attack.assert_called_once()


if __name__ == "__main__":
    unittest.main()
