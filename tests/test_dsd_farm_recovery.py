import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from ok import Box, CannotFindException, TaskDisabledException, WaitFailedException

from src.lw.dsd_farm_ext import DSDFarmExtMixin
from src.tasks.DSDFarmTask import DSDFarmTask


class _BaseClick:
    """模拟 RU 被保留的 _ru_* 原实现, 两个传送搜索都有确定性行为。"""

    def __init__(self):
        self.fallback_nearest_calls = 0
        self.fallback_top_calls = 0

    def _ru_teleport_to_nearest_bonfire(
        self, threshold=0.7, time_out=10, map_is_open=False, target_selector=None
    ):
        self.fallback_nearest_calls += 1
        self.fallback_nearest_selector = target_selector
        return True

    def _ru_teleport_to_top_bonfire(self, box, threshold=0.7, map_is_open=False):
        self.fallback_top_calls += 1
        return True


class _ClickStub(DSDFarmExtMixin, _BaseClick):
    def __init__(self, travel_btn_sequence):
        super().__init__()
        self.travel_btn_results = list(travel_btn_sequence)
        self.warnings = []
        self.clicked = []

    def find_traval_button(self):
        return self.travel_btn_results.pop(0) if self.travel_btn_results else None

    def wait_until(self, condition, time_out=10, raise_if_not_found=False, **kwargs):
        return condition()

    def operate_click(self, box, **kwargs):
        self.clicked.append(box)

    def sleep(self, seconds):
        pass

    def monitor_and_sync_cursor(self, **kwargs):
        pass

    def log_warning_gated(self, msg):
        self.warnings.append(msg)


class TestClickTravalButton(unittest.TestCase):
    def test_returns_false_when_travel_button_still_visible(self):
        task = _ClickStub([Box(0, 0, 10, 10, name="travel"), Box(0, 0, 10, 10, name="travel")])
        self.assertFalse(task.click_traval_button())
        self.assertEqual(len(task.warnings), 1)

    def test_returns_true_when_travel_button_disappeared(self):
        task = _ClickStub([Box(0, 0, 10, 10, name="travel"), None])
        self.assertTrue(task.click_traval_button())
        self.assertEqual(len(task.warnings), 0)

    def test_returns_false_when_travel_button_never_appears(self):
        task = _ClickStub([])
        self.assertFalse(task.click_traval_button(raise_if_not_found=False))
        self.assertEqual(len(task.warnings), 0)


class _InteracStub(DSDFarmExtMixin, _BaseClick):
    def __init__(self, interac_results):
        super().__init__()
        self._results = list(interac_results)
        self.ensure_main_calls = 0
        self.reteleport_calls = 0
        self.sleep_calls = 0
        self.screenshots = []
        self.warnings = []

    def find_interac(self):
        return self._results.pop(0) if self._results else None

    def wait_until(self, condition, time_out=10, raise_if_not_found=False, **kwargs):
        result = condition()
        if not result and raise_if_not_found:
            raise WaitFailedException()
        return result

    def ensure_main(self, **kwargs):
        self.ensure_main_calls += 1

    def lw_teleport_back_to_location(self):
        self.reteleport_calls += 1

    def sleep(self, seconds):
        self.sleep_calls += 1

    def screenshot(self, name):
        self.screenshots.append(name)

    def log_warning_gated(self, msg):
        self.warnings.append(msg)


class TestLwWaitInterac(unittest.TestCase):
    def test_recovers_with_reteleport(self):
        task = _InteracStub([None, None, Box(0, 0, 1, 1, name="interac")])
        self.assertTrue(task.lw_wait_interac(time_out=10))
        self.assertEqual(task.ensure_main_calls, 1)
        self.assertEqual(task.reteleport_calls, 1)
        self.assertEqual(task.screenshots, [])

    def test_raises_when_recovery_fails(self):
        task = _InteracStub([None, None, None])
        with self.assertRaises(WaitFailedException):
            task.lw_wait_interac(time_out=10)
        self.assertEqual(task.ensure_main_calls, 1)
        self.assertEqual(task.reteleport_calls, 1)
        self.assertEqual(task.screenshots, ["dsd_farm_interac_missing"])


