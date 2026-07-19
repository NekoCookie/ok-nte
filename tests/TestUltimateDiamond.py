"""下场大招"元素菱形"视觉识别及其开场稳定门控单测。

识别原理:下场角色头像右侧的元素菱形格,大招满时亮起硬描边菱形(高边缘能量),
没满时是空背景/光晕(平滑、低边缘能量),用 Laplacian 方差区分(属性无关、亮暗通吃)。
样本裁自真实截图,提交在 tests/assets/ult_diamond/,用于回归保护阈值与算法。
"""
import glob
import os
import sys
import unittest
from unittest import mock

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lw.char_ui_ext import CharUIExtMixin as CharUIMixin  # 菱形常量已随上游重构迁到 src/lw/
from src.lw.combat_templates import BuffSupport

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "ult_diamond")


def lap_var(path):
    img = cv2.imread(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F, ksize=3).var())


def make_support(off_field=None, is_current=False, cache_confirmed=False,
                 has_cd=True, skill=False, ult=False):
    s = BuffSupport.__new__(BuffSupport)
    s.index = 1
    s.is_current_char = is_current
    s.logger = mock.MagicMock()
    s.task = mock.MagicMock()
    s.task.off_field_ultimate_ready = mock.MagicMock(return_value=off_field)
    s.team_has_main_dps = mock.MagicMock(return_value=True)
    s.recently_used_resource = mock.MagicMock(return_value=False)
    s.resource_cache_confirmed = cache_confirmed
    s.has_cd_cache = mock.MagicMock(return_value=has_cd)
    s.skill_available = mock.MagicMock(return_value=skill)
    s.ultimate_available = mock.MagicMock(return_value=ult)
    return s


class TestDiamondRecognition(unittest.TestCase):
    """用提交进 repo 的样本,验证"有菱形/无菱形"能被阈值干净分开。"""

    def test_samples_separated_by_thresholds(self):
        absent = sorted(glob.glob(os.path.join(SAMPLE_DIR, "absent_*.png")))
        present = sorted(glob.glob(os.path.join(SAMPLE_DIR, "present_*.png")))
        self.assertTrue(absent, "缺少无菱形样本")
        self.assertTrue(present, "缺少有菱形样本")
        for p in absent:
            self.assertLess(
                lap_var(p), CharUIMixin.ULT_DIAMOND_LAP_ABSENT,
                f"{os.path.basename(p)} 无菱形,边缘能量却不低于 ABSENT 阈值")
        for p in present:
            self.assertGreater(
                lap_var(p), CharUIMixin.ULT_DIAMOND_LAP_PRESENT,
                f"{os.path.basename(p)} 有菱形,边缘能量却不高于 PRESENT 阈值")

    def test_thresholds_have_gap(self):
        # 不确定区间必须存在(present 阈值高于 absent 阈值),否则无 None 缓冲
        self.assertGreater(CharUIMixin.ULT_DIAMOND_LAP_PRESENT,
                           CharUIMixin.ULT_DIAMOND_LAP_ABSENT)


class TestBuffSupportUltimateWiring(unittest.TestCase):
    """普通调度统一使用 RU 大招真值，LW 菱形只参与开场稳定观察。"""

    def test_ru_off_field_ultimate_confirms_resource(self):
        s = make_support(off_field=False, cache_confirmed=False, skill=False, ult=True)
        self.assertTrue(s.has_confirmed_resource())
        s.task.off_field_ultimate_ready.assert_not_called()

    def test_geometry_does_not_override_ru_during_normal_dispatch(self):
        s = make_support(off_field=True, cache_confirmed=False, skill=False, ult=False)
        self.assertFalse(s.has_confirmed_resource())
        s.task.off_field_ultimate_ready.assert_not_called()

    # ---- 下场:菱形=无大招,技能缓存满足 → 仍按技能确认 ----
    def test_off_field_skill_cache_confirms(self):
        s = make_support(off_field=False, cache_confirmed=True, has_cd=True, skill=True)
        self.assertTrue(s.has_confirmed_resource())

    # ---- 下场:菱形=无大招,技能缓存不满足 → 不确认 ----
    def test_off_field_nothing_ready(self):
        s = make_support(off_field=False, cache_confirmed=False, skill=False)
        self.assertFalse(s.has_confirmed_resource())

    def test_skill_cache_remains_independent_of_geometry(self):
        s = make_support(off_field=None, cache_confirmed=True, has_cd=True, skill=True)
        self.assertTrue(s.has_confirmed_resource())
        s2 = make_support(off_field=None, cache_confirmed=False, skill=False)
        self.assertFalse(s2.has_confirmed_resource())

    def test_ultimate_ready_now_always_uses_ru_truth(self):
        s = make_support(off_field=True, ult=False)
        self.assertFalse(s.ultimate_ready_now())
        s.ultimate_available.assert_called_once_with()
        s.task.off_field_ultimate_ready.assert_not_called()

    # ---- has_resource:技能或大招任一就绪即有资源 ----
    def test_has_resource_skill_or_ultimate(self):
        self.assertTrue(make_support(skill=True, ult=False).has_resource())
        self.assertTrue(make_support(skill=False, ult=True).has_resource())
        self.assertFalse(make_support(skill=False, ult=False).has_resource())

    # ---- ultimate_buff_pending:只看大招,用于压过环合优先铺大招 buff ----
    def test_ultimate_buff_pending_only_ultimate(self):
        self.assertTrue(make_support(ult=True).ultimate_buff_pending())
        self.assertFalse(make_support(ult=False).ultimate_buff_pending())
        # 只看大招:技能就绪但大招没好 → 不算待铺(不打断环合)
        self.assertFalse(make_support(skill=True, ult=False).ultimate_buff_pending())

    def test_ultimate_buff_pending_recently_used(self):
        s = make_support(ult=True)
        s.recently_used_resource = mock.MagicMock(return_value=True)
        self.assertFalse(s.ultimate_buff_pending(), "刚用过大招不算待铺")

    def test_opening_observation_keeps_geometry_tristate_gate(self):
        unknown = make_support(off_field=None, ult=False, skill=False)
        self.assertIsNone(unknown.combat_start_resource_observation())
        unknown.task.off_field_ultimate_ready.assert_called_once_with(1)

        present = make_support(off_field=True, ult=False, skill=False)
        self.assertTrue(present.combat_start_resource_observation())

    def test_opening_observation_prefers_ru_truth(self):
        s = make_support(off_field=None, ult=True, skill=False)
        self.assertTrue(s.combat_start_resource_observation())
        s.task.off_field_ultimate_ready.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
