"""LW 主C/辅助模板的 CombatPlan 结构与执行回归测试。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.char.BaseChar import BaseChar
from src.combat.planner import (
    ActionIntent,
    ActionSlot,
    ActionTag,
    CombatPlan,
    CombatPlanner,
    FieldClaimLevel,
    FieldClaimTiming,
    FieldPreference,
    RoleProfile,
)
from src.combat.planner import Role as PlannerRole
from src.lw.combat_templates import (
    BuffSupport,
    HealSupport,
    MainDps,
    ResourceSupport,
    SakiriBuffSupport,
)


def make_buff(main_dps=True, ult_ready=False, skill_ready=True, buff_pending=False):
    c = BuffSupport.__new__(BuffSupport)
    c.index = 1  # FieldClaim.high(source=self) 读 self.index
    c.team_has_main_dps = lambda: main_dps
    c.ultimate_ready_now = lambda: ult_ready
    c.recently_used_resource = lambda: False
    c.has_confirmed_resource = lambda: ult_ready
    c.has_skill_resource = lambda: skill_ready
    c.ultimate_buff_pending = lambda: buff_pending
    c.needs_resource_probe = lambda: False
    c.skill_available = lambda: skill_ready
    c.ultimate_available = lambda: ult_ready
    return c


def actions_by_slot(plan):
    return {a.slot: a for a in plan.actions}


class PlannerStubChar:
    def __init__(self, index, role, preference, actions=(), max_field_time=1.5):
        self.index = index
        self.name = f"stub-{index}"
        self.is_dead = False
        self.last_switch_time = 0.0
        self.last_perform = 0.0
        self._profile = RoleProfile(
            role=role,
            field_preference=preference,
            max_field_time=max_field_time,
        )
        self._actions = list(actions)

    def __str__(self):
        return self.name

    def describe_role(self):
        return self._profile

    def combat_plan(self, _context):
        return CombatPlan(self._actions)

    def is_cycle_full(self):
        return False

    def time_elapsed_accounting_for_freeze(self, _start):
        return 100.0


def make_planner_buff(index, task, skill_ready=False, needs_probe=False):
    c = BuffSupport.__new__(BuffSupport)
    c.index = index
    c.task = task
    c.is_dead = False
    c.last_switch_time = 0.0
    c.last_perform = 0.0
    c.ultimate_ready_now = lambda: False
    c.recently_used_resource = lambda: False
    c.has_skill_resource = lambda: skill_ready
    c.ultimate_buff_pending = lambda: False
    c.needs_resource_probe = lambda: needs_probe
    c.skill_available = lambda: skill_ready
    c.ultimate_available = lambda: False
    return c


def make_planner_heal(index, task, skill_ready=False):
    c = HealSupport.__new__(HealSupport)
    c.index = index
    c.task = task
    c.is_dead = False
    c.last_switch_time = 0.0
    c.last_perform = 0.0
    c.ultimate_ready_now = lambda: False
    c.recently_used_resource = lambda: False
    c.has_skill_resource = lambda: skill_ready
    c.needs_resource_probe = lambda: False
    c.skill_available = lambda: skill_ready
    c.ultimate_available = lambda: False
    return c


class TestBuffSupportPlannerMigration(unittest.TestCase):
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
        self.assertIs(claims[0].timing, FieldClaimTiming.PREEMPTIVE)

    def test_combat_plan_without_ready_resource_has_no_claim(self):
        c = make_buff(ult_ready=False, skill_ready=False, buff_pending=False)
        self.assertEqual(list(c.combat_plan(None).claims), [])

    def test_skill_resource_claims_high(self):
        c = make_buff(ult_ready=False, skill_ready=True, buff_pending=False)
        claims = list(c.combat_plan(None).claims)
        self.assertTrue(claims and claims[0].level == FieldClaimLevel.HIGH)
        self.assertIs(claims[0].timing, FieldClaimTiming.PREEMPTIVE)

    def test_due_resource_probe_claims_high_and_enables_skill(self):
        c = make_buff(ult_ready=False, skill_ready=False, buff_pending=False)
        c.needs_resource_probe = lambda: True
        plan = c.combat_plan(None)
        self.assertEqual(list(plan.claims)[0].level, FieldClaimLevel.HIGH)
        self.assertIs(list(plan.claims)[0].timing, FieldClaimTiming.NORMAL)
        self.assertTrue(actions_by_slot(plan)[ActionSlot.SKILL].priority_ready(None))

    def test_combat_start_resource_observation_preserves_unknown_diamond(self):
        c = make_buff(ult_ready=False, skill_ready=False, buff_pending=False)
        c.is_current_char = False
        c.task = mock.MagicMock()
        c.task.off_field_ultimate_ready.return_value = None

        self.assertIsNone(c.combat_start_resource_observation())

    def test_combat_start_resource_observation_accepts_confirmed_skill(self):
        c = make_buff(ult_ready=False, skill_ready=True, buff_pending=False)
        c.is_current_char = False
        c.task = mock.MagicMock()

        self.assertTrue(c.combat_start_resource_observation())
        c.task.off_field_ultimate_ready.assert_not_called()

    def test_ultimate_priority_ready_uses_diamond(self):
        # 大招切人评分统一走 RU ultimate_ready_now。
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

    def test_skill_execute_anchors_cd_after_common_click_flow(self):
        # 闪避打断恢复已由 BaseChar.click_skill 统一处理；资源模板只负责精确锚 CD。
        c = make_buff()
        c.SKILL_DOWN_TIME = 0.01
        c.SKILL_COOLDOWN = 20.0
        c.click_skill = mock.MagicMock(return_value=True)
        c.logger = mock.MagicMock()
        c.task = mock.MagicMock()
        self.assertTrue(c._execute_support_skill(None))
        c.task.note_skill_on_cd.assert_called_once_with(1, cd=20.0)

    def test_skill_execute_falls_back_to_about_ready(self):
        c = make_buff()
        c.SKILL_DOWN_TIME = 0.01
        c.click_skill = mock.MagicMock(return_value=False)
        c._cast_skill_if_about_ready = mock.MagicMock(return_value=True)
        self.assertTrue(c._execute_support_skill(None))
        c._cast_skill_if_about_ready.assert_called_once()


class TestBuffSupportMixedTeamScoring(unittest.TestCase):
    def _task(self):
        task = mock.MagicMock()
        task.find_element_reaction_target.return_value = None
        task.time_elapsed_accounting_for_freeze.return_value = 10.0
        return task

    def _decision(self, support, *others):
        task = support.task
        current = PlannerStubChar(
            0,
            PlannerRole.SUB_DPS,
            FieldPreference.SUB_DPS,
            max_field_time=0,
        )
        task.chars = [current, support, *others]
        planner = CombatPlanner(task)
        planner.reset(task.chars)
        return planner.decide_switch(current)

    def test_formal_ru_main_dps_role_activates_lw_support_plan(self):
        task = self._task()
        support = make_planner_buff(1, task, skill_ready=True)
        ru_main = PlannerStubChar(2, PlannerRole.MAIN_DPS, FieldPreference.MAIN_DPS)
        task.chars = [support, ru_main]
        self.assertTrue(support.team_has_main_dps())

    def test_ready_support_skill_beats_ru_main_dps_field_time(self):
        task = self._task()
        support = make_planner_buff(1, task, skill_ready=True)
        ru_main = PlannerStubChar(2, PlannerRole.MAIN_DPS, FieldPreference.MAIN_DPS)
        decision = self._decision(support, ru_main)
        self.assertIs(decision.target, support)
        self.assertEqual(decision.priority, 999600)

    def test_due_probe_beats_ru_main_dps_field_time(self):
        task = self._task()
        support = make_planner_buff(1, task, needs_probe=True)
        ru_main = PlannerStubChar(2, PlannerRole.MAIN_DPS, FieldPreference.MAIN_DPS)
        decision = self._decision(support, ru_main)
        self.assertIs(decision.target, support)
        self.assertEqual(decision.priority, 500)

    def test_lw_support_probe_beats_ru_ready_ultimate(self):
        task = self._task()
        support = make_planner_buff(1, task, needs_probe=True)
        ultimate = ActionIntent(
            name="ru_ultimate",
            tags={ActionTag.ULTIMATE_ACTION},
            slot=ActionSlot.ULTIMATE,
            execute=lambda _context: True,
        )
        ru_main_dps = PlannerStubChar(
            2,
            PlannerRole.MAIN_DPS,
            FieldPreference.MAIN_DPS,
            actions=[ultimate],
        )
        decision = self._decision(support, ru_main_dps)
        self.assertIs(decision.target, support)
        self.assertEqual(decision.priority, 500)

    def test_confirmed_support_resource_preempts_ru_element_reaction(self):
        task = self._task()
        support = make_planner_buff(1, task, skill_ready=True)
        reaction = PlannerStubChar(2, PlannerRole.MAIN_DPS, FieldPreference.MAIN_DPS)
        current = PlannerStubChar(
            0,
            PlannerRole.SUB_DPS,
            FieldPreference.SUB_DPS,
            max_field_time=0,
        )
        current.is_cycle_full = lambda: True
        task.chars = [current, support, reaction]
        task.find_element_reaction_target.return_value = reaction
        planner = CombatPlanner(task)
        planner.reset(task.chars)

        decision = planner.decide_switch(current)

        self.assertIs(decision.target, support)
        self.assertIn("preemptive field claim", decision.reason)

    def test_unknown_support_probe_does_not_preempt_ru_element_reaction(self):
        task = self._task()
        support = make_planner_buff(1, task, needs_probe=True)
        reaction = PlannerStubChar(2, PlannerRole.MAIN_DPS, FieldPreference.MAIN_DPS)
        current = PlannerStubChar(
            0,
            PlannerRole.SUB_DPS,
            FieldPreference.SUB_DPS,
            max_field_time=0,
        )
        current.is_cycle_full = lambda: True
        task.chars = [current, support, reaction]
        task.find_element_reaction_target.return_value = reaction
        planner = CombatPlanner(task)
        planner.reset(task.chars)

        decision = planner.decide_switch(current)

        self.assertIs(decision.target, reaction)
        self.assertEqual(decision.reason, "element reaction")

    def test_heal_resource_only_beats_idle_main_dps_as_fallback(self):
        task = self._task()
        heal = make_planner_heal(1, task, skill_ready=True)
        ru_main = PlannerStubChar(2, PlannerRole.MAIN_DPS, FieldPreference.MAIN_DPS)
        decision = self._decision(heal, ru_main)
        self.assertIs(decision.target, heal)
        self.assertEqual(decision.priority, 200)

    def test_two_supports_then_main_resources_then_heal(self):
        task = self._task()
        support_states = [{"ready": True}, {"ready": True}]
        supports = []
        for index, state in enumerate(support_states, start=1):
            support = make_planner_buff(index, task)
            support.has_confirmed_resource = lambda state=state: state["ready"]
            support.has_skill_resource = lambda state=state: state["ready"]
            support.skill_available = lambda state=state: state["ready"]
            support.last_perform = float(index - 1)
            supports.append(support)

        main_state = {"ultimate": True, "skill": True}
        main_ultimate = ActionIntent(
            name="main_ultimate",
            tags={ActionTag.ULTIMATE_ACTION},
            slot=ActionSlot.ULTIMATE,
            execute=lambda _context: True,
            can_execute=lambda _context: main_state["ultimate"],
            priority_ready=lambda _context: main_state["ultimate"],
        )
        main_skill = ActionIntent(
            name="main_skill",
            tags={ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=lambda _context: True,
            can_execute=lambda _context: main_state["skill"],
            priority_ready=lambda _context: main_state["skill"],
        )
        main = PlannerStubChar(
            3,
            PlannerRole.MAIN_DPS,
            FieldPreference.MAIN_DPS,
            actions=[main_ultimate, main_skill],
        )
        main.skill_available = lambda: main_state["skill"]
        main.ultimate_available = lambda: main_state["ultimate"]

        heal_state = {"ready": True}
        heal = make_planner_heal(4, task)
        heal.has_skill_resource = (
            lambda: heal_state["ready"] and not heal._higher_priority_busy()
        )
        heal.skill_available = lambda: heal_state["ready"]

        current = PlannerStubChar(
            0,
            PlannerRole.SUB_DPS,
            FieldPreference.SUB_DPS,
            max_field_time=0,
        )
        task.chars = [current, *supports, main, heal]
        planner = CombatPlanner(task)
        planner.reset(task.chars)

        first = planner.decide_switch(current)
        self.assertIs(first.target, supports[0])
        support_states[0]["ready"] = False

        second = planner.decide_switch(supports[0])
        self.assertIs(second.target, supports[1])
        support_states[1]["ready"] = False

        third = planner.decide_switch(supports[1])
        self.assertIs(third.target, main)
        main_state.update(ultimate=False, skill=False)

        fourth = planner.decide_switch(main)
        self.assertIs(fourth.target, heal)


class TestResourceSupportHierarchy(unittest.TestCase):
    def test_buff_and_heal_are_sibling_resource_templates(self):
        self.assertTrue(issubclass(BuffSupport, ResourceSupport))
        self.assertTrue(issubclass(HealSupport, ResourceSupport))
        self.assertFalse(issubclass(HealSupport, BuffSupport))


class TestHealSupportResourcePlan(unittest.TestCase):
    """治疗与 BuffSupport 平级，共用 ResourceSupport 的 planner 计划骨架。"""

    def _heal(self, higher_busy, ult_ready=True, skill_ready=True):
        c = HealSupport.__new__(HealSupport)
        c.index = 2
        c.team_has_main_dps = lambda: True
        c._higher_priority_busy = lambda: higher_busy
        c.recently_used_resource = lambda: False
        c.ultimate_ready_now = lambda: ult_ready
        c.skill_available = lambda: skill_ready
        c.ultimate_available = lambda: ult_ready
        # ResourceSupport 公共资源判定（治疗 override 加了 _higher_priority_busy 门）
        c.has_cd_cache = lambda: True
        c.is_current_char = False
        c.resource_cache_confirmed = False
        c.last_resource_probe = 0.0
        c.needs_resource_probe = lambda: False

        def off_field_ult(idx):
            return ult_ready

        c.task = mock.MagicMock()
        c.task.off_field_ultimate_ready = off_field_ult
        return c

    def test_describe_role_has_no_idle_field_time(self):
        c = self._heal(higher_busy=False)
        role = c.describe_role()
        self.assertEqual(role.role, PlannerRole.SUPPORT)
        self.assertEqual(role.field_preference, FieldPreference.SUPPORT)
        self.assertEqual(role.max_field_time, 0, "治疗无资源时不参与普通驻场")

    def test_priority_ready_false_when_higher_priority_busy(self):
        # 主C/别的辅助有资源时, 治疗的技能 action priority_ready=False(不抢切人)
        c = self._heal(higher_busy=True)
        skill = actions_by_slot(c.combat_plan(None))[ActionSlot.SKILL]
        self.assertFalse(skill.priority_ready(None), "有更高优先级时治疗不吸引切人")

    def test_skill_resource_claims_low(self):
        c = self._heal(higher_busy=False, ult_ready=False, skill_ready=True)
        claims = list(c.combat_plan(None).claims)
        self.assertEqual(claims[0].level, FieldClaimLevel.LOW)

    def test_ultimate_does_not_publish_buff_claim(self):
        # 治疗大招靠自身动作参与评分，不发布 BuffSupport 专属的高强度铺 buff claim。
        c = self._heal(higher_busy=False, ult_ready=True, skill_ready=False)
        self.assertEqual(list(c.combat_plan(None).claims), [])


class TestSakiriSupportInheritsBuffPlan(unittest.TestCase):
    def test_with_main_dps_uses_buff_plan_with_long_press(self):
        # 有主C: super()=BuffSupport ru 风格; 技能 execute 用 SakiriBuffSupport 的长按 SKILL_DOWN_TIME
        c = SakiriBuffSupport.__new__(SakiriBuffSupport)
        c.index = 1
        c.team_has_main_dps = lambda: True
        c.ultimate_ready_now = lambda: True
        c.recently_used_resource = lambda: False
        c.has_skill_resource = lambda: True
        c.ultimate_buff_pending = lambda: False
        c.needs_resource_probe = lambda: False
        c.skill_available = lambda: True
        c.ultimate_available = lambda: True
        plan = c.combat_plan(None)
        by_slot = actions_by_slot(plan)
        self.assertIn(ActionSlot.SKILL, by_slot)
        self.assertIn(ActionSlot.ULTIMATE, by_slot)
        # 长按常量: 早雾 0.25s(vs 普通辅助 0.01)
        self.assertEqual(SakiriBuffSupport.SKILL_DOWN_TIME, 0.25)

    def test_without_main_dps_delegates_ru_sakiri(self):
        from src.char.Sakiri import Sakiri

        c = SakiriBuffSupport.__new__(SakiriBuffSupport)
        c.team_has_main_dps = lambda: False
        with mock.patch.object(Sakiri, "combat_plan", return_value="ru-sakiri") as m:
            self.assertEqual(c.combat_plan("ctx"), "ru-sakiri")
        m.assert_called_once_with(c, "ctx")


class TestMainDpsPlannerMigration(unittest.TestCase):
    """主C模板迁 planner: 大招/技能独立 action + idle 平A 用 LEGACY_COMBO 槽, entry 编排。"""

    def _main(self, ult=True, skill=True):
        c = MainDps.__new__(MainDps)
        c.ultimate_available = lambda: ult
        c.skill_available = lambda: skill
        c.idle_normal_attack = lambda: None
        return c

    def test_describe_role_main_dps(self):
        role = self._main().describe_role()
        self.assertEqual(role.role, PlannerRole.MAIN_DPS)
        self.assertEqual(role.field_preference, FieldPreference.MAIN_DPS)

    def test_combat_plan_ultimate_skill_idle_actions(self):
        by_slot = actions_by_slot(self._main().combat_plan(None))
        self.assertIn(ActionSlot.ULTIMATE, by_slot)
        self.assertIn(ActionSlot.SKILL, by_slot)
        self.assertIn(ActionSlot.LEGACY_COMBO, by_slot)
        self.assertIn(ActionTag.LEGACY_COMBO, by_slot[ActionSlot.LEGACY_COMBO].tags)

    def test_idle_combo_not_priority_ready(self):
        # idle 不主动抢切人(靠 field_time 站场), priority_ready=False
        idle = actions_by_slot(self._main().combat_plan(None))[ActionSlot.LEGACY_COMBO]
        self.assertFalse(idle.priority_ready(None))

if __name__ == "__main__":
    unittest.main()
