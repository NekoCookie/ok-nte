# [lw] DSDFarmTask(九百九十九夜) 的用户扩展:
# - click_traval_button: 修正上游"传送按钮未消失仍返回成功"的假成功判定
# - teleport_to_nearest_bonfire: 按离地图中心最近顺序逐个尝试篝火候选
# - lw_wait_interac: 传送后交互提示缺失时, 先回主界面等加载, 仍失败再传送一次
#   (接线: DSDFarmTask.ensure_teleport 有界重试 + do_run 一行调用)
from typing import TYPE_CHECKING

from ok import WaitFailedException

from src.Labels import Labels

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
    LW_TRAVEL_BUTTON_WAIT = 3
    LW_MAX_TELEPORT_CANDIDATES = 3

    def lw_max_teleport_attempts(self):
        """RU ensure_teleport 的有界重试上限。"""
        return self.LW_MAX_TELEPORT_ATTEMPTS

    def click_traval_button(self, travel_btn=None, raise_if_not_found=True):
        """修正 RU 假成功: 传送按钮仍可见时说明传送没有完成, 返回 False。"""
        result = super().click_traval_button(
            travel_btn=travel_btn, raise_if_not_found=raise_if_not_found
        )
        if result and self.find_traval_button():
            self.log_warning_gated("travel button still visible, teleport did not complete")
            return False
        return result

    def teleport_to_nearest_bonfire(self, threshold=0.7, time_out=10):
        """按离地图中心最近的顺序逐个尝试篝火, 避免点到无效图标后整轮失败。

        上游只点"最近的一个", 挂机久了地图上最近的图标可能是无效/非目标篝火,
        点完既没有传送按钮也没有任何反馈。这里收集候选后逐个尝试, 全部失败才
        返回 False, 交给 ensure_teleport 有界重试。
        """

        def find_candidates():
            teleports = self.find_feature(
                Labels.bonfire_teleport, box=self.main_viewport, threshold=threshold
            )
            if not teleports:
                return None
            teleports.sort(key=lambda tp: tp.center_distance(self.default_box.center))
            return teleports

        self.ensure_main()
        self.open_map()
        teleports = self.wait_until(find_candidates, time_out=time_out, raise_if_not_found=False)
        if not teleports:
            return False
        for teleport in teleports[: self.LW_MAX_TELEPORT_CANDIDATES]:
            self.log_info(f"lw try map teleport {teleport}")
            self.operate_click(teleport, action_name="click_nearest_map_teleport")
            self.sleep(0.5)
            travel_btn = self.wait_until(
                self.find_traval_button,
                time_out=self.LW_TRAVEL_BUTTON_WAIT,
                raise_if_not_found=False,
            )
            if not travel_btn:
                self.log_warning_gated("no travel button for map teleport candidate, try next")
                continue
            if self.click_traval_button(travel_btn=travel_btn, raise_if_not_found=False):
                return True
        return False

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
            return self.ensure_teleport(lambda: self.teleport_to_nearest_bonfire())
        if location == self.locations[1]:
            box = self.box_of_screen(0.498, 0.102, 0.931, 0.827)
            return self.ensure_teleport(lambda: self.teleport_to_top_bonfire(box))
        box = self.box_of_screen(0.410, 0.234, 0.560, 0.556)
        return self.ensure_teleport(lambda: self.teleport_to_top_bonfire(box))
