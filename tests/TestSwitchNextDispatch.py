"""切人单轨回归：主决策与切人途中重规划都必须走 CombatPlanner。"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.combat.BaseCombatTask import BaseCombatTask


class TestSwitchNextDispatch(unittest.TestCase):
    def test_decide_switch_to_delegates_to_planner(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.combat_planner = mock.MagicMock()
        decision = mock.MagicMock(target="target", has_intro=True)
        task.combat_planner.decide_switch.return_value = decision
        current = mock.MagicMock()

        self.assertEqual(
            task._decide_switch_to(current, free_intro=True, require_intro=True),
            ("target", True),
        )
        task.combat_planner.decide_switch.assert_called_once_with(
            current,
            free_intro=True,
            require_intro=True,
        )

    def test_switch_next_char_uses_planner(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.chars = [mock.MagicMock(), mock.MagicMock()]
        task.combat_planner = mock.MagicMock()
        decision = mock.MagicMock()
        decision.target = None
        decision.has_intro = False
        decision.reason = "keep current"
        task.combat_planner.decide_switch.return_value = decision
        task.run_with_interval = mock.MagicMock()
        current = mock.MagicMock()

        task.switch_next_char(current)

        task.combat_planner.decide_switch.assert_called_once_with(
            current,
            free_intro=False,
        )
        current.click_with_interval.assert_called_once()

    def test_single_char_team_does_not_ask_planner_to_switch(self):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.chars = [mock.MagicMock()]
        task.combat_planner = mock.MagicMock()
        task.click = mock.MagicMock()

        task.switch_next_char(mock.MagicMock())

        task.click.assert_called_once()
        task.combat_planner.decide_switch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
