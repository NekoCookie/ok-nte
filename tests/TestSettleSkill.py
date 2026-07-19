"""settle_skill_after_cast 单测:放招后被闪避时的"校准CD / 补放"结算。

进CD与否只认 skill_ocr_raw(这帧OCR真读到的原始数字), 不读 get_cd/就绪图标(会被刚note的
标称CD污染)。覆盖:
- 放招后没闪避 → 不介入(但仍先 flush pending 闪避再判);
- 非当前角色 → 直接不介入;
- OCR读到有意义CD → 校准, 返回 True;
- OCR没数字/读到偏小值 → 补发技能, 放出去(读到大CD)后返回 True;
- 超时仍没数字 → 锚成就绪(note_skill_ready), 返回 False;
- settle 介入前先 flush_pending_dodge(修"放招→闪避pending→切人"漏检)。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.char.BaseChar import BaseChar
from src.lw.skill_cast_settle import SkillCastSettleMixin


class _SettleChar(SkillCastSettleMixin):
    pass


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def time(self):
        return self.now

    def advance(self, dt):
        self.now += dt


def make_char(clock, is_current=True, dodge_after_cast=True, ocr_raw=None, ocr_raw_seq=None):
    c = _SettleChar.__new__(_SettleChar)
    c.index = 0
    c.is_current_char = is_current
    c.logger = mock.MagicMock()
    c.task = mock.MagicMock()
    # cast_at 固定 1000;闪避在放招后 = 1000.05,放招前 = 999.9
    c.task.last_dodge_time = mock.MagicMock(return_value=1000.05 if dodge_after_cast else 999.9)
    c.task.flush_pending_dodge = mock.MagicMock()
    # skill_ocr_raw: 这帧OCR真读到的原始CD(None=没数字=就绪/没放出)
    if ocr_raw_seq is not None:
        c.task.skill_ocr_raw = mock.MagicMock(side_effect=ocr_raw_seq)
    else:
        c.task.skill_ocr_raw = mock.MagicMock(return_value=ocr_raw)
    c.task.next_frame = mock.MagicMock()
    c.task.note_skill_on_cd = mock.MagicMock()
    c.task.note_skill_ready = mock.MagicMock()
    c.send_skill_key = mock.MagicMock()
    c.normal_attack = mock.MagicMock()
    c.sleep = mock.MagicMock(side_effect=lambda *a, **k: clock.advance(a[0] if a else 0))
    return c


class TestSettleSkillAfterCast(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(now=1000.0)
        self.patcher = mock.patch("src.lw.skill_cast_settle.time", self.clock)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    # ---- 放招后没闪避 → 不介入(但先 flush 过 pending 闪避才下的结论)----
    def test_no_dodge_does_not_intervene(self):
        c = make_char(self.clock, dodge_after_cast=False)
        self.assertFalse(c.settle_skill_after_cast(1000.0, 20.0))
        c.task.flush_pending_dodge.assert_called_once()  # 判定前先落地 pending 闪避
        c.task.next_frame.assert_not_called()
        c.send_skill_key.assert_not_called()

    # ---- 非当前角色 → 直接不介入, 连 flush/判定都不做 ----
    def test_not_current_char(self):
        c = make_char(self.clock, is_current=False)
        self.assertFalse(c.settle_skill_after_cast(1000.0, 20.0))
        c.task.flush_pending_dodge.assert_not_called()
        c.task.last_dodge_time.assert_not_called()

    # ---- settle 介入前必先 flush_pending_dodge(修哈尼娅"放招→闪避→切人"漏检)----
    def test_flushes_pending_dodge_before_judging(self):
        c = make_char(self.clock, dodge_after_cast=True, ocr_raw=16.0)
        c.settle_skill_after_cast(1000.0, 20.0)
        c.task.flush_pending_dodge.assert_called_once()

    # ---- A: OCR读到有意义CD(短CD3s也算)→ 校准, 不补发, 返回 True ----
    def test_already_on_cd_calibrates(self):
        c = make_char(self.clock, ocr_raw=3.0)  # 进了短CD(被打断), OCR照样读到 → 校准
        self.assertTrue(c.settle_skill_after_cast(1000.0, 20.0))
        c.send_skill_key.assert_not_called()
        c.task.note_skill_ready.assert_not_called()

    # ---- B: 没读到数字(没按出去)→ 补发, 放出去后读到大CD → 返回 True ----
    def test_ready_recasts_then_lands(self):
        # 第一圈无数字→补发; 第二圈读到 16→校准结束
        c = make_char(self.clock, ocr_raw_seq=[None, 16.0])
        self.assertTrue(c.settle_skill_after_cast(1000.0, 20.0))
        c.send_skill_key.assert_called_once()
        c.task.note_skill_on_cd.assert_called_once()  # 补发后暂锚标称CD

    # ---- OCR读到偏小值(<MIN_ON_CD, 读数未稳)→ 当没放成继续补放, 等真CD出来再校准 ----
    def test_small_cd_keeps_recasting(self):
        c = make_char(self.clock, ocr_raw_seq=[0.5, 16.0])  # 0.5<1 不算进CD → 补发; 16 → True
        self.assertTrue(c.settle_skill_after_cast(1000.0, 16.0))
        c.send_skill_key.assert_called_once()
        c.task.note_skill_ready.assert_not_called()

    # ---- 超时仍没数字(一直没放出)→ 锚成就绪, 返回 False ----
    def test_timeout_still_ready_marks_ready(self):
        c = make_char(self.clock, ocr_raw=None)  # 始终没数字
        self.assertFalse(c.settle_skill_after_cast(1000.0, 20.0))
        c.task.note_skill_ready.assert_called_once_with(0)
        self.assertGreater(c.send_skill_key.call_count, 1, "超时前应反复补发")

    # ---- max_duration 可加长(安魂曲真技能用 3s)----
    def test_custom_max_duration_runs_longer(self):
        c = make_char(self.clock, ocr_raw=None)
        c.settle_skill_after_cast(1000.0, 16.0, max_duration=3.0)
        # 3s / 0.1 间隔 ≈ 30 圈, 远多于默认 0.5s 的 5 圈
        self.assertGreater(c.send_skill_key.call_count, 20)

    def test_zero_max_duration_does_not_fall_back_to_default(self):
        c = make_char(self.clock, ocr_raw=None)

        self.assertFalse(c.settle_skill_after_cast(1000.0, 16.0, max_duration=0))

        c.task.next_frame.assert_not_called()
        c.send_skill_key.assert_not_called()
        c.task.note_skill_ready.assert_called_once_with(0)


class TestUltimateUnfreezeSettle(unittest.TestCase):
    def test_fill_click_does_not_run_full_combat_check_during_ultimate(self):
        c = BaseChar.__new__(BaseChar)
        c.check_combat = mock.MagicMock()
        c.click_with_interval = mock.MagicMock()

        c._click_during_ultimate_unfreeze()

        c.click_with_interval.assert_called_once_with()
        c.check_combat.assert_not_called()


class TestIdleAttackGuard(unittest.TestCase):
    def make_char(self):
        c = BaseChar.__new__(BaseChar)
        c.task = mock.MagicMock()
        c.task.get_current_char.return_value = c
        c.task.in_animation = False
        c.task.is_in_team.return_value = True
        c.task.click = mock.MagicMock(return_value=None)
        c.sleep = mock.MagicMock()
        return c

    def test_fill_idle_attack_reports_success_independent_of_click_return(self):
        c = self.make_char()

        self.assertTrue(c.fill_idle_attack(interval=0.2))

        c.task.click.assert_called_once_with(
            action_name="BaseChar_idle_fill_attack", interval=0.2
        )

    def test_continuous_attack_stops_when_shared_guard_rejects(self):
        c = self.make_char()
        c.fill_idle_attack = mock.MagicMock(return_value=False)

        with mock.patch("src.char.BaseChar.time.time", return_value=0.0):
            c.continues_normal_attack(1.0)

        c.fill_idle_attack.assert_called_once_with(interval=0.1)
        c.sleep.assert_not_called()


class TestAvailableActionCombatCheck(unittest.TestCase):
    def make_char(self, statuses):
        c = BaseChar.__new__(BaseChar)
        c.logger = mock.MagicMock()
        c.task = mock.MagicMock()
        c.check_combat = mock.MagicMock()
        c._check_available_action_result = mock.MagicMock(side_effect=statuses)
        return c

    def test_animation_action_does_not_check_combat_while_starting(self):
        c = self.make_char(["continue", "animation"])
        available = mock.MagicMock(return_value=True)
        send_action = mock.MagicMock(return_value=True)

        result = c._try_available_action(
            "ultimate",
            available,
            send_action,
            send_click=False,
            has_animation=True,
        )

        self.assertEqual(result["status"], "animation")
        send_action.assert_called_once_with()
        c.task.next_frame.assert_called_once_with()
        c.check_combat.assert_not_called()

    def test_non_animation_action_keeps_combat_check(self):
        c = self.make_char(["continue", "released"])
        available = mock.MagicMock(return_value=True)

        result = c._try_available_action(
            "skill",
            available,
            mock.MagicMock(return_value=True),
            send_click=False,
            has_animation=False,
        )

        self.assertEqual(result["status"], "released")
        c.check_combat.assert_called_once_with()


class TestSkillInputRetryCombatCheck(unittest.TestCase):
    def make_char(self):
        c = BaseChar.__new__(BaseChar)
        c.SKILL_INPUT_MODE_RETRY_DELAY = 0.12
        c.task = mock.MagicMock()
        c.task.in_animation = False
        c.task.is_in_team.return_value = True
        c.sleep = mock.MagicMock()
        c.check_combat = mock.MagicMock()
        c._current_char_still_self = mock.MagicMock(return_value=True)
        c.skill_available = mock.MagicMock(return_value=True)
        return c

    def test_animation_skill_retry_probe_skips_full_combat_check(self):
        c = self.make_char()

        self.assertTrue(
            c._skill_still_available_after_input_mode_delay(has_animation=True)
        )

        c.check_combat.assert_not_called()

    def test_non_animation_skill_retry_probe_keeps_combat_check(self):
        c = self.make_char()

        self.assertTrue(
            c._skill_still_available_after_input_mode_delay(has_animation=False)
        )

        c.check_combat.assert_called_once_with()


if __name__ == "__main__":
    unittest.main(verbosity=2)
