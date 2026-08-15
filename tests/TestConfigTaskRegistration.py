import unittest

from src.config import config


_ONETIME_TASKS = frozenset(map(tuple, config["onetime_tasks"]))
_TRIGGER_TASKS = frozenset(map(tuple, config["trigger_tasks"]))


class TestConfigTaskRegistration(unittest.TestCase):
    def test_committed_lw_task_registrations_remain_available(self):
        self.assertTrue(
            {
                ("src.tasks.SwitchAccountTask", "SwitchAccountTask"),
                ("src.tasks.FishCatchingTask", "FishCatchingTask"),
            }.issubset(_ONETIME_TASKS)
        )
        self.assertTrue(
            {
                ("src.tasks.trigger.RequiemCombatConfigTask", "RequiemCombatConfigTask"),
                ("src.tasks.trigger.NanallySuperJumpTask", "NanallySuperJumpTask"),
            }.issubset(_TRIGGER_TASKS)
        )


if __name__ == "__main__":
    unittest.main()
