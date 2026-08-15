from dataclasses import dataclass


@dataclass(frozen=True)
class DailyRoutineAccountResult:
    account_name: str
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
        self._retry_task_ids: tuple[str, ...] = ()
        self._active_retry_task_ids: frozenset[str] = frozenset()
        self._recorded_status_id: int | None = None

    def lw_begin_daily_run(self):
        self.account_results = []
        self.task_failure_details = {}
        self._active_retry_task_ids = frozenset()
        self._recorded_status_id = None

    def lw_take_retry_task_ids(self):
        task_ids = self._retry_task_ids
        self._retry_task_ids = ()
        self._active_retry_task_ids = frozenset(task_ids)
        return task_ids

    def lw_is_retrying_task(self, task_id):
        return task_id in getattr(self, "_active_retry_task_ids", frozenset())

    def lw_prepare_retry_failed_items(self):
        if not self.account_results:
            return False
        failed_task_ids = self.account_results[-1].failed
        if not failed_task_ids:
            return False
        self._retry_task_ids = failed_task_ids
        return True

    def lw_can_retry_failed_items(self):
        return bool(self.account_results and self.account_results[-1].failed)

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

    def lw_record_current_routine_result(self, account_name):
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