class _AnchorTeleportStub(DSDFarmExtMixin, _BaseClick):
    def __init__(self, tmp_dir, anchor_exists=True, match=None):
        super().__init__()
        self._anchor_path = os.path.join(tmp_dir, "anchor.png")
        if anchor_exists:
            with open(self._anchor_path, "w", encoding="utf-8") as f:
                f.write("x")
        self._match = match
        self.ensure_main_calls = 0
        self.open_map_calls = 0
        self.clicked = []
        self.fallback_calls = 0
        self.fallback_map_states = []
        self.screenshots = []
        self.warnings = []
        self.infos = []
        self._lw_anchor_failed = False

    def _lw_anchor_path(self):
        return self._anchor_path

    def _lw_find_bonfire_anchor(self, path):
        return self._match

    def ensure_main(self, **kwargs):
        self.ensure_main_calls += 1

    def open_map(self):
        self.open_map_calls += 1

    def operate_click(self, box, **kwargs):
        self.clicked.append(box)

    def sleep(self, seconds):
        pass

    def click_traval_button(self, travel_btn=None, raise_if_not_found=True):
        return True

    def screenshot(self, name):
        self.screenshots.append(name)

    def log_info(self, msg):
        self.infos.append(msg)

    def log_warning_gated(self, msg):
        self.warnings.append(msg)

    def fallback(self, map_is_open=False):
        self.fallback_calls += 1
        self.fallback_map_states.append(map_is_open)
        return True


class TestTeleportViaAnchor(unittest.TestCase):
    def test_clicks_anchor_when_found(self):
        match = Box(100, 100, 50, 50, name="bonfire_anchor")
        with tempfile.TemporaryDirectory() as tmp:
            task = _AnchorTeleportStub(tmp, match=match)
            self.assertTrue(task._lw_teleport_via_anchor(task.fallback))
            self.assertEqual(task.clicked, [match])
            self.assertEqual(task.fallback_calls, 0)
            self.assertEqual(task.open_map_calls, 1)
            self.assertEqual(task.screenshots, [])

    def test_missing_anchor_falls_back_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = _AnchorTeleportStub(tmp, anchor_exists=False)
            self.assertTrue(task._lw_teleport_via_anchor(task.fallback))
            self.assertEqual(task.fallback_calls, 1)
            self.assertEqual(task.fallback_map_states, [False])
            self.assertEqual(task.open_map_calls, 0)
            self.assertEqual(task.screenshots, [])

    def test_anchor_not_found_falls_back_without_reopening_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = _AnchorTeleportStub(tmp, match=None)
            self.assertTrue(task._lw_teleport_via_anchor(task.fallback))
            self.assertEqual(task.open_map_calls, 1)
            self.assertEqual(task.fallback_calls, 1)
            self.assertEqual(task.fallback_map_states, [True])
            self.assertEqual(task.screenshots, ["dsd_farm_anchor_not_found"])
            self.assertTrue(task._lw_anchor_failed)

    def test_failed_anchor_is_bypassed_on_next_teleport_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = _AnchorTeleportStub(tmp, match=None)
            self.assertTrue(task._lw_teleport_via_anchor(task.fallback))
            self.assertTrue(task._lw_teleport_via_anchor(task.fallback))
            self.assertEqual(task.open_map_calls, 1)
            self.assertEqual(task.fallback_map_states, [True, False])

    def test_rejects_ambiguous_anchor_matches(self):
        anchor = np.arange(12 * 12 * 3, dtype=np.uint8).reshape(12, 12, 3)
        frame = np.zeros((160, 160, 3), dtype=np.uint8)
        frame[20:32, 20:32] = anchor
        frame[100:112, 100:112] = anchor
        task = object.__new__(DSDFarmExtMixin)
        task.frame = frame
        task.main_viewport = Box(0, 0, 160, 160)
        task._lw_load_anchor = lambda path: anchor
        task.log_warning_gated = mock.Mock()

        self.assertIsNone(task._lw_find_bonfire_anchor("anchor.png"))
        task.log_warning_gated.assert_called_once_with("bonfire anchor match is ambiguous")

    def test_nearest_bonfire_wiring_uses_anchor(self):
        task = _WiringStub()
        result = task.lw_teleport_to_nearest_bonfire(threshold=0.8, time_out=5)
        self.assertTrue(result)
        self.assertEqual(task.fallback_nearest_calls, 1)
        left = Box(10, 100, 10, 10)
        right = Box(20, 90, 10, 10)
        self.assertEqual(task.fallback_nearest_selector([right, left]), left)

    def test_top_bonfire_wiring_uses_anchor(self):
        task = _WiringStub()
        result = task.lw_teleport_to_top_bonfire(Box(0, 0, 100, 100), threshold=0.9)
        self.assertTrue(result)
        self.assertEqual(task.fallback_top_calls, 1)


