"""[lw] Per-furniture daily retry and failure details."""

from __future__ import annotations

from ok import TaskDisabledException

from src.Labels import Labels


class FurnitureTaskExtMixin:
    """Keep LW furniture retry state outside the RU FurnitureTask contract."""

    LW_SUPPORTED_FURNITURE = (Labels.anomaly_fluff,)

    def lw_init_furniture_retry_state(self):
        self.furniture_results = {}
        self.failure_details = []
        self._retry_furniture = ()
        self._claim_failure_reason = None

    def lw_claim_anomaly_furniture(self):
        """Claim each selected furniture item independently and retain failure details."""

        self.log_info("正在领取异象家具奖励")
        furniture_list = self._retry_furniture or self.LW_SUPPORTED_FURNITURE
        self._retry_furniture = ()
        self.furniture_results = {}
        self.failure_details = []
        for furniture in furniture_list:
            self._claim_failure_reason = None
            try:
                claimed = self.claim_furniture(furniture)
            except TaskDisabledException:
                raise
            except Exception as error:
                self.log_error(f"领取异象家具失败: {furniture}", error)
                claimed = False
                self._claim_failure_reason = str(error).strip() or type(error).__name__

            failure_reason = None
            if not claimed:
                failure_reason = self._claim_failure_reason or "领取流程未完成"
                self.failure_details.append(f"{furniture.value}: {failure_reason}")
            self.furniture_results[furniture] = claimed
            result = "成功" if claimed else "失败"
            message = f"异象家具 {furniture.value} 领取{result}"
            if failure_reason:
                message = f"{message}: {failure_reason}"
            self.log_info(message)

        all_claimed = all(self.furniture_results.values())
        if all_claimed:
            self.log_info("异象家具奖励全部领取成功")
        else:
            self.log_error("异象家具奖励未能全部领取成功")
        return all_claimed

    def lw_record_furniture_claim_failure(self, reason):
        self._claim_failure_reason = reason

    def prepare_retry(self):
        self._retry_furniture = tuple(
            furniture for furniture, claimed in self.furniture_results.items() if not claimed
        )
        return bool(self._retry_furniture)
