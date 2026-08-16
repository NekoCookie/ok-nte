import unittest
from unittest.mock import MagicMock, patch

from src.tasks.SwitchAccountTask import (
    DROPDOWN_ARROW,
    LOGIN_BTN_RE,
    UID_RE,
    SwitchAccountTask,
    pick_target,
    select_account,
)


class FakeBox:
    def __init__(self, name):
        self.name = name


class TestSwitchAccountLogic(unittest.TestCase):
    def test_uid_re_matches_uid_only(self):
        self.assertTrue(UID_RE.match("167365281"))
        self.assertTrue(UID_RE.match("167250072"))
        # 手机号掩码行: 带星号或吞星号后仅7位, 都不能误认成UID
        self.assertFalse(UID_RE.match("156****9844"))
        self.assertFalse(UID_RE.match("1569844"))
        self.assertFalse(UID_RE.match("京ICP备2021013357号"))

    def test_login_btn_re_excludes_other_login(self):
        self.assertTrue(LOGIN_BTN_RE.match("登录"))
        self.assertTrue(LOGIN_BTN_RE.match("登 录"))
        self.assertFalse(LOGIN_BTN_RE.match("使用其他方式登录"))

    def test_pick_target_by_uid(self):
        rows = [FakeBox("167365281"), FakeBox("167250072")]
        picked = pick_target(rows, "167250072", "167365281")
        self.assertIs(picked, rows[1])

    def test_pick_target_auto_switches_to_other(self):
        rows = [FakeBox("167365281"), FakeBox("167250072")]
        self.assertIs(pick_target(rows, "", "167365281"), rows[1])
        self.assertIs(pick_target(rows, "", "167250072"), rows[0])

    def test_pick_target_missing_uid_returns_none(self):
        rows = [FakeBox("167365281"), FakeBox("167250072")]
        self.assertIsNone(pick_target(rows, "999999999", "167365281"))


class FakePanel:
    """read_uids 按帧序列出结果, 记录点击。"""

    def __init__(self, uid_frames):
        self.clicks = []
        self._frames = list(uid_frames)

    def read_uids(self):
        if len(self._frames) > 1:
            return self._frames.pop(0)
        return self._frames[0]

    def click(self, rx, ry):
        self.clicks.append((rx, ry))

    def click_box(self, box):
        self.clicks.append(box)


class FakeTask:
    def __init__(self):
        self.info_messages = []

    def sleep(self, seconds):
        pass

    def wait_until(self, predicate, **kwargs):
        for _ in range(5):
            result = predicate()
            if result:
                return result
        return None

    def log_info(self, message, *args, **kwargs):
        self.info_messages.append(message)


class TestSelectAccountFlow(unittest.TestCase):
    def test_select_expands_clicks_row_and_verifies(self):
        row_a, row_b = FakeBox("167365281"), FakeBox("167250072")
        panel = FakePanel(
            [
                [row_a],  # 折叠态: 当前账号A
                [row_a, row_b],  # 点箭头后展开
                [row_b],  # 点B后收起显示B
            ]
        )
        chosen, previous = select_account(FakeTask(), panel, "")
        self.assertEqual(chosen, "167250072")
        self.assertEqual(previous, "167365281")
        # 第一次点下拉箭头(坐标), 第二次点账号B(box)
        self.assertEqual(panel.clicks[0], DROPDOWN_ARROW)
        self.assertIs(panel.clicks[1], row_b)

    def test_select_skips_when_target_already_current(self):
        row_b = FakeBox("167250072")
        panel = FakePanel([[row_b]])
        chosen, previous = select_account(FakeTask(), panel, "167250072")
        self.assertEqual(chosen, "167250072")
        self.assertEqual(previous, "167250072")
        self.assertEqual(panel.clicks, [])

    def test_select_raises_when_target_not_in_list(self):
        row_a, row_b = FakeBox("167365281"), FakeBox("167250072")
        panel = FakePanel([[row_a], [row_a, row_b]])
        with self.assertRaises(RuntimeError):
            select_account(FakeTask(), panel, "999999999")


