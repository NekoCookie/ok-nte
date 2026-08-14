import unittest
from contextlib import nullcontext
from unittest import mock

from src.combat.BaseCombatTask import BaseCombatTask, TeamSurvivalStatus


def make_combat_once_task(*, dead=False, in_team=True):
    task = BaseCombatTask.__new__(BaseCombatTask)
    char = mock.MagicMock()
    char.is_dead = dead
    task.chars = [char]
    task.info = {}
    task.wait_until = mock.MagicMock()
    task.begin_combat_session = mock.MagicMock()
    task.retarget_turn_policy = mock.MagicMock(return_value=nullcontext())
    task.in_combat = mock.MagicMock(return_value=False)
    task.combat_end = mock.MagicMock()
    task.wait_in_team = mock.MagicMock(return_value=in_team)
    return task


class TestCombatSurvivalStatus(unittest.TestCase):
    def test_returns_no_deaths_and_forwards_retarget_policy(self):
        task = make_combat_once_task()

        status = task.combat_once(retarget_turn=False)

        self.assertIs(status, TeamSurvivalStatus.NO_DEATHS)
        task.retarget_turn_policy.assert_called_once_with(enable=False)
        task.combat_end.assert_called_once_with()

    def test_returns_dead_when_a_character_was_marked_dead(self):
        task = make_combat_once_task(dead=True)

        status = task.combat_once()

        self.assertIs(status, TeamSurvivalStatus.DEAD)

    def test_returns_wiped_when_team_does_not_reappear(self):
        task = make_combat_once_task(in_team=False)

        status = task.combat_once()

        self.assertIs(status, TeamSurvivalStatus.WIPED)


if __name__ == "__main__":
    unittest.main()
