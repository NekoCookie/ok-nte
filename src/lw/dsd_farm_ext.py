# [lw] DSDFarmTask(九百九十九夜) 的用户扩展:
# - 目标篝火按地点分开识别: 每个地点独立校准一个"篝火图标+周边地形"地图锚点,
#   角色跑偏、篝火不在地图中心时, 也通过全地图匹配锚点找到正确篝火, 不随机试候选
# - click_traval_button: 修正上游"传送按钮未消失仍返回成功"的假成功判定
# - lw_wait_interac: 传送后交互提示缺失时, 先回主界面等加载, 仍失败再传送一次
#   (接线: DSDFarmTask.ensure_teleport 有界重试 + do_run 两个一行钩子)
import json
import os
from contextlib import suppress
from typing import TYPE_CHECKING

import cv2
import numpy as np

from ok import Box, TaskDisabledException, WaitFailedException

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
    LW_TRAVEL_BUTTON_STUCK_WAIT = 6
    LW_ANCHOR_THRESHOLD = 0.90
    LW_ANCHOR_PEAK_MARGIN = 0.03
    LW_ANCHOR_VERSION = 3
    LW_ANCHOR_CALIBRATE_SIZES = (260, 340, 420)
    LW_ANCHOR_FOLDER = os.path.join("screenshots", "dsd_farm_anchors")

    def lw_max_teleport_attempts(self):
        """RU ensure_teleport 的有界重试上限。"""
        return self.LW_MAX_TELEPORT_ATTEMPTS

    def lw_ensure_teleport_or_stop(self, fun):
        """Stop the farming task when bounded teleport recovery is exhausted."""
        if self.ensure_teleport(fun):
            return True
        self.log_error("传送回目标篝火失败, 已停止九百九十九夜挂机")
        raise TaskDisabledException()

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
            pre_action=lambda: self.operate_click(travel_btn, interval=2),
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
        """Teleport to the fixed volcano target or use anchors for other locations."""
        search = self._ru_teleport_to_nearest_bonfire
        if self._lw_is_volcano_location():
            return search(
                threshold=threshold,
                time_out=time_out,
                target_selector=self._lw_select_volcano_bonfire,
            )
        return self._lw_teleport_via_anchor(
            lambda map_is_open=False: search(
                threshold=threshold,
                time_out=time_out,
                map_is_open=map_is_open,
                target_selector=self._lw_select_volcano_bonfire,
            )
        )

    def lw_teleport_to_top_bonfire(self, box, threshold=0.7):
        """优先用地图锚点识别目标篝火, 失败退回上游框选搜索。"""
        search = self._ru_teleport_to_top_bonfire
        return self._lw_teleport_via_anchor(
            lambda map_is_open=False: search(
                box=box, threshold=threshold, map_is_open=map_is_open
            )
        )

    def lw_ensure_bonfire_anchor(self):
        """角色在目标篝火旁时校准该地点的地图锚点(仅首次或上次识别失败时执行)。"""
        if self._lw_is_volcano_location():
            return
        path = self._lw_anchor_path()
        if self._lw_anchor_is_current(path) and not getattr(self, "_lw_anchor_failed", False):
            return
        try:
            self.ensure_main()
            self.open_map()
            frame = self.frame
            calibration_box = self._lw_anchor_calibration_box()
            icons = self.find_feature(Labels.bonfire_teleport, box=calibration_box, threshold=0.7)
            if not icons:
                self.log_warning_gated("no bonfire icon for anchor calibration")
                return
            icon = self._lw_select_anchor_icon(icons)
            cx = icon.x + icon.width // 2
            cy = icon.y + icon.height // 2
            for size in self.LW_ANCHOR_CALIBRATE_SIZES:
                crop = self._lw_crop_centered(frame, cx, cy, size)
                if crop is None:
                    continue
                if not self._lw_anchor_is_unique(frame, crop):
                    continue
                os.makedirs(os.path.dirname(path), exist_ok=True)
                cv2.imwrite(path, crop)
                with open(path + ".json", "w", encoding="utf-8") as meta_file:
                    json.dump(
                        {
                            "version": self.LW_ANCHOR_VERSION,
                            "width": frame.shape[1],
                            "height": frame.shape[0],
                        },
                        meta_file,
                    )
                self._lw_anchor_failed = False
                self.log_info(f"bonfire anchor calibrated: {path} size={size}")
                return
            self.log_warning_gated("could not calibrate a unique bonfire anchor")
        except Exception as e:
            self.log_warning_gated(f"bonfire anchor calibration failed: {e}")
        finally:
            with suppress(Exception):
                self.ensure_main()

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

    def _lw_teleport_via_anchor(self, fallback):
        """优先用地图锚点定位正确篝火; 失败时在当前地图内回退到确定性搜索。"""
        path = self._lw_anchor_path()
        if not os.path.exists(path) or getattr(self, "_lw_anchor_failed", False):
            return fallback()
        self.ensure_main()
        self.open_map()
        match = self._lw_find_bonfire_anchor(path)
        if match is None:
            self._lw_anchor_failed = True
            self.screenshot("dsd_farm_anchor_not_found")
            self.log_warning_gated("bonfire anchor not found on map, fallback without reopening map")
            return fallback(map_is_open=True)
        self.log_info(f"found bonfire anchor {match}")
        self.operate_click(match, action_name="click_bonfire_anchor")
        self.sleep(0.5)
        return self.click_traval_button(raise_if_not_found=False)

    def _lw_anchor_path(self):
        location = self.config.get(self.CONF_LOCATION, self.locations[0])
        slugs = {
            self.locations[0]: "volcano_bottom_left",
            self.locations[1]: "dragon_tower",
            self.locations[2]: "silken_alley",
        }
        slug = slugs.get(location, "unknown")
        return os.path.join(self.LW_ANCHOR_FOLDER, f"bonfire_anchor_{slug}.png")

    def _lw_anchor_is_current(self, path):
        """Require versioned metadata so old, weakly selected anchors are rebuilt."""
        if not os.path.exists(path):
            return False
        try:
            with open(path + ".json", encoding="utf-8") as meta_file:
                meta = json.load(meta_file)
            return meta.get("version") == self.LW_ANCHOR_VERSION
        except (OSError, AttributeError, TypeError, ValueError, json.JSONDecodeError):
            return False

    def _lw_anchor_calibration_box(self):
        """Use the same location-specific map region as the deterministic fallback."""
        location = self.config.get(self.CONF_LOCATION, self.locations[0])
        if location == self.locations[1]:
            return self.box_of_screen(0.498, 0.102, 0.931, 0.827)
        if location == self.locations[2]:
            return self.box_of_screen(0.410, 0.234, 0.560, 0.556)
        return self.main_viewport

    def _lw_select_anchor_icon(self, icons):
        """Choose the known target icon instead of the map-center nearest icon."""
        if self._lw_is_volcano_location():
            return self._lw_select_volcano_bonfire(icons)
        return min(icons, key=lambda icon: icon.y)

    def _lw_is_volcano_location(self):
        try:
            return self.config.get(self.CONF_LOCATION, self.locations[0]) == self.locations[0]
        except AttributeError:
            return False

    @staticmethod
    def _lw_select_volcano_bonfire(icons):
        """The configured volcano target is the leftmost bonfire on the bottom layer."""
        return min(icons, key=lambda icon: (icon.x, -icon.y))

    def _lw_load_anchor(self, path):
        anchor = cv2.imread(path, cv2.IMREAD_COLOR)
        if anchor is None:
            return None
        meta_path = path + ".json"
        try:
            if os.path.exists(meta_path):
                with open(meta_path, encoding="utf-8") as meta_file:
                    meta = json.load(meta_file)
                scale_x = self.width / meta["width"]
                scale_y = self.height / meta["height"]
                if abs(scale_x - 1) > 0.01 or abs(scale_y - 1) > 0.01:
                    anchor = cv2.resize(
                        anchor,
                        None,
                        fx=scale_x,
                        fy=scale_y,
                        interpolation=cv2.INTER_AREA,
                    )
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            self.log_warning_gated("failed to load bonfire anchor metadata")
        return anchor

    def _lw_find_bonfire_anchor(self, path):
        anchor = self._lw_load_anchor(path)
        if anchor is None:
            return None
        frame = self.frame
        view_box = self.main_viewport
        view = view_box.crop_frame(frame)
        if view.shape[0] < anchor.shape[0] or view.shape[1] < anchor.shape[1]:
            return None
        result = cv2.matchTemplate(view, anchor, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < self.LW_ANCHOR_THRESHOLD:
            return None
        if not self._lw_anchor_match_is_unique(result, anchor.shape):
            self.log_warning_gated("bonfire anchor match is ambiguous")
            return None
        return Box(
            view_box.x + max_loc[0],
            view_box.y + max_loc[1],
            anchor.shape[1],
            anchor.shape[0],
            max_val,
            "bonfire_anchor",
        )

    def _lw_crop_centered(self, frame, cx, cy, size):
        half = size // 2
        x0 = max(0, cx - half)
        y0 = max(0, cy - half)
        x1 = min(frame.shape[1], cx + half)
        y1 = min(frame.shape[0], cy + half)
        crop = frame[y0:y1, x0:x1]
        if crop.shape[0] < size * 0.6 or crop.shape[1] < size * 0.6:
            return None
        return crop

    def _lw_anchor_is_unique(self, frame, crop, view_box=None):
        """自检: 锚点在当前地图区域内必须能高置信度唯一匹配。"""
        box = view_box or self.main_viewport
        view = box.crop_frame(frame)
        if view.shape[0] < crop.shape[0] or view.shape[1] < crop.shape[1]:
            return False
        result = cv2.matchTemplate(view, crop, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        if max_val < self.LW_ANCHOR_THRESHOLD:
            return False
        return self._lw_anchor_match_is_unique(result, crop.shape)

    def _lw_anchor_match_is_unique(self, result, anchor_shape):
        """Reject similarly strong matches at separate map locations."""
        max_val = float(np.max(result))
        ys, xs = np.where(result >= max_val - self.LW_ANCHOR_PEAK_MARGIN)
        peaks = []
        for x, y in zip(xs, ys):
            if all(
                abs(int(x) - px) > anchor_shape[1] * 0.6
                or abs(int(y) - py) > anchor_shape[0] * 0.6
                for px, py in peaks
            ):
                peaks.append((int(x), int(y)))
        return len(peaks) == 1
