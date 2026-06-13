"""纯逻辑单测:验证 Requiem 真技能 / 免费技能的分类与切人决策。

不依赖游戏、不依赖视觉。把时钟和所有 I/O 方法打桩,只测 do_perform / real_skill_ready
的决策逻辑。重点钉死历史 bug:免费技能迟放后,16s 的真技能仍被判成真(不再落进 12~16 夹缝)。
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


def make_requiem(clock, last_real_skill_time=0.0, skill_available=True,
                 click_skill_ok=True, click_ultimate=False):
    """构造一个只保留决策逻辑、其余全部打桩的 Requiem 实例。"""
    r = Requiem.__new__(Requiem)
    r.skill_off_field_until = 0.0
    r.last_real_skill_time = last_real_skill_time
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
    # 免费技能后的留场平A打桩成空,本测只关心分类,不测接平A本身
    r.free_skill_followup_attack = mock.MagicMock()
    return r


class TestRequiemSkillClassification(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(now=1000.0)
        self.patcher = mock.patch('src.char.Requiem.time', self.clock)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    # ---- real_skill_ready 边界 ----
    def test_real_ready_boundary(self):
        r = make_requiem(self.clock, last_real_skill_time=1000.0)
        self.clock.now = 1000.0 + 15.9
        self.assertFalse(r.real_skill_ready(), "15.9s 应判免费技能")
        self.clock.now = 1000.0 + 16.0
        self.assertTrue(r.real_skill_ready(), "16.0s 应判真技能")

    # ---- 第一发技能 = 真技能 → 切人 ----
    def test_first_skill_is_real_and_switches(self):
        r = make_requiem(self.clock, last_real_skill_time=0.0)
        r.do_perform()
        self.assertEqual(r.last_real_skill_time, 1000.0, "真技能应把锚点更新到按键时刻")
        self.assertTrue(r.should_force_off_field(), "真技能后应触发下场(off-field)")
        r.free_skill_followup_attack.assert_not_called()

    # ---- CD 内图标亮 = 免费技能 → 不切、不动锚点 ----
    def test_free_skill_no_switch_no_reanchor(self):
        r = make_requiem(self.clock, last_real_skill_time=1000.0)
        r.skill_off_field_until = 1003.0  # 上次真技能留下的旧值,已过期
        self.clock.now = 1008.0           # 距真技能 8s,CD 未到
        r.do_perform()
        self.assertEqual(r.last_real_skill_time, 1000.0, "免费技能绝不能推进锚点")
        self.assertFalse(r.should_force_off_field(), "免费技能不应触发下场")
        r.free_skill_followup_attack.assert_called_once()

    # ---- 关键回归:免费技能迟放(13s),16s 真技能仍判真 → 切人 ----
    def test_late_free_skill_does_not_swallow_real_skill(self):
        r = make_requiem(self.clock, last_real_skill_time=1000.0)

        # T=1013:迟到的免费技能(老 12s 设计在这里会重开窗口埋下祸根)
        self.clock.now = 1013.0
        r.do_perform()
        self.assertEqual(r.last_real_skill_time, 1000.0,
                         "迟放的免费技能不能重置锚点(这正是老 bug 的根)")
        self.assertFalse(r.should_force_off_field(), "免费技能不切人")

        # T=1016:真技能 CD 到,必须判成真技能并切人
        self.clock.now = 1016.0
        r.free_skill_followup_attack.reset_mock()
        r.do_perform()
        self.assertEqual(r.last_real_skill_time, 1016.0,
                         "16s 的真技能必须被判成真并更新锚点")
        self.assertTrue(r.should_force_off_field(),
                        "真技能必须触发下场——12~16 夹缝 bug 不应复现")
        r.free_skill_followup_attack.assert_not_called()

    # ---- 起手平A:只在真技能"之前"触发,且必须是平A而非死 sleep ----
    def test_engage_attack_uses_attack_only_on_real_skill(self):
        # 真技能 → 应调用一次 continues_normal_attack(SKILL_ENGAGE_ATTACK),且不 sleep
        r = make_requiem(self.clock, last_real_skill_time=0.0)
        r.do_perform()
        r.continues_normal_attack.assert_any_call(r.SKILL_ENGAGE_ATTACK)
        r.sleep.assert_not_called()  # 起手必须用平A,不能死等

        # 免费技能 → 不应触发起手平A(走 followup)
        r2 = make_requiem(self.clock, last_real_skill_time=1000.0)
        self.clock.now = 1008.0
        r2.do_perform()
        self.assertNotIn(
            ((r2.SKILL_ENGAGE_ATTACK,), {}),
            [(c.args, c.kwargs) for c in r2.continues_normal_attack.call_args_list],
            "免费技能不应触发真技能的起手平A",
        )
        r2.free_skill_followup_attack.assert_called_once()

        # 没技能可放(idle) → 不应有起手平A
        r3 = make_requiem(self.clock, last_real_skill_time=1000.0, skill_available=False)
        self.clock.now = 1005.0
        r3.do_perform()
        r3.continues_normal_attack.assert_not_called()

    # ---- 起手平A时长可被自动战斗任务配置覆盖 ----
    def test_engage_attack_reads_task_config(self):
        # 没有 task → 回退到常量默认
        r = make_requiem(self.clock)
        self.assertEqual(r.engage_attack_duration(), r.SKILL_ENGAGE_ATTACK)

        # task.config 提供值 → 用配置值
        r.task = mock.MagicMock()
        r.task.config = {r.CONF_ENGAGE_ATTACK: 0.45}
        self.assertEqual(r.engage_attack_duration(), 0.45)

        # 配置为 0 → 起手平A为 0,do_perform 不调用 continues_normal_attack,但仍正常放技能切人
        r.task.config = {r.CONF_ENGAGE_ATTACK: 0}
        r.do_perform()
        r.continues_normal_attack.assert_not_called()
        self.assertEqual(r.last_real_skill_time, 1000.0, "真技能仍应正常放出")
        self.assertTrue(r.should_force_off_field(), "真技能仍应切下场")

        # 非法值 → 回退默认
        r.task.config = {r.CONF_ENGAGE_ATTACK: "abc"}
        self.assertEqual(r.engage_attack_duration(), r.SKILL_ENGAGE_ATTACK)

    # ---- 真技能未好且图标没亮 → 不放技能,走 idle ----
    def test_no_skill_when_unavailable(self):
        r = make_requiem(self.clock, last_real_skill_time=1000.0,
                         skill_available=False)
        self.clock.now = 1005.0
        r.do_perform()
        r.click_skill.assert_not_called()
        r.idle_normal_attack.assert_called_once()
        self.assertEqual(r.last_real_skill_time, 1000.0)

    # ---- 完整一轮循环:真→(CD内多次免费)→真,锚点每 16s 才推进一次 ----
    def test_full_cycle_anchor_only_advances_on_real(self):
        r = make_requiem(self.clock, last_real_skill_time=0.0)

        self.clock.now = 1000.0
        r.do_perform()                       # 真技能
        self.assertEqual(r.last_real_skill_time, 1000.0)

        for t in (1004.0, 1009.0, 1014.0):   # CD 内多次免费技能
            self.clock.now = t
            r.do_perform()
            self.assertEqual(r.last_real_skill_time, 1000.0,
                             f"t={t} 免费技能不应推进锚点")

        self.clock.now = 1017.0              # 下一次真技能
        r.do_perform()
        self.assertEqual(r.last_real_skill_time, 1017.0)
        self.assertTrue(r.should_force_off_field())


if __name__ == '__main__':
    unittest.main(verbosity=2)
