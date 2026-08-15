import unittest
from types import SimpleNamespace
from unittest import mock

from ok import Box, CannotFindException, TaskDisabledException, WaitFailedException

from src.lw import dsd_farm_ext
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
        self.paused = False
        self.executor = SimpleNamespace(check_enabled=lambda **kwargs: None, paused=False)

    def find_traval_button(self):
        return self.travel_btn_results.pop(0) if self.travel_btn_results else None

    def wait_until(self, condition, time_out=10, raise_if_not_found=False, **kwargs):
        if pre_action := kwargs.get("pre_action"):
            pre_action()
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


class TestRefreshMonsterConfirmation(unittest.TestCase):
    def test_current_ru_refresh_confirms_the_update_dialog_and_no_remind_option(self):
        task = object.__new__(DSDFarmTask)
        changed_box = Box(0, 0, 10, 10, name="changed")
        no_remind_box = Box(0, 0, 10, 10, name="no_remind")
        task.box_of_screen = mock.Mock(return_value=changed_box)
        task.operate_click = mock.Mock()
        task.find_one = mock.Mock(return_value=no_remind_box)
        task.wait_until = mock.Mock(side_effect=lambda condition, **_kwargs: condition())

        def run_and_check_changed(action, **_kwargs):
            action()
            return True

        task.run_and_check_changed = mock.Mock(side_effect=run_and_check_changed)

        def wait_click_confirm(**kwargs):
            kwargs["on_found"]()
            return True

        task.wait_click_confirm = mock.Mock(side_effect=wait_click_confirm)

        task.refresh_monster()

        task.operate_click.assert_has_calls(
            [mock.call(0.057, 0.218), mock.call(no_remind_box, after_sleep=0.5)]
        )
        task.wait_click_confirm.assert_called_once_with(
            range=(0.650, 0.611, 0.707, 0.708),
            on_found=mock.ANY,
            time_out=3,
        )

    def test_current_ru_refresh_skips_the_dialog_when_the_refresh_click_has_no_effect(self):
        task = object.__new__(DSDFarmTask)
        task.box_of_screen = mock.Mock(return_value=Box(0, 0, 10, 10, name="changed"))
        task.run_and_check_changed = mock.Mock(return_value=False)
        task.wait_click_confirm = mock.Mock()

        task.refresh_monster()

        task.wait_click_confirm.assert_not_called()


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

    def test_top_bonfire_selects_the_uppermost_result_without_an_anchor(self):
        task = object.__new__(DSDFarmExtMixin)
        lower = Box(20, 80, 10, 10)
        upper = Box(40, 30, 10, 10)
        task.ensure_main = mock.Mock()
        task.open_map = mock.Mock()
        task.find_feature = mock.Mock(return_value=[lower, upper])
        task.log_info = mock.Mock()
        task.operate_click = mock.Mock()
        task.lw_perform_input = lambda action, *args, **kwargs: action(*args, **kwargs)
        task.sleep = mock.Mock()
        task.click_traval_button = mock.Mock(return_value=True)

        self.assertTrue(task.lw_teleport_to_top_bonfire(Box(0, 0, 100, 100)))

        task.operate_click.assert_called_once_with(upper, action_name="click_map_teleport")


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
        task.lw_hold_key_cancellable = lambda *args, **kwargs: None
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

    def test_propagates_stop_from_teleport_without_recovery_actions(self):
        task = self._task()
        task.ensure_main = mock.Mock()

        with self.assertRaises(TaskDisabledException):
            task.ensure_teleport(lambda: (_ for _ in ()).throw(TaskDisabledException()))

        task.ensure_main.assert_not_called()

    def test_propagates_stop_from_ensure_main_without_movement(self):
        task = self._task()
        task.ensure_main = mock.Mock(side_effect=TaskDisabledException())
        task.lw_hold_key_cancellable = mock.Mock()

        with self.assertRaises(TaskDisabledException):
            task.ensure_teleport(lambda: False)

        task.lw_hold_key_cancellable.assert_not_called()


class TestCancellableInput(unittest.TestCase):
    def test_does_not_run_input_after_stop(self):
        task = object.__new__(DSDFarmExtMixin)
        action = mock.Mock()
        task.paused = False
        task.executor = SimpleNamespace(
            check_enabled=mock.Mock(side_effect=TaskDisabledException()), paused=False
        )

        with self.assertRaises(TaskDisabledException):
            task.lw_perform_input(action)

        action.assert_not_called()

    def test_releases_recovery_key_when_stop_interrupts_hold(self):
        task = object.__new__(DSDFarmExtMixin)
        interaction = mock.Mock()
        task.paused = False
        task.executor = SimpleNamespace(
            check_enabled=mock.Mock(side_effect=[None, TaskDisabledException()]),
            interaction=interaction,
            paused=False,
        )

        with mock.patch.object(dsd_farm_ext.time, "sleep"):
            with self.assertRaises(TaskDisabledException):
                task.lw_hold_key_cancellable("w", duration=3)

        interaction.send_key_down.assert_called_once_with("w")
        interaction.send_key_up.assert_called_once_with("w")

    def test_waits_for_task_resume_before_sending_input(self):
        task = object.__new__(DSDFarmExtMixin)
        action = mock.Mock()
        task.paused = True
        task.executor = SimpleNamespace(check_enabled=mock.Mock(), paused=False)

        def resume_task(_):
            task.paused = False

        with mock.patch.object(dsd_farm_ext.time, "sleep", side_effect=resume_task):
            task.lw_perform_input(action)

        action.assert_called_once()

    def test_releases_recovery_key_when_task_pauses(self):
        task = object.__new__(DSDFarmExtMixin)
        interaction = mock.Mock()
        task.paused = False
        task.executor = SimpleNamespace(
            check_enabled=mock.Mock(side_effect=[None, None, None, TaskDisabledException()]),
            interaction=interaction,
            paused=False,
        )

        sleep_calls = 0

        def change_pause_state(_):
            nonlocal sleep_calls
            sleep_calls += 1
            task.paused = sleep_calls == 1

        with mock.patch.object(dsd_farm_ext.time, "sleep", side_effect=change_pause_state):
            with self.assertRaises(TaskDisabledException):
                task.lw_hold_key_cancellable("w", duration=3)

        interaction.send_key_down.assert_called_once_with("w")
        interaction.send_key_up.assert_called_once_with("w")

    def test_detects_task_and_global_pause_independently(self):
        task = object.__new__(DSDFarmExtMixin)
        task.executor = SimpleNamespace(paused=False)

        task.paused = False
        self.assertFalse(task.lw_input_paused())
        task.paused = True
        self.assertTrue(task.lw_input_paused())
        task.paused = False
        task.executor.paused = True
        self.assertTrue(task.lw_input_paused())


if __name__ == "__main__":
    unittest.main()
