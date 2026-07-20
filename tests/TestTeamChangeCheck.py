"""check_team_changed_during_combat 回归测试: 不得再引用上游已删的旧 sleep-check 属性。

背景: 上游 72ab817 把 skip_sleep_check 布尔重构为 SleepCheckSkip + skip_sleep_checks()
上下文管理器, lw 的队伍变更检测仍写旧属性 → 进战斗第一次检测即
AttributeError('skip_sleep_check')(实机弹红色通知、自动战斗挂掉), 且 _team_change_checking
在 try 块外置 True 未复位, 之后检测被永久静默短路。本测试构造 _in_combat=True 的最小实例,
锁住: 检测正常走完不抛 AttributeError, 且 _team_change_checking 用后复位。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.combat.BaseCombatTask import BaseCombatTask, SleepCheckSkip
from src.lw.team_roster import TeamReloadRequested, TeamRosterMonitor


def make_task():
    t = BaseCombatTask.__new__(BaseCombatTask)
    t._in_combat = True
    t.chars = [mock.MagicMock(), mock.MagicMock()]
    t._team_change_checking = False
    t.in_sleep_check = False  # 实机由 ok-script 运行时维护
    t._last_team_change_check = 0.0
    t._team_reload_enabled = True  # 模拟处于 lw_combat_run 的 team_reload_watch 作用域内
    t.sleep_check_skip = SleepCheckSkip()
    t.in_team = mock.MagicMock(return_value=(True, 0, 2))
    # 快照归一返回 None → 走"无效快照"早退分支, 不再依赖后续签名比对的更多状态
    t._normalize_team_snapshot = mock.MagicMock(return_value=None)
    return t


class _SignatureTask(BaseCombatTask):
    frame = mock.MagicMock()  # 覆盖基类的 frame property, 便于免初始化构造


def make_signature_task():
    t = _SignatureTask.__new__(_SignatureTask)
    t._last_team_signature_check = 0.0
    char = mock.MagicMock()
    char.char_name = "安魂曲"
    char.index = 0
    t.chars = [char]
    box = mock.MagicMock()
    box.scale.return_value.crop_frame.return_value = mock.MagicMock(size=100)
    t.get_char_box = mock.MagicMock(return_value=box)
    return t


class TestTeamSignatureCheck(unittest.TestCase):
    """上游schema v5后 match_feature 的 target_char/返回值语义从 char_name 变为 char_id。
    签名未变、静态扫描抓不到; 传名字会过滤掉全部候选→置信度恒0.00→每秒误判队伍变更、
    清掉 combo 挂起状态(实机表现: 双4a只出窗口内一半)。锁住: 必须用 char_id 调用与比对。"""

    def test_match_feature_called_and_compared_with_char_id(self):
        t = make_signature_task()
        with mock.patch("src.lw.combat_ext.CustomCharManager") as mgr_cls:
            mgr = mgr_cls.return_value
            mgr._find_character_id_by_name.return_value = "char_123"
            mgr.get_character_info_by_id.return_value = {"feature_ids": ["f1"]}
            # 新版语义: 匹配成功时返回 char_id
            mgr.match_feature.return_value = (True, "char_123", 0.92)
            result = t.check_team_signature_changed_during_combat()

        self.assertFalse(result, "同角色匹配成功不得判为队伍变更")
        kwargs = mgr.match_feature.call_args.kwargs
        self.assertEqual(
            kwargs["target_char"], "char_123",
            "target_char 必须传 char_id(传 char_name 会过滤掉全部候选、置信度恒0)",
        )
        self.assertIsNone(t._roster_monitor()._signature_candidate)


def make_reload_task():
    """_reload_if_team_size_changed 用的最小实例(主循环每轮减员检测路径)。"""
    t = BaseCombatTask.__new__(BaseCombatTask)
    t.chars = [mock.MagicMock(), mock.MagicMock()]  # team_size = len(chars) = 2
    t._last_team_recheck = 0.0
    t.lw_dump_char_slot_scores = mock.MagicMock(return_value=[0.6, 0.0, 0.0, 0.0])
    t.is_reliable_team_expansion = mock.MagicMock(return_value=True)
    t._reload_combat_team = mock.MagicMock(return_value=True)
    t.log_info = mock.MagicMock()
    t._normalize_team_snapshot = lambda in_team, ci, c, source="": (
        (ci, c) if (in_team and ci != -1 and c > 0) else None
    )
    return t


class TestTeamShrinkConfirm(unittest.TestCase):
    """主循环减员二次确认(补齐 a22d93d 起就漏的路径): 单帧抖动不 reload, 持续减员才 reload。

    历史遗漏: check_team_changed_during_combat(战斗动作中)有 0.8s 候选确认, 但主循环每轮
    perform 前的 _reload_if_team_size_changed 从诞生起就无确认——某帧头像瞬时识别不到(切人
    过渡/大招演出)会误判减员直接 reload(实机: 2->1 抖动触发 reload, 旧代码进而崩溃)。
    """

    def test_single_frame_jitter_absorbed(self):
        # 减员一帧, 下一次 recheck 人数恢复 → 候选被清, 不 reload
        t = make_reload_task()
        t.in_team = mock.MagicMock(side_effect=[(True, 0, 1), (True, 0, 2)])
        with mock.patch("src.lw.combat_ext.time.time", side_effect=[10.0, 11.0]):
            r1 = t._reload_if_team_size_changed()
            r2 = t._reload_if_team_size_changed()
        self.assertTrue(r1)
        self.assertTrue(r2)
        t._reload_combat_team.assert_not_called()
        self.assertIsNone(t._roster_monitor()._size_candidate)

    def test_first_shrink_detection_does_not_reload(self):
        # 首次检测到减员只记候选、dump 诊断, 本轮不 reload
        t = make_reload_task()
        t.in_team = mock.MagicMock(side_effect=[(True, 0, 1)])
        with mock.patch("src.lw.combat_ext.time.time", side_effect=[10.0]):
            r = t._reload_if_team_size_changed()
        self.assertTrue(r)
        t._reload_combat_team.assert_not_called()
        self.assertEqual(t._roster_monitor()._size_candidate, (1, 10.0))
        t.lw_dump_char_slot_scores.assert_called_once()

    def test_sustained_shrink_requests_reload_after_confirm(self):
        # 连续两次 recheck(间隔≥确认窗口)都是同一减少后人数 → 中断旧动作, 交主循环 reload
        t = make_reload_task()
        t.in_team = mock.MagicMock(side_effect=[(True, 0, 1), (True, 0, 1)])
        with mock.patch("src.lw.combat_ext.time.time", side_effect=[10.0, 11.0]):
            r1 = t._reload_if_team_size_changed()
            with self.assertRaises(TeamReloadRequested) as raised:
                t._reload_if_team_size_changed()
        self.assertTrue(r1, "首次减员只记候选, 本轮不 reload")
        self.assertEqual(raised.exception.change.observed_count, 1)
        t._reload_combat_team.assert_not_called()
        self.assertIsNone(t._roster_monitor()._size_candidate)

    def test_recheck_throttled_within_interval(self):
        # 距上次检测不足 TEAM_RECHECK_INTERVAL → 短路, 不重复识别
        t = make_reload_task()
        t.in_team = mock.MagicMock(side_effect=[(True, 0, 1), (True, 0, 1)])
        with mock.patch("src.lw.combat_ext.time.time", side_effect=[10.0, 10.5]):
            t._reload_if_team_size_changed()
            t._reload_if_team_size_changed()
        self.assertEqual(t.in_team.call_count, 1, "节流窗口内不应再次识别队伍")
        t._reload_combat_team.assert_not_called()


class TestTeamChangeCheck(unittest.TestCase):
    def test_no_attribute_error_and_flag_reset(self):
        t = make_task()
        result = t.check_team_changed_during_combat(force=True)
        self.assertFalse(result)
        t.in_team.assert_called_once()
        self.assertFalse(t._team_change_checking, "检测后必须复位, 否则之后恒短路")

    def test_flag_reset_even_if_in_team_raises(self):
        t = make_task()
        t.in_team = mock.MagicMock(side_effect=RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            t.check_team_changed_during_combat(force=True)
        self.assertFalse(t._team_change_checking, "异常路径也必须复位(旧代码卡True→静默失效)")

    def test_sleep_check_skip_restored(self):
        t = make_task()
        t.check_team_changed_during_combat(force=True)
        self.assertFalse(t.sleep_check_skip.all, "skip 状态必须随上下文管理器退出还原")


class TestTeamReloadOptIn(unittest.TestCase):
    """队伍变更检测必须 opt-in(2026-07-21 日常任务事故回归)。

    背景: df8d8fb 把 TeamChangedException(NotInCombatException 子类)重构为
    TeamReloadRequested(普通 Exception), 只在 lw_combat_run 捕获; 但检测挂在
    check_combat 上, combat_once 路径(AnomalyTask/DSDFarmTask)也会触发——大招光效
    压低头像匹配分误报队伍变更后, 信号无人接, 一路炸穿 DailyTask 整条任务链。
    修复: 检测默认静默, 仅在 lw_combat_run 的 team_reload_watch 作用域内开启。
    锁住: 默认(combat_once 场景)不检测不抛; watch 作用域异常退出也必须复位开关。
    """

    def test_disabled_by_default_short_circuits(self):
        t = make_task()
        del t._team_reload_enabled  # 回到类级默认 False, 即 combat_once 场景
        result = t.check_team_changed_during_combat(force=True)
        self.assertFalse(result)
        t.in_team.assert_not_called()

    def test_watch_scope_enables_then_restores_on_exception(self):
        t = BaseCombatTask.__new__(BaseCombatTask)
        with self.assertRaises(RuntimeError):
            with t.team_reload_watch():
                self.assertTrue(t._team_reload_enabled)
                raise RuntimeError("boom")
        self.assertFalse(t._team_reload_enabled, "异常退出也必须复位, 否则泄漏到日常战斗")

    def test_watch_scope_resets_stale_candidates(self):
        t = BaseCombatTask.__new__(BaseCombatTask)
        t._roster_monitor().observe_size(
            expected_count=4, observed_count=3, now=10.0, confirm_interval=0.8
        )
        with t.team_reload_watch():
            self.assertIsNone(
                t._roster_monitor()._size_candidate,
                "上一场残留候选必须清掉, 否则新战斗开场可能瞬间确认误报",
            )


class TestTeamRosterMonitor(unittest.TestCase):
    def test_size_candidate_requires_continuous_confirmation(self):
        monitor = TeamRosterMonitor()
        status, change = monitor.observe_size(
            expected_count=4,
            observed_count=3,
            now=10.0,
            confirm_interval=0.8,
        )
        self.assertEqual(status, "candidate")
        self.assertIsNone(change)

        status, change = monitor.observe_size(
            expected_count=4,
            observed_count=3,
            now=10.9,
            confirm_interval=0.8,
        )
        self.assertEqual(status, "confirmed")
        self.assertEqual(change.observed_count, 3)

    def test_invalid_or_restored_observation_breaks_confirmation(self):
        monitor = TeamRosterMonitor()
        monitor.observe_size(
            expected_count=4,
            observed_count=3,
            now=10.0,
            confirm_interval=0.8,
        )
        monitor.clear_size()
        status, change = monitor.observe_size(
            expected_count=4,
            observed_count=3,
            now=11.0,
            confirm_interval=0.8,
        )
        self.assertEqual(status, "candidate")
        self.assertIsNone(change)

    def test_reload_signal_is_not_out_of_combat(self):
        from src.combat.BaseCombatTask import NotInCombatException

        self.assertFalse(issubclass(TeamReloadRequested, NotInCombatException))


if __name__ == "__main__":
    unittest.main()
