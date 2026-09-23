import unittest
from unittest.mock import Mock

from ok import CannotFindException, TaskDisabledException

from src.lw.daily_claim_ext import F2_UNAVAILABLE_REASON, DailyClaimExtMixin
from src.tasks.daily.DailyClaimTask import DailyClaimTask


class ClaimTask(DailyClaimExtMixin):
    def __init__(self):
        super().__init__()
        self.log_warning = Mock()


class TestDailyClaimIsolation(unittest.TestCase):
    def test_failed_sub_item_records_reason_and_later_items_still_run(self):
        task = ClaimTask()
        task.lw_begin_claims()

        def boom():
            raise CannotFindException("can't find mail panel")

        later = Mock(return_value=True)
        self.assertFalse(task.lw_run_claim_item("邮件", boom))
        self.assertTrue(task.lw_run_claim_item("活跃度奖励", later))

        later.assert_called_once()
        self.assertEqual(
            task.failure_details, ["邮件: CannotFindException: can't find mail panel"]
        )

    def test_missing_f2_panel_is_a_quiet_reasoned_failure(self):
        task = ClaimTask()
        task.lw_begin_claims()
        task.is_in_team = Mock(return_value=True)
        task.send_key = Mock()
        task.sleep = Mock()
        task.wait_panel = Mock(return_value=None)
        task.log_error = Mock()

        def battle_pass():
            if not task.lw_open_f2_panel():
                return False
            return True

        self.assertFalse(task.lw_run_claim_item("环期任务奖励", battle_pass))
        self.assertEqual(task.failure_details, [f"环期任务奖励: {F2_UNAVAILABLE_REASON}"])
        task.log_error.assert_not_called()

    def test_user_stop_still_propagates(self):
        task = ClaimTask()

        def stopped():
            raise TaskDisabledException()

        with self.assertRaises(TaskDisabledException):
            task.lw_run_claim_item("邮件", stopped)

    def test_details_reset_each_run(self):
        task = ClaimTask()
        task.failure_details = ["old"]
        task.lw_begin_claims()
        self.assertEqual(task.failure_details, [])

    def test_daily_claim_task_uses_isolation_mixin(self):
        self.assertTrue(issubclass(DailyClaimTask, DailyClaimExtMixin))


if __name__ == "__main__":
    unittest.main()
