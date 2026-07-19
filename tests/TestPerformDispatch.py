"""角色 perform 单轨回归：内置角色与 LW 角色都必须进入 CombatPlanner。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.char.BaseChar import BaseChar
from src.char.Lacrimosa import Lacrimosa
from src.char.Requiem import Requiem
from src.char.Sakiri import Sakiri
from src.combat.planner import ActionSlot, ActionTag, Role
from src.lw.combat_templates import BuffSupport, MainDps, SakiriBuffSupport


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
    def test_all_character_types_use_planner(self):
        cases = (
            (BaseChar, ()),
            (Requiem, (support_template(),)),
            (MainDps, (support_template(),)),
            (BuffSupport, (main_dps_template(),)),
            (BuffSupport, ()),
        )
        for cls, teammates in cases:
            with self.subTest(cls=cls.__name__, teammate_count=len(teammates)):
                c = make_char(cls, teammates=teammates)
                c.task.refresh_cd = mock.MagicMock()
                c.perform()
                c.task.combat_planner.perform_current_char.assert_called_once_with(c)
                c.switch_next_char.assert_called_once()

    def test_requiem_perform_keeps_shared_planner_lifecycle(self):
        c = make_char(Requiem, teammates=[support_template()])
        c.task.refresh_cd = mock.MagicMock()
        c.has_intro = True
        c.add_intro_motion_freeze = mock.MagicMock()
        c.wait_intro = mock.MagicMock()
        c._try_default_arc_click = mock.MagicMock()
        with mock.patch("src.char.BaseChar.time.time", return_value=123.0):
            c.perform()
        self.assertEqual(c.last_perform, 123.0)
        c.add_intro_motion_freeze.assert_called_once_with(123.0)
        c.wait_intro.assert_called_once()
        c.task.combat_planner.perform_current_char.assert_called_once_with(c)
        c.task.refresh_cd.assert_called_once()
        c.switch_next_char.assert_called_once()


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
