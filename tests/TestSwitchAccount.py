import unittest

from src.tasks.SwitchAccountTask import LOGIN_BTN_RE, UID_RE, SwitchAccountTask


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
        picked = SwitchAccountTask.pick_target(rows, "167250072", "167365281")
        self.assertIs(picked, rows[1])

    def test_pick_target_auto_switches_to_other(self):
        rows = [FakeBox("167365281"), FakeBox("167250072")]
        picked = SwitchAccountTask.pick_target(rows, "", "167365281")
        self.assertIs(picked, rows[1])
        picked = SwitchAccountTask.pick_target(rows, "", "167250072")
        self.assertIs(picked, rows[0])

    def test_pick_target_missing_uid_returns_none(self):
        rows = [FakeBox("167365281"), FakeBox("167250072")]
        self.assertIsNone(SwitchAccountTask.pick_target(rows, "999999999", "167365281"))


class TestSelectAccountFlow(unittest.TestCase):
    def _task(self, ocr_frames):
        """ocr_frames: read_account_uids 每次调用依次返回的列表(耗尽后重复最后一帧)。"""
        task = object.__new__(SwitchAccountTask)
        task.clicks = []
        task.info_messages = []
        frames = list(ocr_frames)

        def read_account_uids():
            if len(frames) > 1:
                return frames.pop(0)
            return frames[0]

        def operate_click(x, y=None, **kwargs):
            task.clicks.append(x if y is None else (x, y))

        def wait_until(predicate, **kwargs):
            for _ in range(5):
                result = predicate()
                if result:
                    return result
            return None

        task.read_account_uids = read_account_uids
        task.operate_click = operate_click
        task.wait_until = wait_until
        task.log_info = lambda message, *args, **kwargs: task.info_messages.append(message)
        return task

    def test_select_expands_clicks_row_and_verifies(self):
        row_a, row_b = FakeBox("167365281"), FakeBox("167250072")
        task = self._task(
            [
                [row_a],  # 折叠态: 当前账号A
                [row_a, row_b],  # 点箭头后展开
                [row_b],  # 点B后收起显示B
            ]
        )
        chosen = task.select_account("")
        self.assertEqual(chosen, "167250072")
        # 第一次点下拉箭头(坐标), 第二次点账号B(box)
        self.assertEqual(task.clicks[0], SwitchAccountTask.DROPDOWN_ARROW)
        self.assertIs(task.clicks[1], row_b)

    def test_select_skips_when_target_already_current(self):
        row_b = FakeBox("167250072")
        task = self._task([[row_b]])
        chosen = task.select_account("167250072")
        self.assertEqual(chosen, "167250072")
        self.assertEqual(task.clicks, [])

    def test_select_raises_when_target_not_in_list(self):
        row_a, row_b = FakeBox("167365281"), FakeBox("167250072")
        task = self._task([[row_a], [row_a, row_b]])
        with self.assertRaises(RuntimeError):
            task.select_account("999999999")


if __name__ == "__main__":
    unittest.main()
