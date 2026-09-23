"""[lw] Daily-claim sub-item isolation and readable failure reasons."""

from ok import TaskDisabledException

from src.Labels import Labels

F2_UNAVAILABLE_REASON = "F2面板未出现, 卡池更替期间F2可能暂时关闭"


class DailyClaimExtMixin:
    """Run each claim sub-item independently and report why a sub-item failed.

    ``failure_details`` is the protocol read by ``DailyRoutineTask`` for the
    failure summary, so no notification toast or exception is needed.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.failure_details: list[str] = []
        self._lw_claim_reason: str | None = None

    def lw_begin_claims(self):
        self.failure_details = []

    def lw_run_claim_item(self, name: str, claim) -> bool:
        """Run one sub-item; a failure is recorded and never stops later sub-items."""
        self._lw_claim_reason = None
        error_reason = None
        try:
            result = claim()
        except TaskDisabledException:
            raise
        except Exception as error:
            self.log_warning(f"{name}失败: {error}")
            error_reason = f"{type(error).__name__}: {error}"
            result = False
        if result is False:
            reason = self._lw_claim_reason or error_reason or "未完成"
            self.failure_details.append(f"{name}: {reason}")
        return result

    def lw_open_f2_panel(self):
        """Open F2 without the RU hotkey error toast; F2 can be absent between gacha pools."""
        if hasattr(self, "reset_to_false"):
            self.reset_to_false()
        if self.is_in_team():
            self.send_key("f2", after_sleep=1)
        panel = self.wait_panel(Labels.f2_panel)
        if not panel:
            self._lw_claim_reason = F2_UNAVAILABLE_REASON
            return None
        self.sleep(0.5)
        return panel
