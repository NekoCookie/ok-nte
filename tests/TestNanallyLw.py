import unittest
from unittest import mock

from src.char.Nanally import Nanally


class TestNanallyLw(unittest.TestCase):
    def _char(self):
        char = object.__new__(Nanally)
        char.click_skill_action = mock.Mock(return_value="skill")
        char.click_ultimate_action = mock.Mock(return_value="ultimate")
        return char

    def test_plan_uses_lw_landed_hook_after_the_ultimate_action(self):
        char = self._char()
        char.ultimate_available = mock.Mock(return_value=True)
        char.lw_ultimate_action_landed = mock.Mock(return_value=True)
        char.perform_in_ult = mock.Mock()
        char.plan = mock.Mock(side_effect=lambda *_actions, **kwargs: kwargs["entry"])

        entry = char.combat_plan("context")()
        self.assertEqual(next(entry), "skill")
        self.assertEqual(entry.send(False), "ultimate")
        with self.assertRaises(StopIteration):
            entry.send(False)

        char.lw_ultimate_action_landed.assert_called_once_with(False, True)
        char.perform_in_ult.assert_called_once_with("context", "skill")

    def test_ultimate_field_loop_uses_lw_continue_hook(self):
        char = self._char()
        char.lw_should_continue_ultimate_field = mock.Mock(return_value=False)
        context = mock.Mock()

        with mock.patch("src.char.Nanally.time.time", side_effect=[0.0, 0.1]):
            self.assertFalse(char.perform_in_ult(context, "skill"))

        char.lw_should_continue_ultimate_field.assert_called_once_with(0.1)
        context.is_action_allowed.assert_not_called()

    def test_landed_hook_accepts_a_visible_cooldown_transition(self):
        char = self._char()
        char.ultimate_available = mock.Mock(return_value=False)

        self.assertTrue(char.lw_ultimate_action_landed(False, True))
        self.assertFalse(char.lw_ultimate_action_landed(False, False))
        self.assertTrue(char.lw_ultimate_action_landed(True, False))


if __name__ == "__main__":
    unittest.main()
