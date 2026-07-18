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
from src.combat.planner import ActionTag, FieldClaimLevel
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


class TestBuffSupportPlannerMigration(unittest.TestCase):
    def test_default_switch_off_keeps_do_perform(self):
        self.assertFalse(BuffSupport.LW_USE_PLANNER_PLAN, "默认必须走 do_perform, 不改现状")
        c = make_buff(main_dps=True)
        c.LW_USE_PLANNER_PLAN = False
        self.assertTrue(c.lw_use_do_perform(), "开关关: 有主C走 do_perform")
        c.LW_USE_PLANNER_PLAN = True
        self.assertFalse(c.lw_use_do_perform(), "开关开: 有主C改走 planner combat_plan")

    def test_no_main_dps_always_planner(self):
        c = make_buff(main_dps=False)
        c.LW_USE_PLANNER_PLAN = False
        self.assertFalse(c.lw_use_do_perform(), "无主C: 无论开关都退回 planner")

    def test_describe_role_is_support(self):
        c = make_buff()
        self.assertEqual(c.describe_role().role, PlannerRole.SUPPORT)

    def test_combat_plan_ultimate_ready_scores_as_ultimate(self):
        c = make_buff(ult_ready=True, buff_pending=True)
        plan = c.combat_plan(None)
        actions = list(plan.actions)
        self.assertEqual(len(actions), 1)
        self.assertIn(ActionTag.ULTIMATE_ACTION, actions[0].tags)
        # 大招 buff 待铺 → high claim 压环合
        claims = list(plan.claims)
        self.assertTrue(claims and claims[0].level == FieldClaimLevel.HIGH)

    def test_combat_plan_skill_only_scores_as_skill(self):
        c = make_buff(ult_ready=False, skill_ready=True)
        plan = c.combat_plan(None)
        actions = list(plan.actions)
        self.assertIn(ActionTag.SKILL_ACTION, actions[0].tags)
        self.assertNotIn(ActionTag.ULTIMATE_ACTION, actions[0].tags)
        self.assertEqual(list(plan.claims), [], "无大招待铺不发 claim")

    def test_combat_plan_no_main_dps_delegates_super(self):
        c = make_buff(main_dps=False)
        with mock.patch.object(BaseChar, "combat_plan", return_value="base-default"):
            self.assertEqual(c.combat_plan(None), "base-default")

    def test_planner_perform_reuses_do_perform_core(self):
        # 执行体复用 _cast_ult_and_skill + update_resource_after_perform(手感与 do_perform 一致)
        c = make_buff()
        c._cast_ult_and_skill = mock.MagicMock(return_value=(True, False))
        c.update_resource_after_perform = mock.MagicMock()
        c.SKILL_DOWN_TIME = 0.01
        result = c._planner_perform_support(None)
        c._cast_ult_and_skill.assert_called_once()
        c.update_resource_after_perform.assert_called_once_with(True, False)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
