import unittest

from src.globals import Globals
from src.lw.globals_ext import GlobalsExtMixin


class TestGlobalsExtension(unittest.TestCase):
    def test_main_window_hook_is_owned_by_the_lw_mixin(self):
        self.assertIs(Globals.on_show_main_window, GlobalsExtMixin.on_show_main_window)


if __name__ == "__main__":
    unittest.main()
