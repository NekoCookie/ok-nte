import unittest
from types import SimpleNamespace
from unittest import mock

from ok import Box, CannotFindException, TaskDisabledException, WaitFailedException

from src.lw.dsd_farm_ext import DSDFarmExtMixin
from src.tasks.DSDFarmTask import DSDFarmTask


class _BaseClick:
    """模拟 RU 被保留的 _ru_* 原实现, 两个传送搜索都有确定性行为。"""

    def __init__(self):
        self.fallback_nearest_calls = 0
        self.fallback_top_calls = 0

    def _ru_teleport_to_nearest_bonfire(
        self, threshold=0.7, time_out=10, target_selector=None
    ):
        self.fallback_nearest_calls += 1
        self.fallback_nearest_selector = target_selector
        return True

    def _ru_teleport_to_top_bonfire(self, box, threshold=0.7):
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


class _DeterministicTeleportStub(DSDFarmExtMixin, _BaseClick):
    pass


class TestDeterministicTeleportSelection(unittest.TestCase):
    def test_volcano_selector_chooses_leftmost_bonfire(self):
        left = Box(20, 100, 10, 10)
        right = Box(40, 50, 10, 10)

        self.assertIs(DSDFarmExtMixin._lw_select_volcano_bonfire([right, left]), left)

    def test_top_bonfire_uses_deterministic_fallback_without_anchor(self):
        task = _DeterministicTeleportStub()

        self.assertTrue(task.lw_teleport_to_top_bonfire(Box(0, 0, 100, 100)))
        self.assertEqual(task.fallback_top_calls, 1)


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
