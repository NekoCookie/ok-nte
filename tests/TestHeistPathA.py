import unittest

from src.heist_path.HeistPathA import HeistPathA


class TestHeistPathA(unittest.TestCase):
    def test_run_path_maps_each_avoider_strategy_to_its_route(self):
        expected_routes = {
            -1: "lg1_wp5_avoid_combat_00",
            0: "lg1_wp5_avoid_combat_01",
            1: "lg1_wp5_avoid_combat_02",
            2: "lg1_wp5_avoid_combat_03",
        }
        route_names = set(expected_routes.values())
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


if __name__ == "__main__":
    unittest.main()
