import unittest
from types import SimpleNamespace

from ok import Box, WaitFailedException

from src.lw.dsd_farm_ext import DSDFarmExtMixin
from src.tasks.DSDFarmTask import DSDFarmTask


class _BaseClick:
    """模拟上游 click_traval_button 的假成功行为: 无论按钮是否消失都返回 True。"""

    def __init__(self):
        self.base_click_calls = 0

    def click_traval_button(self, travel_btn=None, raise_if_not_found=True):
        self.base_click_calls += 1
        return True


class _ClickStub(DSDFarmExtMixin, _BaseClick):
    def __init__(self, travel_btn):
        super().__init__()
        self.travel_btn = travel_btn
        self.warnings = []

    def find_traval_button(self):
        return self.travel_btn

    def log_warning_gated(self, msg):
        self.warnings.append(msg)


class TestClickTravalButton(unittest.TestCase):
    def test_returns_false_when_travel_button_still_visible(self):
        task = _ClickStub(Box(0, 0, 10, 10, name="travel"))
        self.assertFalse(task.click_traval_button())
        self.assertEqual(task.base_click_calls, 1)
        self.assertEqual(len(task.warnings), 1)

    def test_returns_true_when_travel_button_disappeared(self):
        task = _ClickStub(None)
        self.assertTrue(task.click_traval_button())
        self.assertEqual(task.base_click_calls, 1)
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


class _TeleportStub(DSDFarmExtMixin, _BaseClick):
    def __init__(self, teleports, travel_btn_results):
        super().__init__()
        self.teleports = teleports
        self.travel_btn_results = list(travel_btn_results)
        self.clicked = []
        self.ensure_main_calls = 0
        self.open_map_calls = 0
        self.infos = []
        self.warnings = []

    @property
    def main_viewport(self):
        return object()

    @property
    def default_box(self):
        return SimpleNamespace(center=Box(0, 0, 1, 1))

    def ensure_main(self, **kwargs):
        self.ensure_main_calls += 1

    def open_map(self):
        self.open_map_calls += 1

    def find_feature(self, label, box=None, threshold=0.7):
        return list(self.teleports)

    def wait_until(self, condition, time_out=10, raise_if_not_found=False, **kwargs):
        return condition()

    def operate_click(self, box, **kwargs):
        self.clicked.append(box)

    def sleep(self, seconds):
        pass

    def find_traval_button(self):
        return self.travel_btn_results.pop(0) if self.travel_btn_results else None

    def log_info(self, msg):
        self.infos.append(msg)

    def log_warning_gated(self, msg):
        self.warnings.append(msg)


class TestTeleportCandidates(unittest.TestCase):
    def test_tries_next_candidate_when_no_travel_button(self):
        first = Box(0, 0, 10, 10, name="cand_1")
        second = Box(50, 50, 10, 10, name="cand_2")
        task = _TeleportStub(
            [second, first], [None, Box(0, 0, 1, 1, name="travel"), None]
        )
        self.assertTrue(task.teleport_to_nearest_bonfire())
        self.assertEqual([box.name for box in task.clicked], ["cand_1", "cand_2"])
        self.assertEqual(task.base_click_calls, 1)

    def test_returns_false_when_all_candidates_fail(self):
        first = Box(0, 0, 10, 10, name="cand_1")
        second = Box(50, 50, 10, 10, name="cand_2")
        task = _TeleportStub([second, first], [None, None])
        self.assertFalse(task.teleport_to_nearest_bonfire())
        self.assertEqual([box.name for box in task.clicked], ["cand_1", "cand_2"])
        self.assertEqual(task.base_click_calls, 0)


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


if __name__ == "__main__":
    unittest.main()
