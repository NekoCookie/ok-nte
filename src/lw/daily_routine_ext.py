from dataclasses import dataclass

from ok import TaskDisabledException


@dataclass(frozen=True)
class DailyRoutineAccountResult:
    account_name: str
    account_uid: str | None
    success: tuple[str, ...]
    failed: tuple[str, ...]
    skipped: tuple[str, ...]
    failure_details: tuple[tuple[str, tuple[str, ...]], ...]


class DailyRoutineExtMixin:
    """[lw] Account-aware summaries and targeted retries for the daily routine."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.account_results: list[DailyRoutineAccountResult] = []
        self.task_failure_details: dict[str, list[str]] = {}
        self._retry_plan: tuple[DailyRoutineAccountResult, ...] = ()
        self._retry_return_account: DailyRoutineAccountResult | None = None
        self._active_retry_task_ids: frozenset[str] = frozenset()
        self._current_daily_account_uid: str | None = None
        self._recorded_status_id: int | None = None

    def lw_begin_daily_run(self):
        self.account_results = []
        self.task_failure_details = {}
        self._active_retry_task_ids = frozenset()
        self._recorded_status_id = None

    def lw_take_retry_plan(self):
        retry_plan = self._retry_plan
        return_account = self._retry_return_account
        self._retry_plan = ()
        self._retry_return_account = None
        self._active_retry_task_ids = frozenset()
        return retry_plan, return_account

    def lw_is_retrying_task(self, task_id):
        return task_id in getattr(self, "_active_retry_task_ids", frozenset())

    def lw_filter_retry_items(self, items):
        retry_ids = getattr(self, "_active_retry_task_ids", frozenset())
        if not retry_ids:
            return items
        self.log_info(f"Retry failed tasks: {sorted(retry_ids)}")
        return [
            {"id": item["id"], "enabled": True}
            for item in items
            if item["id"] in retry_ids
        ]

    def lw_prepare_retry_failed_items(self):
        retry_plan = tuple(result for result in self.account_results if result.failed)
        if not retry_plan or not self.lw_can_retry_failed_items():
            return False
        self._retry_plan = retry_plan
        self._retry_return_account = self.account_results[0] if len(self.account_results) > 1 else None
        return True

    def lw_start_retry_failed_items(self, start_controller):
        """Start a targeted retry without exposing LW retry state to RU helpers."""

        if not self.lw_prepare_retry_failed_items():
            return False
        if start_controller.do_start(self):
            return True
        self._retry_plan = ()
        self._retry_return_account = None
        return False

    def lw_can_retry_failed_items(self):
        retry_results = [result for result in self.account_results if result.failed]
        if not retry_results:
            return False
        if len(self.account_results) == 1:
            return True
        return all(
            result.account_uid
            for result in (self.account_results[0], *retry_results)
        )

    def lw_set_current_daily_account(self, account_uid):
        self._current_daily_account_uid = account_uid or None

    def lw_switch_to_daily_account(self, account_uid):
        if not account_uid or self._current_daily_account_uid == account_uid:
            return

        from src.tasks.SwitchAccountTask import switch_account

        selected_account_uid, _ = switch_account(self, account_uid)
        if selected_account_uid != account_uid:
            raise RuntimeError(f"Switched to unexpected account: {selected_account_uid}")
        self.lw_set_current_daily_account(selected_account_uid)

    def lw_run_retry_plan(self, retry_plan, return_account):
        try:
            for result in retry_plan:
                self.lw_switch_to_daily_account(result.account_uid)
                self._active_retry_task_ids = frozenset(result.failed)
                self.do_run()
                self.lw_record_current_routine_result(result.account_name, result.account_uid)
        finally:
            self._active_retry_task_ids = frozenset()
            if return_account is not None:
                self.lw_switch_to_daily_account(return_account.account_uid)

    def lw_prepare_task_retry(self, task):
        prepare_retry = getattr(task, "prepare_retry", None)
        if callable(prepare_retry):
            prepare_retry()

    def lw_record_task_failure(self, task_id, task, error=None):
        task_details = getattr(task, "failure_details", ())
        details = list(task_details) if isinstance(task_details, (list, tuple)) else []
        if error is not None:
            error_name = type(error).__name__
            error_text = str(error).strip()
            details.append(f"{error_name}: {error_text}" if error_text else error_name)
        if details:
            self.task_failure_details[task_id] = details

    def lw_task_result_display_name(self, task_id, display_name):
        details = self.task_failure_details.get(task_id, ())
        if not details:
            return display_name
        return f"{display_name} ({'; '.join(details)})"

    def lw_record_current_routine_result(self, account_name, account_uid=None):
        if self._recorded_status_id == id(self.task_status):
            return
        status = self.task_status
        details = tuple(
            (task_id, tuple(self.task_failure_details.get(task_id, ())))
            for task_id in status.get("failed", ())
            if self.task_failure_details.get(task_id)
        )
        self.account_results.append(
            DailyRoutineAccountResult(
                account_name=account_name or "当前账号",
                account_uid=account_uid,
                success=tuple(status.get("success", ())),
                failed=tuple(status.get("failed", ())),
                skipped=tuple(status.get("skipped", ())),
                failure_details=details,
            )
        )
        self._recorded_status_id = id(status)

    def lw_finish_daily_run(self):
        if getattr(self, "task_status", None) is not None:
            self.lw_record_current_routine_result("当前账号")
        if not self.account_results:
            return

        summaries = {
            status: "\n".join(
                f"{result.account_name}: {self._daily_result_names(result, status)}"
                for result in self.account_results
            )
            for status in ("success", "failed", "skipped")
        }
        for status, summary in summaries.items():
            self.info_set(status, summary)
        self.log_info(
            "\n".join(f"{status}: {summary}" for status, summary in summaries.items()),
            notify=True,
        )

    def lw_run_daily(self):
        """Run account summaries and retries around the unchanged RU daily workflow."""

        retry_plan, return_account = self.lw_take_retry_plan()
        self.lw_begin_daily_run()
        try:
            if retry_plan:
                self.lw_run_retry_plan(retry_plan, return_account)
            else:
                self.do_run()
                self.lw_daily_account_cycle()
            self.lw_finish_daily_run()
        except TaskDisabledException:
            raise
        except Exception as error:
            self.screenshot("daily_routine_unexpected_exception")
            if self.current_task_key:
                self.info_set("当前失败任务", self.current_task_key)
            self._print_result()
            self.lw_finish_daily_run()
            self.log_error("DailyRoutineTask error", error)
            raise

    def _daily_result_names(self, result, status):
        task_ids = getattr(result, status)
        details_by_task = dict(result.failure_details)
        return [
            self.lw_task_result_display_name_from_details(
                task_id,
                details_by_task.get(task_id, ()),
            )
            for task_id in task_ids
        ]

    def lw_task_result_display_name_from_details(self, task_id, details):
        display_name = self._task_display_name(task_id)
        if not details:
            return display_name
        return f"{display_name} ({'; '.join(details)})"

    def lw_reset_task_failure_details(self):
        self.task_failure_details = {}
