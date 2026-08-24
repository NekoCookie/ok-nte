"""Auto Combat configuration regression tests."""

import unittest
from unittest import mock

from src.combat.BaseCombatTask import BaseCombatTask
from src.tasks.trigger.AutoCombatTask import AutoCombatTask


class TestAutoCombatTask(unittest.TestCase):
    def test_entry_ability_setting_is_disabled_by_default(self):
        task = AutoCombatTask.__new__(AutoCombatTask)
        with mock.patch.object(BaseCombatTask, "__init__", return_value=None):
            AutoCombatTask.__init__(task)

        self.assertFalse(task.default_config[task.CONF_EARLY_ENTRY_ABILITY_INPUT])
        self.assertIn(
            "关=保持RU的切人和环合普攻逻辑",
            task.config_description[task.CONF_EARLY_ENTRY_ABILITY_INPUT],
        )


if __name__ == "__main__":
    unittest.main()
