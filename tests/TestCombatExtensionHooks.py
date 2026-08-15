from types import SimpleNamespace
import unittest
from unittest import mock

from src.combat.BaseCombatTask import BaseCombatTask


class TestCombatExtensionHooks(unittest.TestCase):
    def test_current_ru_get_cd_delegates_the_snapshot_to_the_lw_policy(self):
        task = object.__new__(BaseCombatTask)
        task.refresh_cd = mock.Mock()
        task.get_current_char = mock.Mock(return_value=SimpleNamespace(index=1))
        task.cds = {1: {"time": 10.0, "skill": 4.0}}
        task.lw_get_cd = mock.Mock(return_value=3.5)

        self.assertEqual(BaseCombatTask.get_cd(task, "skill"), 3.5)

        task.lw_get_cd.assert_called_once_with("skill", 1, task.cds[1])

    def test_lw_preparation_clears_animation_before_resource_observation(self):
        task = object.__new__(BaseCombatTask)
        task.in_animation = True
        task.lw_settle_combat_start_resources = mock.Mock()

        task.lw_prepare_combat_start()

        self.assertFalse(task.in_animation)
        task.lw_settle_combat_start_resources.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
