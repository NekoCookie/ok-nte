"""AutoCombatTask must set the combat-session ultimate policy from its configuration."""
import os
import sys
import unittest
from contextlib import nullcontext
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lw.team_roster import TeamReloadRequested, TeamRosterChange
from src.tasks.trigger.AutoCombatTask import AutoCombatTask


def make_run_task(use_ult_config):
    t = AutoCombatTask.__new__(AutoCombatTask)
    t.CONF_USE_ULT = "使用终结技"
    t.config = {"使用终结技": use_ult_config}
    t.scene = mock.MagicMock()
    t.scene.is_in_team.return_value = True
    t.is_in_team = mock.MagicMock()
    t.in_combat = mock.MagicMock(side_effect=[True, True, False])
    t._last_team_recheck = 0.0
    t.combat_session = None
    t.begin_combat_session = mock.MagicMock()
    t.team_reload_watch = mock.MagicMock(return_value=nullcontext())
    t._reload_if_team_size_changed = mock.MagicMock(return_value=True)
    t.get_current_char = mock.MagicMock(return_value=mock.MagicMock())
    t.combat_end = mock.MagicMock()
    return t


class TestUseUltimateConfig(unittest.TestCase):
    def test_use_ultimate_disabled_by_config(self):
        t = make_run_task(False)
        t.run()
        self.assertFalse(t.combat_session.use_ultimate)

    def test_use_ultimate_enabled_by_config(self):
        t = make_run_task(True)
        t.run()
        self.assertTrue(t.combat_session.use_ultimate)

    def test_use_ultimate_defaults_true_when_missing(self):
        t = make_run_task(True)
        t.config = {}  # 配置缺失 → 默认 True
        t.combat_session.use_ultimate = False
        t.run()
        self.assertTrue(t.combat_session.use_ultimate)

    def test_confirmed_team_change_reloads_instead_of_ending_combat(self):
        t = make_run_task(True)
        change = TeamRosterChange(kind="size", expected_count=4, observed_count=2)
        t._reload_if_team_size_changed.side_effect = TeamReloadRequested(change)
        t._reload_combat_team = mock.MagicMock(return_value=True)

        t.run()

        t._reload_combat_team.assert_called_once_with()
        t.combat_end.assert_called_once_with()

    def test_action_error_still_runs_combat_cleanup(self):
        t = make_run_task(True)
        current_char = mock.MagicMock()
        current_char.perform.side_effect = RuntimeError("action failed")
        t.get_current_char.return_value = current_char

        with self.assertRaisesRegex(RuntimeError, "action failed"):
            t.run()

        t.combat_end.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
