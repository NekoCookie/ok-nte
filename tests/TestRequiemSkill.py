"""纯逻辑单测:验证 Requiem CombatPlan 中真技能 / 免费技能的分类与切人决策。

判定唯一依据是技能图标视觉匹配(classify_skill_visual);不再用时间锚点。
单测把视觉判定打桩成固定结果来驱动 plan entry 分支,并单独验证:
- 视觉模板真/免费可分(用提交进 assets 的模板自校验)
- 识别不到(None)时按真技能处理
- 真技能按键没落实时不切人
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.char.Requiem import Requiem
from src.combat.planner import ActionResult


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def time(self):
        return self.now

    def advance(self, dt):
        self.now += dt


def make_requiem(clock, skill_kind="real", skill_available=True,
                 click_skill_ok=True, click_ultimate=False, in_long_cd=True):
    """构造一个只保留决策逻辑、其余全部打桩的 Requiem 实例。

    skill_kind: 'real' / 'free' / None —— 视觉判定的固定返回(驱动 plan entry 分支)。
    in_long_cd: 放招后图标是否在"长CD"(_real_skill_in_long_cd 的固定返回, 即是否真放成功)。
    """
    r = Requiem.__new__(Requiem)
    r.skill_off_field_until = 0.0
    r._pending_double_4a = None
    r.index = 0
    r.task = mock.MagicMock()
    r.task.config = {}
    # engage/闪避反击等时长现从"安魂曲配置"任务(get_task_by_class)读; 默认None→走各自默认值。
    r.task.get_task_by_class = mock.MagicMock(return_value=None)
    r.logger = mock.MagicMock()
    r.wait_intro = mock.MagicMock()
    r.click_ultimate = mock.MagicMock(return_value=click_ultimate)
    r.ultimate_available = mock.MagicMock(return_value=False)
    r.skill_available = mock.MagicMock(return_value=skill_available)
    r.click_skill = mock.MagicMock(return_value=click_skill_ok)
    r.lw_click_skill_with_settlement = mock.MagicMock(return_value=click_skill_ok)
    r.should_yield_to_support = mock.MagicMock(return_value=False)
    r.continues_normal_attack = mock.MagicMock()
    r.idle_normal_attack = mock.MagicMock()
    r.normal_attack = mock.MagicMock()
    # sleep 推进假时钟, 否则真技能重试循环(按时间 deadline)在测试里永不结束。
    r.sleep = mock.MagicMock(side_effect=lambda *a, **k: clock.advance(a[0] if a else 0))
    r.free_skill_followup_attack = mock.MagicMock()
    # 免费技能后的"跳A打断a5"是独立的时序IO行为, 这里打桩掉, 只验证 plan 分支是否调它。
    r._free_skill_break_a5 = mock.MagicMock()
    r.engage_before_skill = mock.MagicMock()
    # 放完真技能后的"是否真进CD"确认:默认 False = 技能已落实(进了CD)
    r._skill_still_available_after_input_mode_delay = mock.MagicMock(return_value=False)
    # 放招后图标是否在长CD(=真放成功);区分 16s 长CD vs 被打断的 ~3s 短CD。
    r._real_skill_in_long_cd = mock.MagicMock(return_value=in_long_cd)
    # 视觉判定打桩:固定返回 skill_kind(plan entry 经 is_real_skill_now 读取)
    r.classify_skill_visual = mock.MagicMock(return_value=skill_kind)
    r._maybe_trigger_g_skill = mock.MagicMock(return_value=False)
    r._check_combat_alive = mock.MagicMock()
    return r


def run_requiem_plan(r):
    """按 planner 的 allowed-action 语义执行一次 Requiem entry flow。"""
    flow = r.combat_plan(None).entry()
    result = None
    while True:
        try:
            action = next(flow) if result is None else flow.send(result)
        except StopIteration:
            return
        if action.is_allowed(None):
            result = action.run(None)
        else:
            result = ActionResult(
                name=action.name,
                success=False,
                tags=set(action.tags),
                slot=action.slot,
                reason="action blocked by planner",
            )


class TestRequiemSkillClassification(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(now=1000.0)
        self.patcher = mock.patch('src.char.Requiem.time', self.clock)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    # ---- 视觉判真 → 起手平A + 放 + 切人 ----
    def test_real_skill_switches(self):
        r = make_requiem(self.clock, skill_kind="real")
        run_requiem_plan(r)
        r.engage_before_skill.assert_called_once_with(r.SKILL_ENGAGE_ATTACK)
        self.assertTrue(r.should_force_off_field(), "真技能后应触发下场")
        r.free_skill_followup_attack.assert_not_called()
        r._free_skill_break_a5.assert_not_called()  # 真技能分支不走免费打断

    # ---- 视觉判免费 → 留场,不切,不起手平A ----
    def test_free_skill_stays_on_field(self):
        r = make_requiem(self.clock, skill_kind="free")
        run_requiem_plan(r)
        r.engage_before_skill.assert_not_called()
        self.assertFalse(r.should_force_off_field(), "免费技能不应触发下场")
        r._free_skill_break_a5.assert_called_once()  # 免费技能后应先跳A打断a5
        r.free_skill_followup_attack.assert_called_once()

    # ---- 识别不到(None)→ 按真技能处理(切人)----
    def test_unknown_treated_as_real(self):
        r = make_requiem(self.clock, skill_kind=None)
        run_requiem_plan(r)
        r.engage_before_skill.assert_called_once_with(r.SKILL_ENGAGE_ATTACK)
        self.assertTrue(r.should_force_off_field(), "识别不到应按真技能切人")
        r.free_skill_followup_attack.assert_not_called()

    # ---- 一次放成功(进长CD)→ 直接 overlap ----
    def test_real_skill_first_try_long_cd_switches(self):
        r = make_requiem(self.clock, skill_kind="real", in_long_cd=True)
        run_requiem_plan(r)
        self.assertTrue(r.should_force_off_field(), "进长CD=放成功, 应 overlap 下场")
        r.lw_click_skill_with_settlement.assert_called_with(
            cooldown=r.REAL_SKILL_CD,
            max_duration=r.REAL_SKILL_RETRY_MAX_DURATION,
        )

    # ---- 进的是短CD(被闪避打断的假成功)→ 不切, 修掉"短CD误当放成功" ----
    def test_real_skill_short_cd_does_not_switch(self):
        r = make_requiem(self.clock, skill_kind="real", in_long_cd=False)
        run_requiem_plan(r)
        self.assertFalse(r.should_force_off_field(), "短CD=被打断, 不该 overlap")
        r.lw_click_skill_with_settlement.assert_called_with(
            cooldown=r.REAL_SKILL_CD,
            max_duration=r.REAL_SKILL_RETRY_MAX_DURATION,
        )

    # ---- 没按出去，经公共 click_skill 恢复后进长CD → overlap ----
    def test_real_skill_common_recovery_lands_long_cd_switches(self):
        r = make_requiem(self.clock, skill_kind="real", in_long_cd=True)
        # 首次确认仍可用 = 没按出去 → _try_land 返回 False，复查公共恢复后的最终 CD。
        r._skill_still_available_after_input_mode_delay = mock.MagicMock(return_value=True)
        run_requiem_plan(r)
        self.assertTrue(r.should_force_off_field(), "settle 后进长CD应 overlap 下场")

    # ---- 没按出去，公共恢复后仍没进长CD → 不切, 下轮重试 ----
    def test_real_skill_common_recovery_fails_no_switch(self):
        r = make_requiem(self.clock, skill_kind="real", in_long_cd=False)
        r._skill_still_available_after_input_mode_delay = mock.MagicMock(return_value=True)
        run_requiem_plan(r)
        self.assertFalse(r.should_force_off_field(), "settle 后仍没进长CD, 不该 overlap")

    # ---- _real_skill_in_long_cd 轮询: CD数字滞后, 几帧后刷出长CD → 提前判成功 ----
    def test_real_skill_in_long_cd_polls_until_cd_appears(self):
        r = make_requiem(self.clock)
        del r._real_skill_in_long_cd  # 用真方法(make_requiem 默认 mock 掉了)
        r.normal_attack = mock.MagicMock()
        # 放招瞬间没数字/短CD, 第三帧才刷出 15 → 立即 True
        r.task.skill_ocr_raw = mock.MagicMock(side_effect=[None, 3.0, 15.0])
        r.task.next_frame = mock.MagicMock()
        self.assertTrue(r._real_skill_in_long_cd())

    # ---- _real_skill_in_long_cd 轮询: 窗口内始终只有短CD → 超时判失败 ----
    def test_real_skill_in_long_cd_times_out_when_never_long(self):
        r = make_requiem(self.clock)
        del r._real_skill_in_long_cd
        r.normal_attack = mock.MagicMock()
        r.task.skill_ocr_raw = mock.MagicMock(return_value=3.0)  # 始终短CD(被打断)
        r.task.next_frame = mock.MagicMock()
        self.assertFalse(r._real_skill_in_long_cd())
        self.assertGreater(r.normal_attack.call_count, 1, "轮询期间应持续平A, 不站着干等")

    # ---- 没读到数字(就绪/没放出)→ 判失败, 不会被锚点/就绪图标误导 ----
    def test_real_skill_in_long_cd_no_number_is_failure(self):
        r = make_requiem(self.clock)
        del r._real_skill_in_long_cd
        r.normal_attack = mock.MagicMock()
        r.task.skill_ocr_raw = mock.MagicMock(return_value=None)  # 全程没数字
        r.task.next_frame = mock.MagicMock()
        self.assertFalse(r._real_skill_in_long_cd())

    # ---- 没技能可放(图标没亮)→ 不放技能,走 idle ----
    def test_no_skill_when_unavailable(self):
        r = make_requiem(self.clock, skill_available=False)
        run_requiem_plan(r)
        r.click_skill.assert_not_called()
        r.idle_normal_attack.assert_called_once()

    # ---- is_real_skill_now:免费=False,真/None=True(None 按真处理)----
    def test_is_real_skill_now(self):
        r = make_requiem(self.clock)
        r.classify_skill_visual = mock.MagicMock(return_value="free")
        self.assertFalse(r.is_real_skill_now())
        r.classify_skill_visual = mock.MagicMock(return_value="real")
        self.assertTrue(r.is_real_skill_now())
        r.classify_skill_visual = mock.MagicMock(return_value=None)
        self.assertTrue(r.is_real_skill_now(), "识别不到按真技能处理")

    # ---- 起手平A至少出手一次,用 normal_attack(无守卫)----
    def test_engage_before_skill_attacks_at_least_once(self):
        r = make_requiem(self.clock)
        del r.engage_before_skill  # 用真方法
        r.sleep = mock.MagicMock(side_effect=lambda *a, **k: self.clock.advance(a[0] if a else 0))
        r.engage_before_skill(0.0)
        self.assertGreaterEqual(r.normal_attack.call_count, 1)
        r.normal_attack.reset_mock()
        r.engage_before_skill(0.25)
        self.assertGreaterEqual(r.normal_attack.call_count, 2)

    # ---- 起手平A时长可被自动战斗任务配置覆盖 ----
    def test_engage_attack_reads_task_config(self):
        r = make_requiem(self.clock)
        # get_task_by_class 默认 None → 走默认 SKILL_ENGAGE_ATTACK
        self.assertEqual(r.engage_attack_duration(), r.SKILL_ENGAGE_ATTACK)
        # 从"安魂曲配置"任务读: 配置该任务的 config
        jump_task = mock.MagicMock()
        jump_task.config = {r.CONF_ENGAGE_ATTACK: 0.45}
        r.task.get_task_by_class = mock.MagicMock(return_value=jump_task)
        self.assertEqual(r.engage_attack_duration(), 0.45)
        # 配置为 0 → 不起手平A,但真技能仍正常放出+切人
        jump_task.config = {r.CONF_ENGAGE_ATTACK: 0}
        run_requiem_plan(r)
        r.engage_before_skill.assert_not_called()
        self.assertTrue(r.should_force_off_field(), "真技能仍应切下场")
        jump_task.config = {r.CONF_ENGAGE_ATTACK: "abc"}
        self.assertEqual(r.engage_attack_duration(), r.SKILL_ENGAGE_ATTACK)

    # ---- 视觉模板:真/免费图标能分开(用提交进 assets 的模板自校验)----
    def test_template_conf_separates_real_and_free(self):
        import cv2
        real = cv2.imread(Requiem.SKILL_REAL_TEMPLATE_PATH)
        free = cv2.imread(Requiem.SKILL_FREE_TEMPLATE_PATH)
        self.assertIsNotNone(real, "缺少真技能图标模板")
        self.assertIsNotNone(free, "缺少免费技能图标模板")
        self.assertGreater(Requiem._template_conf(real, real),
                           Requiem._template_conf(real, free) + 0.2)
        self.assertGreater(Requiem._template_conf(free, free),
                           Requiem._template_conf(free, real) + 0.2)
        r = make_requiem(self.clock)
        self.assertEqual(
            r._decide_skill_kind(Requiem._template_conf(real, real),
                                 Requiem._template_conf(real, free)), "real")
        self.assertEqual(
            r._decide_skill_kind(Requiem._template_conf(free, real),
                                 Requiem._template_conf(free, free)), "free")

    # ---- 判定阈值:低置信/差距小 → None(按真技能处理)----
    def test_decide_skill_kind_thresholds(self):
        r = make_requiem(self.clock)
        self.assertEqual(r._decide_skill_kind(0.9, 0.5), "real")
        self.assertEqual(r._decide_skill_kind(0.5, 0.9), "free")
        self.assertIsNone(r._decide_skill_kind(0.2, 0.1), "都低于 min_conf → None")
        self.assertIsNone(r._decide_skill_kind(0.90, 0.88), "差距 < margin → None")


if __name__ == '__main__':
    unittest.main(verbosity=2)