class TestDailyAccountCycle(unittest.TestCase):
    """lw_daily_account_cycle 的门控逻辑: 无任务/开关关闭不动作, 打开则换号+再跑一轮。"""

    def _daily(self, switch_task):
        from src.lw.nte_task_ext import NTETaskExtMixin

        daily = object.__new__(NTETaskExtMixin)
        daily.get_task_by_class = lambda cls: switch_task
        daily.log_info = MagicMock()
        daily.do_run = MagicMock()
        return daily

    def test_noop_without_switch_task(self):
        daily = self._daily(None)
        with patch("src.tasks.SwitchAccountTask.switch_account") as sw:
            daily.lw_daily_account_cycle()
        sw.assert_not_called()
        daily.do_run.assert_not_called()

    def test_noop_when_disabled(self):
        switch = MagicMock()
        switch.config = {SwitchAccountTask.CONF_CYCLE_WITH_DAILY: False}
        daily = self._daily(switch)
        with patch("src.tasks.SwitchAccountTask.switch_account") as sw:
            daily.lw_daily_account_cycle()
        sw.assert_not_called()
        daily.do_run.assert_not_called()

    def test_cycle_switches_then_reruns_daily(self):
        switch = MagicMock()
        switch.config = {
            SwitchAccountTask.CONF_CYCLE_WITH_DAILY: True,
            SwitchAccountTask.CONF_SWITCH_BACK: False,
        }
        daily = self._daily(switch)
        with patch(
            "src.tasks.SwitchAccountTask.switch_account", return_value=("167250072", "167365281")
        ) as sw:
            daily.lw_daily_account_cycle()
        sw.assert_called_once_with(daily)
        daily.do_run.assert_called_once()

    def test_cycle_records_account_ids_for_later_targeted_retry(self):
        switch = MagicMock()
        switch.config = {
            SwitchAccountTask.CONF_CYCLE_WITH_DAILY: True,
            SwitchAccountTask.CONF_SWITCH_BACK: False,
        }
        daily = self._daily(switch)
        daily.lw_record_current_routine_result = MagicMock()
        daily.lw_set_current_daily_account = MagicMock()
        with patch(
            "src.tasks.SwitchAccountTask.switch_account", return_value=("167250072", "167365281")
        ):
            daily.lw_daily_account_cycle()

        self.assertEqual(
            [call.args for call in daily.lw_record_current_routine_result.call_args_list],
            [("账号 1", "167365281"), ("账号 2", "167250072")],
        )
        daily.lw_set_current_daily_account.assert_called_once_with("167250072")

    def test_cycle_switches_back_to_original_when_enabled(self):
        switch = MagicMock()
        switch.config = {
            SwitchAccountTask.CONF_CYCLE_WITH_DAILY: True,
            SwitchAccountTask.CONF_SWITCH_BACK: True,
        }
        daily = self._daily(switch)
        with patch(
            "src.tasks.SwitchAccountTask.switch_account", return_value=("167250072", "167365281")
        ) as sw:
            daily.lw_daily_account_cycle()
        self.assertEqual(sw.call_count, 2)
        # 第二次按原UID精确切回
        self.assertEqual(sw.call_args_list[1].args, (daily, "167365281"))
        daily.do_run.assert_called_once()

    def test_no_switch_back_when_second_round_fails(self):
        switch = MagicMock()
        switch.config = {
            SwitchAccountTask.CONF_CYCLE_WITH_DAILY: True,
            SwitchAccountTask.CONF_SWITCH_BACK: True,
        }
        daily = self._daily(switch)
        daily.do_run.side_effect = RuntimeError("second round failed")
        with patch(
            "src.tasks.SwitchAccountTask.switch_account", return_value=("167250072", "167365281")
        ) as sw:
            with self.assertRaises(RuntimeError):
                daily.lw_daily_account_cycle()
        sw.assert_called_once()  # 只切了去程, 没切回


if __name__ == "__main__":
    unittest.main()