class TestRuDelegation(unittest.TestCase):
    def test_nearest_bonfire_public_method_delegates_to_lw(self):
        task = object.__new__(DSDFarmTask)
        calls = []
        task.lw_teleport_to_nearest_bonfire = lambda **kwargs: (calls.append(kwargs) or "lw")
        result = task.teleport_to_nearest_bonfire(threshold=0.8, time_out=5)
        self.assertEqual(result, "lw")
        self.assertEqual(calls, [{"threshold": 0.8, "time_out": 5}])

    def test_top_bonfire_public_method_delegates_to_lw(self):
        task = object.__new__(DSDFarmTask)
        calls = []
        task.lw_teleport_to_top_bonfire = lambda **kwargs: (calls.append(kwargs) or "lw")
        result = task.teleport_to_top_bonfire(Box(0, 0, 10, 10), threshold=0.9)
        self.assertEqual(result, "lw")
        self.assertEqual(calls, [{"box": Box(0, 0, 10, 10), "threshold": 0.9}])


class _WiringStub(DSDFarmExtMixin, _BaseClick):
    def __init__(self):
        super().__init__()
        self.via_calls = []

    def _lw_teleport_via_anchor(self, fallback):
        self.via_calls.append(fallback)
        return fallback()


class _CalibStub(DSDFarmExtMixin, _BaseClick):
    def __init__(self, tmp_dir, icon=None, icons=None, unique=True):
        super().__init__()
        self.tmp_dir = tmp_dir
        self.icons = list(icons) if icons is not None else ([icon] if icon else [])
        self.unique = unique
        self.ensure_main_calls = 0
        self.open_map_calls = 0
        self.warnings = []
        self.infos = []
        self._lw_anchor_failed = False
        self.frame = np.zeros((200, 300, 3), dtype=np.uint8)
        self.CONF_LOCATION = "位置"
        self.locations = ["火山", "高塔", "残丝"]
        self._location = "高塔"
        self.crop_center = None

    def _lw_anchor_path(self):
        return os.path.join(self.tmp_dir, "anchor.png")

    def ensure_main(self, **kwargs):
        self.ensure_main_calls += 1

    def open_map(self):
        self.open_map_calls += 1

    def find_feature(self, label, box=None, threshold=0.7):
        return self.icons

    @property
    def config(self):
        return SimpleNamespace(get=lambda key, default=None: self._location)

    def box_of_screen(self, x1, y1, x2, y2):
        return Box(x1 * 300, y1 * 200, (x2 - x1) * 300, (y2 - y1) * 200)

    @property
    def main_viewport(self):
        return Box(0, 0, 300, 200)

    @property
    def default_box(self):
        return SimpleNamespace(center=Box(0, 0, 1, 1))

    def _lw_anchor_is_unique(self, frame, crop):
        return self.unique

    def _lw_crop_centered(self, frame, cx, cy, size):
        self.crop_center = (cx, cy)
        return np.zeros((size, size, 3), dtype=np.uint8)

    def log_info(self, msg):
        self.infos.append(msg)

    def log_warning_gated(self, msg):
        self.warnings.append(msg)


