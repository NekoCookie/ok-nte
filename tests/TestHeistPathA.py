import unittest

from src.heist_path.HeistPathA import HeistPathA
from src.tasks.AutoHeistTask import AutoHeistTask


class TestHeistPathA(unittest.TestCase):
    def test_run_path_selects_g_then_shift_route_for_g_strategy(self):
        path = object.__new__(HeistPathA)
        calls = []

        for method_name in (
            "goto_lg1",
            "wait_team_ui_settle",
            "lg1_wp1",
            "lg1_wp2",
            "lg1_wp3",
            "lg1_wp4",
            "lg1_wp5_avoid_combat_g_then_shift",
            "lg2_wp1_to_exit1",
            "lg2_wp1_remains",
            "lg2_wp2_to_exit2",
            "lg2_wp3_to_layzer_room",
            "lg2_wp3_in_layzer_room",
            "lg2_wp4",
            "lg2_wp4_to_exit1",
        ):
            setattr(path, method_name, lambda name=method_name: calls.append(name))

        path.avoider_strategy_index = lambda: 2
        path.exit_state = {1: True, 2: False}

        path.run_path()

        self.assertIn("lg1_wp5_avoid_combat_g_then_shift", calls)

    def test_run_path_maps_each_avoider_strategy_to_its_route(self):
        expected_routes = {
            -1: "lg1_wp5_avoid_combat_00",
            0: "lg1_wp5_avoid_combat_01",
            1: "lg1_wp5_avoid_combat_02",
            2: "lg1_wp5_avoid_combat_g_then_shift",
        }
        route_names = set(expected_routes.values()) | {"lg1_wp5_avoid_combat_03"}
        for strategy, expected in expected_routes.items():
            with self.subTest(strategy=strategy):
                path = object.__new__(HeistPathA)
                calls = []
                for method_name in (
                    "goto_lg1",
                    "wait_team_ui_settle",
                    "lg1_wp1",
                    "lg1_wp2",
                    "lg1_wp3",
                    "lg1_wp4",
                    *route_names,
                    "lg2_wp1_to_exit1",
                    "lg2_wp1_remains",
                    "lg2_wp2_to_exit2",
                    "lg2_wp3_to_layzer_room",
                    "lg2_wp3_in_layzer_room",
                    "lg2_wp4",
                    "lg2_wp4_to_exit1",
                ):
                    setattr(path, method_name, lambda name=method_name: calls.append(name))
                path.avoider_strategy_index = lambda strategy=strategy: strategy
                path.exit_state = {1: True, 2: False}

                path.run_path()

                self.assertEqual([name for name in calls if name in route_names], [expected])

    def test_g_avoidance_runs_g_then_existing_shift_route(self):
        path = object.__new__(HeistPathA)
        events = []
        path.log_round_info = lambda message: events.append(("log", message))
        path.send_key = lambda key: events.append(("key", key))
        path.sleep = lambda duration: events.append(("sleep", duration))
        path.lg1_wp5_avoid_combat_01 = lambda: events.append(("shift_route",))

        path.lg1_wp5_avoid_combat_g_then_shift()

        self.assertEqual(
            events,
            [
                ("log", "LG1 WP5 G后Shift避战路线"),
                ("key", "g"),
                ("sleep", 0.5),
                ("shift_route",),
            ],
        )

    def test_forced_shift_action_does_not_repeat_g(self):
        task = object.__new__(AutoHeistTask)
        events = []
        task.config = {task.CONF_AVOID_MTH: task.AVOID_METHOD_G}
        task.send_key_down = lambda key: events.append(("down", key))
        task.send_key_up = lambda key: events.append(("up", key))
        task.sleep = lambda duration: events.append(("sleep", duration))

        task.perform_avoidance_action(task.AVOID_METHOD_DASH)

        self.assertEqual(
            events,
            [
                ("down", "w"),
                ("sleep", 0.1),
                ("down", "lshift"),
                ("sleep", 1.0),
                ("up", "lshift"),
                ("sleep", 0.1),
                ("up", "w"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
