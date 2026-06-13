"""纯逻辑单测:验证 Requiem 真技能 / 免费技能的分类与切人决策。

判定唯一依据是技能图标视觉匹配(classify_skill_visual);不再用时间锚点。
单测把视觉判定打桩成固定结果来驱动 do_perform 分支,并单独验证:
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


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def time(self):
        return self.now

    def advance(self, dt):
        self.now += dt


def make_requiem(clock, skill_kind="real", skill_available=True,
                 click_skill_ok=True, click_ultimate=False):
    """构造一个只保留决策逻辑、其余全部打桩的 Requiem 实例。

    skill_kind: 'real' / 'free' / None —— 视觉判定的固定返回(驱动 do_perform 分支)。
    """
    r = Requiem.__new__(Requiem)
    r.skill_off_field_until = 0.0
    r.logger = mock.MagicMock()
    r.wait_intro = mock.MagicMock()
    r.click_ultimate = mock.MagicMock(return_value=click_ultimate)
    r.ultimate_available = mock.MagicMock(return_value=False)
    r.skill_available = mock.MagicMock(return_value=skill_available)
    r.click_skill = mock.MagicMock(return_value=(click_skill_ok, 0.0, False))
    r.should_yield_to_support = mock.MagicMock(return_value=False)
    r.continues_normal_attack = mock.MagicMock()
    r.idle_normal_attack = mock.MagicMock()
    r.normal_attack = mock.MagicMock()
    r.sleep = mock.MagicMock()
    r.free_skill_followup_attack = mock.MagicMock()
    r.engage_before_skill = mock.MagicMock()
    # 放完真技能后的"是否真进CD"确认:默认 False = 技能已落实(进了CD)
    r._skill_still_available_after_input_mode_delay = mock.MagicMock(return_value=False)
    # 视觉判定打桩:固定返回 skill_kind(do_perform 经 is_real_skill_now 读取)
    r.classify_skill_visual = mock.MagicMock(return_value=skill_kind)
    return r


class TestRequiemSkillClassification(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(now=1000.0)
        self.patcher = mock.patch('src.char.Requiem.time', self.clock)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    # ---- 视觉判真 → 起手平A + 放 + 切人 ----
    def test_real_skill_switches(self):
        r = make_requiem(self.clock, skill_kind="real")
        r.do_perform()
        r.engage_before_skill.assert_called_once_with(r.SKILL_ENGAGE_ATTACK)
        self.assertTrue(r.should_force_off_field(), "真技能后应触发下场")
        r.free_skill_followup_attack.assert_not_called()

    # ---- 视觉判免费 → 留场,不切,不起手平A ----
    def test_free_skill_stays_on_field(self):
        r = make_requiem(self.clock, skill_kind="free")
        r.do_perform()
        r.engage_before_skill.assert_not_called()
        self.assertFalse(r.should_force_off_field(), "免费技能不应触发下场")
        r.free_skill_followup_attack.assert_called_once()

    # ---- 识别不到(None)→ 按真技能处理(切人)----
    def test_unknown_treated_as_real(self):
        r = make_requiem(self.clock, skill_kind=None)
        r.do_perform()
        r.engage_before_skill.assert_called_once_with(r.SKILL_ENGAGE_ATTACK)
        self.assertTrue(r.should_force_off_field(), "识别不到应按真技能切人")
        r.free_skill_followup_attack.assert_not_called()

    # ---- 真技能按键没落实(被吞/打断)→ 不切人 ----
    def test_real_skill_not_landed_does_not_switch(self):
        r = make_requiem(self.clock, skill_kind="real")
        r._skill_still_available_after_input_mode_delay = mock.MagicMock(return_value=True)
        r.do_perform()
        self.assertFalse(r.should_force_off_field(), "按键没落实就不应切下场")

    # ---- 没技能可放(图标没亮)→ 不放技能,走 idle ----
    def test_no_skill_when_unavailable(self):
        r = make_requiem(self.clock, skill_available=False)
        r.do_perform()
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
        self.assertEqual(r.engage_attack_duration(), r.SKILL_ENGAGE_ATTACK)
        r.task = mock.MagicMock()
        r.task.config = {r.CONF_ENGAGE_ATTACK: 0.45}
        self.assertEqual(r.engage_attack_duration(), 0.45)
        # 配置为 0 → 不起手平A,但真技能仍正常放出+切人
        r.task.config = {r.CONF_ENGAGE_ATTACK: 0}
        r.do_perform()
        r.engage_before_skill.assert_not_called()
        self.assertTrue(r.should_force_off_field(), "真技能仍应切下场")
        r.task.config = {r.CONF_ENGAGE_ATTACK: "abc"}
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