class TestAnchorCalibration(unittest.TestCase):
    def test_skips_when_anchor_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "anchor.png")
            with open(path, "w", encoding="utf-8") as f:
                f.write("x")
            task = _CalibStub(tmp, icon=Box(150, 100, 10, 10))
            with open(path + ".json", "w", encoding="utf-8") as f:
                json.dump({"version": task.LW_ANCHOR_VERSION}, f)
            task.lw_ensure_bonfire_anchor()
            self.assertEqual(task.open_map_calls, 0)

    def test_rebuilds_legacy_anchor_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "anchor.png")
            with open(path, "w", encoding="utf-8") as f:
                f.write("x")
            with open(path + ".json", "w", encoding="utf-8") as f:
                json.dump({"width": 2560, "height": 1440}, f)
            task = _CalibStub(tmp, icon=Box(150, 100, 10, 10))

            task.lw_ensure_bonfire_anchor()

            self.assertEqual(task.open_map_calls, 1)
            with open(path + ".json", encoding="utf-8") as f:
                self.assertEqual(json.load(f)["version"], task.LW_ANCHOR_VERSION)

    def test_recalibrates_after_anchor_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "anchor.png")
            with open(path, "w", encoding="utf-8") as f:
                f.write("x")
            task = _CalibStub(tmp, icon=Box(150, 100, 10, 10))
            task._lw_anchor_failed = True
            task.lw_ensure_bonfire_anchor()
            self.assertEqual(task.open_map_calls, 1)
            self.assertTrue(os.path.exists(path))
            self.assertTrue(os.path.exists(path + ".json"))
            self.assertFalse(task._lw_anchor_failed)

    def test_captures_unique_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = _CalibStub(tmp, icon=Box(150, 100, 10, 10))
            task.lw_ensure_bonfire_anchor()
            path = os.path.join(tmp, "anchor.png")
            self.assertTrue(os.path.exists(path))
            self.assertTrue(os.path.exists(path + ".json"))
            self.assertEqual(task.open_map_calls, 1)
            self.assertEqual(task.ensure_main_calls, 2)
            self.assertFalse(task._lw_anchor_failed)

    def test_warns_when_no_icon(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = _CalibStub(tmp, icon=None)
            task.lw_ensure_bonfire_anchor()
            self.assertFalse(os.path.exists(os.path.join(tmp, "anchor.png")))
            self.assertTrue(any("no bonfire icon" in w for w in task.warnings))

    def test_dragon_tower_calibration_uses_top_icon_in_target_region(self):
        with tempfile.TemporaryDirectory() as tmp:
            top_icon = Box(200, 35, 10, 10)
            lower_icon = Box(120, 120, 10, 10)
            task = _CalibStub(tmp, icons=[lower_icon, top_icon])
            task.lw_ensure_bonfire_anchor()

            self.assertEqual(task.crop_center, (205, 40))

    def test_volcano_calibration_uses_map_marker_and_removes_it_from_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = _CalibStub(tmp, icon=Box(200, 100, 10, 10))
            task._location = "火山"
            task.frame[95:110, 40:55] = (253, 221, 116)
            task.lw_ensure_bonfire_anchor()

            self.assertEqual(task.crop_center, (47, 102))


class TestMapMarkerMask(unittest.TestCase):
    def test_removes_cyan_map_marker_from_anchor_image(self):
        task = object.__new__(DSDFarmExtMixin)
        image = np.full((40, 40, 3), 50, dtype=np.uint8)
        image[10:25, 10:25] = (253, 221, 116)

        cleaned = task._lw_remove_map_player_marker(image)

        self.assertFalse(np.any(task._lw_map_player_marker_mask(cleaned)))


class _PathStub(DSDFarmExtMixin, _BaseClick):
    def __init__(self, location):
        super().__init__()
        self.CONF_LOCATION = "位置"
        self.locations = ["火山", "高塔", "残丝"]
        self._location = location

    @property
    def config(self):
        return SimpleNamespace(get=lambda key, default=None: self._location)


class TestAnchorPaths(unittest.TestCase):
    def test_anchor_paths_are_separate_per_location(self):
        paths = [_PathStub(loc)._lw_anchor_path() for loc in ("火山", "高塔", "残丝")]
        self.assertEqual(len(set(paths)), 3)
        self.assertTrue("volcano_bottom_left" in paths[0])
        self.assertTrue("dragon_tower" in paths[1])
        self.assertTrue("silken_alley" in paths[2])

    def test_unknown_location_gets_fallback_slug(self):
        path = _PathStub("未知")._lw_anchor_path()
        self.assertTrue(path.endswith("bonfire_anchor_unknown.png"))


class _LocationStub(DSDFarmExtMixin, _BaseClick):
    def __init__(self):
        super().__init__()
        self.CONF_LOCATION = "位置"
        self.locations = ["底层篝火", "高塔篝火", "残丝篝火"]
        self.calls = []

    @property
    def config(self):
        return SimpleNamespace(get=lambda key, default=None: "底层篝火")

    def ensure_teleport(self, fun):
        self.calls.append(fun())
        return True

    def teleport_to_nearest_bonfire(self):
        return "nearest"

    def teleport_to_top_bonfire(self, box):
        return "top"


class TestLwTeleportBackToLocation(unittest.TestCase):
    def test_location_0_uses_nearest_bonfire(self):
        task = _LocationStub()
        self.assertTrue(task.lw_teleport_back_to_location())
        self.assertEqual(task.calls, ["nearest"])


class TestEnsureTeleportBounded(unittest.TestCase):
    def _task(self):
        task = object.__new__(DSDFarmTask)
        task.team_dead = False
        task.ensure_main = lambda **kwargs: None
        task.sleep = lambda *args, **kwargs: None
        task.send_key = lambda *args, **kwargs: None
        task.log_warning_gated = lambda *args, **kwargs: None
        return task

    def test_returns_false_after_max_attempts(self):
        task = self._task()
        calls = []
        result = task.ensure_teleport(lambda: (calls.append(1) or False))
        self.assertFalse(result)
        self.assertEqual(len(calls), task.lw_max_teleport_attempts())

    def test_stops_task_after_teleport_recovery_is_exhausted(self):
        task = self._task()
        task.log_error = mock.Mock()
        with self.assertRaises(TaskDisabledException):
            task.lw_ensure_teleport_or_stop(lambda: False)
        task.log_error.assert_called_once()

    def test_keeps_team_dead_fallback_order(self):
        task = self._task()
        task.team_dead = True
        calls = []
        task.teleport_on_spot = lambda: (calls.append("spot") or False)
        origin = lambda: (calls.append("origin") or False)
        result = task.ensure_teleport(origin)
        self.assertFalse(result)
        self.assertEqual(calls[0], "spot")
        self.assertTrue(all(call == "origin" for call in calls[1:]))

    def test_continues_after_fun_raises(self):
        task = self._task()
        calls = []

        def fun():
            calls.append(1)
            if len(calls) == 1:
                raise CannotFindException("boom")
            return False

        result = task.ensure_teleport(fun)
        self.assertFalse(result)
        self.assertEqual(len(calls), task.lw_max_teleport_attempts())

    def test_continues_after_ensure_main_raises(self):
        task = self._task()
        calls = []
        fail = [True]

        def ensure_main(**kwargs):
            if fail[0]:
                fail[0] = False
                raise CannotFindException("main unavailable")

        task.ensure_main = ensure_main
        result = task.ensure_teleport(lambda: (calls.append(1) or False))
        self.assertFalse(result)
        self.assertEqual(len(calls), task.lw_max_teleport_attempts())


if __name__ == "__main__":
    unittest.main()
