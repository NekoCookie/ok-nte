"""refresh_cd 就绪判定单测(重构后的统一规则):
- 读到数字 = 在CD, 锚=数字, 记 skill_ocr_raw, 清"连续没数字"计时;
- 没数字 + 连续没数字 < 去抖窗 → 保留上次锚点(偶发坏帧不误判就绪);
- 没数字 + 连续没数字 >= 平时去抖窗 → 锚 0(就绪);
- 放招后 grace 期内没数字 → 用更长的 grace 窗顶住, 不锚 0(挡数字滞后→防空切)。

不依赖每角色就绪模板/图标高亮——所以安魂曲那种"CD白字"也不会被误判就绪。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.combat.BaseCombatTask import BaseCombatTask


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def time(self):
        return self.now

    def advance(self, dt):
        self.now += dt


class FakeText:
    def __init__(self, x, cd):
        self.x = x
        self.cd = cd


IDX = 2  # 当前角色 index


def make_task():
    t = BaseCombatTask.__new__(BaseCombatTask)
    t.cds = {}
    t.scene = mock.MagicMock()
    t.scene.cd_refreshed = False
    t.SKILL_CD_DIAG = False  # 关诊断, 免去截图/对照日志依赖
    char = mock.MagicMock()
    char.index = IDX
    t.get_current_char = mock.MagicMock(return_value=char)
    t.ocr = mock.MagicMock(return_value=[])
    # width_of_screen(0.89)=100, (0.925)=110; skill 文本 x<100, ultimate x>110
    t.width_of_screen = mock.MagicMock(side_effect=lambda r: 100 if r < 0.9 else 110)
    t._box_ready_no_number = mock.MagicMock(return_value=False)  # 大招分支, skill 不走它
    t.log_info = mock.MagicMock()
    return t


class TestRefreshCdReady(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(now=1000.0)
        self.p_time = mock.patch('src.combat.BaseCombatTask.time', self.clock)
        # note_skill_on_cd/note_skill_ready 等在 src/lw/combat_ext.py, 必须与 refresh_cd 用同一假钟
        self.p_time_ext = mock.patch('src.lw.combat_ext.time', self.clock)
        self.p_conv = mock.patch('src.combat.BaseCombatTask.convert_cd', lambda t: t.cd)
        self.p_time.start()
        self.p_time_ext.start()
        self.p_conv.start()
        self.addCleanup(self.p_time.stop)
        self.addCleanup(self.p_time_ext.stop)
        self.addCleanup(self.p_conv.stop)
        self.task = make_task()

    def feed(self, skill_cd=None, dt=0.0):
        """喂一帧: skill_cd=None 表示这帧 OCR 没读到技能数字。"""
        if dt:
            self.clock.advance(dt)
        self.task.scene.cd_refreshed = False
        self.task.ocr.return_value = [FakeText(50, skill_cd)] if skill_cd is not None else []
        self.task.refresh_cd()

    def skill_cds(self):
        return self.task.cds[IDX]

    # ---- 读到数字 → 锚=数字, 记 ocr_raw, 清 no_number_since ----
    def test_number_read_anchors(self):
        self.feed(skill_cd=12.0)
        self.assertEqual(self.skill_cds()["skill"], 12.0)
        self.assertEqual(self.skill_cds()["skill_ocr_raw"], 12.0)
        self.assertNotIn("skill_no_number_since", self.skill_cds())

    # ---- 安魂曲场景: CD中图标有白字但能读到数字 → 判CD(不被高亮骗成就绪)----
    def test_cd_number_not_mistaken_for_ready(self):
        self.feed(skill_cd=11.1)
        self.assertEqual(self.skill_cds()["skill"], 11.1)  # 进CD, 不是就绪0

    # ---- 首次见角色就没数字: 用图标兜一帧。就绪图标 → 锚0 ----
    def test_first_seen_no_number_ready_icon_anchors_zero(self):
        self.task._box_ready_no_number = mock.MagicMock(return_value=True)
        self.feed(skill_cd=None)
        self.assertEqual(self.skill_cds()["skill"], 0)

    # ---- 首次见角色就没数字, 图标非就绪 → 占位冷却(等下帧数字校准)----
    def test_first_seen_no_number_not_ready_icon_holds_cd(self):
        self.task._box_ready_no_number = mock.MagicMock(return_value=False)
        self.feed(skill_cd=None)
        self.assertEqual(self.skill_cds()["skill"], self.task.UNKNOWN_CD_SECONDS)

    # ---- 没数字但在去抖窗内(偶发坏帧)→ 保留上次锚点, 不锚0 ----
    def test_no_number_within_debounce_keeps_anchor(self):
        self.feed(skill_cd=12.0)              # 先锚12
        self.feed(skill_cd=None, dt=0.1)      # 0.1s < 0.5s 去抖 → 保留
        self.assertEqual(self.skill_cds()["skill"], 12.0)
        self.assertIsNone(self.skill_cds()["skill_ocr_raw"])

    # ---- 连续没数字超过平时去抖窗 → 判就绪锚0 ----
    def test_no_number_beyond_debounce_marks_ready(self):
        self.feed(skill_cd=12.0)
        self.feed(skill_cd=None, dt=0.1)      # 累计0.1
        self.feed(skill_cd=None, dt=0.5)      # 累计0.6 >= 0.5 → 就绪
        self.assertEqual(self.skill_cds()["skill"], 0)

    # ---- 放招后 grace 期内持续没数字(数字滞后)→ 用grace长窗顶住, 不锚0 ----
    def test_post_cast_grace_holds_off_ready(self):
        self.task.note_skill_on_cd(IDX, cd=20.0)  # 放招锚20, 设 skill_cast_at=now
        self.feed(skill_cd=None, dt=0.1)
        self.feed(skill_cd=None, dt=0.5)          # 累计0.6: 平时早该就绪, 但 grace(2s)内 → 仍保留
        self.assertEqual(self.skill_cds()["skill"], 20.0)

    # ---- 回归: 就绪很久(since 累积)后放招锚CD, 放招后没数字帧不能被陈旧 since 冲成就绪 ----
    # 复现空切根因: 支援长时间在场就绪→skill_no_number_since 累积几秒且没清→放招 note 锚20→
    # 放招后第一帧 OCR 滞后没数字→若 note 不清 since, now-since>>grace 立刻触发把20冲回0→空切。
    def test_cast_after_long_ready_keeps_cd_not_clobbered(self):
        self.task._box_ready_no_number = mock.MagicMock(return_value=True)
        self.feed(skill_cd=None)                  # 就绪, since 起算
        self.feed(skill_cd=None, dt=3.0)          # 持续就绪 3s: since 已很旧(锚仍0)
        self.assertEqual(self.skill_cds()["skill"], 0)
        self.task.note_skill_on_cd(IDX, cd=20.0)  # 放技能锚20(应同时重置 since)
        self.feed(skill_cd=None, dt=0.2)          # 放招后 OCR 滞后没数字: grace 内必须保住20
        self.assertEqual(self.skill_cds()["skill"], 20.0)

    # ---- 放招后被闪避打断: 数字滞后过后读到短CD → 校准成短CD(不是标称20)----
    def test_post_cast_reads_short_cd_calibrates(self):
        self.task.note_skill_on_cd(IDX, cd=20.0)
        self.feed(skill_cd=None, dt=0.1)          # 滞后, 保留20
        self.feed(skill_cd=3.0, dt=0.5)           # 数字出来=3s短CD → 校准
        self.assertEqual(self.skill_cds()["skill"], 3.0)
        self.assertEqual(self.skill_cds()["skill_ocr_raw"], 3.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
