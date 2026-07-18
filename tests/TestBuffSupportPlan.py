"""BuffSupport planner 迁移(全面升级试点)结构测试。

把辅助出招从 do_perform 迁到 combat_plan(整段包进一个 planner 动作)。核心保证:
- LW_USE_PLANNER_PLAN 默认 False → 出招仍走 do_perform(现状零变化), True → 走 combat_plan;
- describe_role 声明 SUPPORT 定位;
- combat_plan 有主C时按当前资源动态给 tags(大招就绪=ULTIMATE_ACTION, 仅技能=SKILL_ACTION),
  大招 buff 待铺时发 high claim; 无主C时委托 super()(BaseChar 默认)。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.char.BaseChar import BaseChar
from src.char.MainDps import BuffSupport
from src.combat.planner import ActionSlot, ActionTag, FieldClaimLevel
from src.combat.planner import Role as PlannerRole


def make_buff(main_dps=True, ult_ready=False, skill_ready=True, buff_pending=False):
    c = BuffSupport.__new__(BuffSupport)
    c.index = 1  # FieldClaim.high(source=self) 读 self.index
    c.team_has_main_dps = lambda: main_dps
    c.ultimate_ready_now = lambda: ult_ready
    c.recently_used_resource = lambda: False
    c.has_confirmed_resource = lambda: ult_ready
    c.has_skill_resource = lambda: skill_ready
    c.ultimate_buff_pending = lambda: buff_pending
    c.skill_available = lambda: skill_ready
    c.ultimate_available = lambda: ult_ready
    return c


def actions_by_slot(plan):
    return {a.slot: a for a in plan.actions}


class TestBuffSupportPlannerMigration(unittest.TestCase):
    def test_default_switch_off_keeps_do_perform(self):
        from src.lw import planner_migration

        self.assertFalse(planner_migration.USE_PLANNER, "总开关默认 False, 不改现状")
        c = make_buff(main_dps=True)
        with mock.patch.object(planner_migration, "USE_PLANNER", False):
            self.assertTrue(c.lw_use_do_perform(), "开关关: 有主C走 do_perform")
        with mock.patch.object(planner_migration, "USE_PLANNER", True):
            self.assertFalse(c.lw_use_do_perform(), "开关开: 有主C改走 planner combat_plan")

    def test_no_main_dps_always_planner(self):
        from src.lw import planner_migration

        c = make_buff(main_dps=False)
        with mock.patch.object(planner_migration, "USE_PLANNER", False):
            self.assertFalse(c.lw_use_do_perform(), "无主C: 无论开关都退回 planner")

    def test_describe_role_is_support(self):
        c = make_buff()
        self.assertEqual(c.describe_role().role, PlannerRole.SUPPORT)

    def test_combat_plan_splits_ultimate_and_skill_actions(self):
        # ru 风格: 大招/技能各是独立声明动作(planner 能分别评分), 不是笼统一个
        c = make_buff(ult_ready=True, buff_pending=True)
        plan = c.combat_plan(None)
        by_slot = actions_by_slot(plan)
        self.assertIn(ActionSlot.ULTIMATE, by_slot)
        self.assertIn(ActionSlot.SKILL, by_slot)
        self.assertIn(ActionTag.ULTIMATE_ACTION, by_slot[ActionSlot.ULTIMATE].tags)
        self.assertIn(ActionTag.SKILL_ACTION, by_slot[ActionSlot.SKILL].tags)

    def test_combat_plan_ultimate_buff_pending_claims_high(self):
        c = make_buff(ult_ready=True, buff_pending=True)
        claims = list(c.combat_plan(None).claims)
        self.assertTrue(claims and claims[0].level == FieldClaimLevel.HIGH)

    def test_combat_plan_no_buff_pending_no_claim(self):
        c = make_buff(ult_ready=False, buff_pending=False)
        self.assertEqual(list(c.combat_plan(None).claims), [])

    def test_ultimate_priority_ready_uses_diamond(self):
        # 大招切人评分用菱形 ultimate_ready_now(下场准), 非在场 ultimate_available
        c = make_buff(ult_ready=True)
        ult = actions_by_slot(c.combat_plan(None))[ActionSlot.ULTIMATE]
        self.assertTrue(ult.priority_ready(None))
        c2 = make_buff(ult_ready=False)
        ult2 = actions_by_slot(c2.combat_plan(None))[ActionSlot.ULTIMATE]
        self.assertFalse(ult2.priority_ready(None))

    def test_combat_plan_no_main_dps_delegates_super(self):
        c = make_buff(main_dps=False)
        with mock.patch.object(BaseChar, "combat_plan", return_value="base-default"):
            self.assertEqual(c.combat_plan(None), "base-default")

    def test_skill_execute_anchors_cd_and_settles(self):
        # 技能 execute 复现 _cast_ult_and_skill 的技能分支: 放招+锚CD+结算
        c = make_buff()
        c.SKILL_DOWN_TIME = 0.01
        c.SKILL_COOLDOWN = 20.0
        c.click_skill = mock.MagicMock(return_value=True)
        c.logger = mock.MagicMock()
        c.settle_skill_after_cast = mock.MagicMock()
        c.task = mock.MagicMock()
        c.task.cds = {1: {"skill_cast_at": 123.0}}
        self.assertTrue(c._execute_support_skill(None))
        c.task.note_skill_on_cd.assert_called_once_with(1, cd=20.0)
        c.settle_skill_after_cast.assert_called_once_with(123.0, 20.0)

    def test_skill_execute_falls_back_to_about_ready(self):
        c = make_buff()
        c.SKILL_DOWN_TIME = 0.01
        c.click_skill = mock.MagicMock(return_value=False)
        c._cast_skill_if_about_ready = mock.MagicMock(return_value=True)
        self.assertTrue(c._execute_support_skill(None))
        c._cast_skill_if_about_ready.assert_called_once()


if __name__ == "__main__":
    unittest.main()
