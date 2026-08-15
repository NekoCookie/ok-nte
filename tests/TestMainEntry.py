import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import main


class _User32:
    METRICS = {
        76: 0,
        77: 0,
        78: 1920,
        79: 1080,
    }

    def GetSystemMetrics(self, index):
        return self.METRICS[index]


class TestSavedWindowGeometry(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self._temp_dir.name)
        self.config_path = self.config_dir / "_ok.json"
        self.windll = SimpleNamespace(user32=_User32())

    def tearDown(self):
        self._temp_dir.cleanup()

    def _repair(self, saved):
        self.config_path.write_text(json.dumps(saved), encoding="utf-8")
        with mock.patch.object(main.ctypes, "windll", self.windll, create=True):
            main._repair_saved_window_geometry({"config_folder": str(self.config_dir)})
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def test_repair_centers_a_saved_window_outside_the_virtual_desktop(self):
        saved = self._repair(
            {
                "window_x": -4000,
                "window_y": -3000,
                "window_width": 1200,
                "window_height": 800,
            }
        )

        self.assertEqual(saved["window_x"], 360)
        self.assertEqual(saved["window_y"], 140)

    def test_repair_leaves_a_visible_saved_window_unchanged(self):
        original = {
            "window_x": 10,
            "window_y": 20,
            "window_width": 1200,
            "window_height": 800,
        }

        saved = self._repair(original)

        self.assertEqual(saved, original)


if __name__ == "__main__":
    unittest.main()
