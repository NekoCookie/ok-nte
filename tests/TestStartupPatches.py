import unittest

from src.patches.startup_patches import resolve_runtime_ui_mode


class TestStartupPatches(unittest.TestCase):
    def test_qt_mode(self):
        self.assertEqual(resolve_runtime_ui_mode({"gui": {"type": "qt"}}, []), "qt")

    def test_headless_is_not_qt_mode(self):
        config = {"gui": {"type": "qt"}}

        self.assertIsNone(resolve_runtime_ui_mode(config, ["--headless"]))
        self.assertIsNone(resolve_runtime_ui_mode(config, ["-h"]))

    def test_non_qt_ui_is_not_qt_mode(self):
        self.assertEqual(resolve_runtime_ui_mode({"gui": {"type": "web"}}, []), "web")
        self.assertIsNone(resolve_runtime_ui_mode({"use_gui": False}, []))


if __name__ == "__main__":
    unittest.main()
