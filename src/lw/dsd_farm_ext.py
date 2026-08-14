# [lw] DSDFarmTask(九百九十九夜) 的用户扩展:
# - 目标篝火按地点固定区域和确定性规则识别, 不运行期生成或读取临时锚点
# - click_traval_button: 修正上游"传送按钮未消失仍返回成功"的假成功判定
# - lw_wait_interac: 传送后交互提示缺失时, 先回主界面等加载, 仍失败再传送一次
#   (接线: DSDFarmTask.ensure_teleport 有界重试 + do_run 两个一行钩子)
import time
from typing import TYPE_CHECKING

from ok import Box, TaskDisabledException, WaitFailedException

if TYPE_CHECKING:
    from src.tasks.DSDFarmTask import DSDFarmTask

    _TaskProxy = DSDFarmTask
else:

    class _TaskProxy:
        pass


class DSDFarmExtMixin(_TaskProxy):
    # 长挂机时地图状态可能短暂异常: 所有等待/重试都有界, 不无限等待也不无限走位
    LW_MAX_TELEPORT_ATTEMPTS = 4
    LW_INTERAC_RECOVER_WAIT = 30
    LW_TRAVEL_BUTTON_STUCK_WAIT = 6
    LW_INPUT_PAUSE_POLL_INTERVAL = 0.05

    def _lw_held_keys(self):
        keys = getattr(self, "_lw_held_key_set", None)
        if keys is None:
            keys = set()
            self._lw_held_key_set = keys
        return keys

    def lw_release_held_keys(self):
        """Release keys held by 999 before waiting in either pause layer."""
        keys = self._lw_held_keys()
        if not keys:
            return
        interaction = self.executor.interaction
        for key in tuple(keys):
            interaction.send_key_up(key)

    def lw_restore_held_keys(self):
        """Restore keys released temporarily while 999 was paused."""
        keys = self._lw_held_keys()
        if not keys:
            return
        interaction = self.executor.interaction
        for key in tuple(keys):
            interaction.send_key_down(key)
    def lw_max_teleport_attempts(self):
        """RU ensure_teleport 的有界重试上限。"""
        return self.LW_MAX_TELEPORT_ATTEMPTS

    def lw_ensure_teleport_or_stop(self, fun):
        """Stop the farming task when bounded teleport recovery is exhausted."""
        if self.ensure_teleport(fun):
            return True
        self.log_error("传送回目标篝火失败, 已停止九百九十九夜挂机")
        raise TaskDisabledException()

    def lw_input_paused(self):
        """Return whether either the current task or the global executor is paused."""
        return self.paused or self.executor.paused

    def lw_wait_until_input_allowed(self):
        """Wait for both pause layers to clear, or stop immediately when 999 is disabled."""
        paused = False
        while True:
            try:
                self.executor.check_enabled(check_pause=False)
            except TaskDisabledException:
                self.lw_release_held_keys()
                raise
            if not self.lw_input_paused():
                if paused:
                    self.lw_restore_held_keys()
                return
            if not paused:
                self.lw_release_held_keys()
                paused = True
            time.sleep(self.LW_INPUT_PAUSE_POLL_INTERVAL)

    def lw_perform_input(self, action, *args, **kwargs):
        """Run one input action only while 999 and the global executor are both active."""
        self.lw_wait_until_input_allowed()
        return action(*args, **kwargs)

    def lw_hold_key_cancellable(self, key, duration):
        """Hold a recovery key, releasing it whenever either pause layer is entered."""
        interaction = self.executor.interaction
        remaining = duration
        key_down = False
        try:
            while remaining > 0:
                self.executor.check_enabled(check_pause=False)
                if self.lw_input_paused():
                    if key_down:
                        interaction.send_key_up(key)
                        key_down = False
                    self.lw_wait_until_input_allowed()
                    continue
                if not key_down:
                    interaction.send_key_down(key)
                    key_down = True
                wait_time = min(remaining, self.LW_INPUT_PAUSE_POLL_INTERVAL)
                start = time.monotonic()
                time.sleep(wait_time)
                remaining -= time.monotonic() - start
        finally:
            if key_down:
                interaction.send_key_up(key)

    def click_traval_button(self, travel_btn=None, raise_if_not_found=True):
        """修正 RU 假成功, 并用更短的卡死等待快速失败, 交给有界重试重新开图。"""
        if not isinstance(travel_btn, Box):
            travel_btn = self.wait_until(
                self.find_traval_button,
                time_out=10,
                raise_if_not_found=raise_if_not_found,
            )
        if not travel_btn:
            return False
        self.sleep(0.1)
        result = self.wait_until(
            lambda: not self.find_traval_button(),
            pre_action=lambda: self.lw_perform_input(
                self.operate_click, travel_btn, interval=2
            ),
            time_out=self.LW_TRAVEL_BUTTON_STUCK_WAIT,
            settle_time=0.5,
            raise_if_not_found=False,
        )
        self.monitor_and_sync_cursor()
        self.sleep(0.1)
        if not result:
            self.log_warning_gated("travel button still visible, teleport did not complete")
        return bool(result)

    def lw_teleport_to_nearest_bonfire(self, threshold=0.7, time_out=10):
        """Teleport to the configured volcano target using deterministic map selection."""
        return self._ru_teleport_to_nearest_bonfire(
            threshold=threshold,
            time_out=time_out,
            target_selector=self._lw_select_volcano_bonfire,
        )

    def lw_teleport_to_top_bonfire(self, box, threshold=0.7):
        """Teleport to a top bonfire using the location-specific deterministic box."""
        return self._ru_teleport_to_top_bonfire(box=box, threshold=threshold)

    def lw_wait_interac(self, time_out=10):
        """等待篝火交互提示; 缺失时先回主界面等加载, 仍失败则重新传送一次。"""
        if self.wait_until(self.find_interac, time_out=time_out, raise_if_not_found=False):
            return True
        self.ensure_main()
        if self.wait_until(
            self.find_interac, time_out=self.LW_INTERAC_RECOVER_WAIT, raise_if_not_found=False
        ):
            return True
        self.log_warning_gated("interact prompt missing after teleport, re-teleporting")
        self.lw_teleport_back_to_location()
        self.sleep(1)
        found = self.wait_until(
            self.find_interac, time_out=self.LW_INTERAC_RECOVER_WAIT, raise_if_not_found=False
        )
        if not found:
            self.screenshot("dsd_farm_interac_missing")
            raise WaitFailedException()
        return found

    def lw_teleport_back_to_location(self):
        """按当前配置位置重新执行一次有界传送回篝火。"""
        location = self.config.get(self.CONF_LOCATION, None)
        if location == self.locations[0]:
            return self.lw_ensure_teleport_or_stop(lambda: self.teleport_to_nearest_bonfire())
        if location == self.locations[1]:
            box = self.box_of_screen(0.498, 0.102, 0.931, 0.827)
            return self.lw_ensure_teleport_or_stop(lambda: self.teleport_to_top_bonfire(box))
        box = self.box_of_screen(0.410, 0.234, 0.560, 0.556)
        return self.lw_ensure_teleport_or_stop(lambda: self.teleport_to_top_bonfire(box))

    @staticmethod
    def _lw_select_volcano_bonfire(icons):
        """The configured volcano target is the leftmost bonfire on the bottom layer."""
        return min(icons, key=lambda icon: (icon.x, -icon.y))
